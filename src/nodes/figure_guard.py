"""Reject narrative prose that contains a figure the evidence does not support.

The TDD says the synthesis node may introduce no figure absent from
``score.*``. That is easy to write in a design document and easy to violate in
practice — a model narrating a verdict will reach for a round number, a
plausible percentage, or a year it half-remembers. This module makes the rule
operational.

**How it works.** Build an allow-set of every number that legitimately appears
in the verdict, the task scores and the retrieved evidence. Extract every
number from the narrative. Anything left over is a fabrication and the
narrative is refused.

**Why it is deliberately conservative about what counts.** Ordinals ("first",
"1."), small counts a reader can verify from the text itself, and years already
present in the evidence are admitted. The aim is to catch a *quantitative
claim* the customer might act on, not to fight English. A guard that fires on
"one of three caveats" would be turned off within a week, and a guard that is
off catches nothing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

LOG = logging.getLogger("nodes.figure_guard")

# Numbers with optional thousands separators, decimals and a trailing percent.
NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*(%?)")

# Small integers are admitted unconditionally: they are almost always structural
# ("the three caveats", "section 2"), and a customer cannot be misled by a count
# they can verify by reading the list in front of them.
STRUCTURAL_MAX = 12

# Tolerance when matching a narrative figure to an allowed value. A model
# writing 0.54 for 0.541 is rounding, not inventing.
ABS_TOLERANCE = 0.01


@dataclass
class Fabrication:
    """One figure in the narrative that the evidence does not support."""

    literal: str
    value: float
    context: str

    def __str__(self) -> str:
        return f"{self.literal!r} in “…{self.context}…”"


@dataclass
class GuardReport:
    """What the guard found."""

    allowed_values: set[float] = field(default_factory=set)
    fabrications: list[Fabrication] = field(default_factory=list)
    checked: int = 0

    @property
    def clean(self) -> bool:
        return not self.fabrications

    def message(self) -> str:
        if self.clean:
            return f"{self.checked} figure(s) checked, all supported by evidence."
        listed = "; ".join(str(f) for f in self.fabrications[:6])
        return (f"{len(self.fabrications)} of {self.checked} figure(s) are not "
                f"supported by the persisted verdict or the retrieved evidence: "
                f"{listed}")


def _numbers_in(text: str) -> list[tuple[str, float]]:
    """Every number in a string, as (literal, value)."""
    found: list[tuple[str, float]] = []
    for match in NUMBER_RE.finditer(text):
        whole, frac, pct = match.group(1), match.group(2), match.group(3)
        literal = match.group(0).strip()
        try:
            value = float(whole.replace(",", "") + (f".{frac}" if frac else ""))
        except ValueError:
            continue
        found.append((literal, value))
        if pct:
            # "36.5%" should match either 36.5 or 0.365 in the evidence, since
            # a share is stored both ways across this project.
            found.append((literal, value / 100.0))
    return found


def _harvest(obj: Any, into: set[float], depth: int = 0) -> None:
    """Collect every number reachable in a nested structure."""
    if depth > 8 or obj is None:
        return
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        into.add(float(obj))
        into.add(round(float(obj) * 100, 6))   # a share expressed as a percent
        return
    if isinstance(obj, str):
        for _literal, value in _numbers_in(obj):
            into.add(value)
        return
    if isinstance(obj, dict):
        for value in obj.values():
            _harvest(value, into, depth + 1)
        return
    if isinstance(obj, (list, tuple, set)):
        for value in obj:
            _harvest(value, into, depth + 1)
        return
    # Pydantic models and dataclasses.
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        _harvest(dump(), into, depth + 1)
        return
    fields = getattr(obj, "__dict__", None)
    if isinstance(fields, dict):
        _harvest(fields, into, depth + 1)


def build_allow_set(*sources: Any) -> set[float]:
    """Every number the narrative is permitted to state.

    Drawn from the persisted verdict, the task scores and the evidence rows, so
    "supported" means *present in what the run actually saw* rather than
    plausible.
    """
    allowed: set[float] = set()
    for source in sources:
        _harvest(source, allowed)

    # Derived forms a writer will legitimately reach for.
    derived: set[float] = set()
    for value in allowed:
        derived.add(round(value, 3))
        derived.add(round(value, 2))
        derived.add(round(value, 1))
        derived.add(float(int(value)) if abs(value) < 1e12 else value)
    return allowed | derived


def _is_supported(value: float, allowed: set[float]) -> bool:
    if value in allowed:
        return True
    return any(abs(value - candidate) <= ABS_TOLERANCE for candidate in allowed)


def check(narrative: str, *sources: Any,
          structural_max: int = STRUCTURAL_MAX) -> GuardReport:
    """Check a narrative against the evidence it is allowed to draw on."""
    allowed = build_allow_set(*sources)
    report = GuardReport(allowed_values=allowed)

    seen: set[str] = set()
    for literal, value in _numbers_in(narrative):
        if literal in seen:
            continue
        seen.add(literal)
        report.checked += 1

        # Structural small integers are admitted; see the module docstring.
        if value == int(value) and abs(value) <= structural_max and "%" not in literal:
            continue
        if _is_supported(value, allowed):
            continue

        index = narrative.find(literal)
        context = narrative[max(0, index - 45):index + len(literal) + 45]
        report.fabrications.append(
            Fabrication(literal=literal, value=value,
                        context=context.replace("\n", " ").strip()))

    if report.clean:
        LOG.info("guard=figures status=clean checked=%s", report.checked)
    else:
        LOG.error("guard=figures status=fabrication_detected count=%s checked=%s",
                  len(report.fabrications), report.checked)
    return report


def citations_in(narrative: str, allowed_claim_ids: Iterable[str]) -> tuple[set[str], set[str]]:
    """Claim ids cited in the narrative, split into supported and invented.

    The synthesis node may cite only what ``search_claims`` returned, so a
    citation to anything else is the same class of error as a fabricated
    number.
    """
    allowed = set(allowed_claim_ids)
    # Claim ids are of the form ``<doc>:<topic>:<page>:<index>``.
    pattern = re.compile(r"[A-Za-z0-9_@.\-]+:[A-Za-z0-9_\-]+:\d+:\d+")
    cited = set(pattern.findall(narrative))
    return cited & allowed, cited - allowed
