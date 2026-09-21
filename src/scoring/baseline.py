"""A deterministic baseline classifier — the control, not the product.

TDD §5.3 requires the deterministic path to produce a defensible number
*before* any agent is wired in, so the agents' contribution is measurable
rather than assumed. That requires classifications, and in P2 there is no model
to produce them. This module supplies them from keyword rules.

**This is deliberately crude and is not the production classifier.** It exists
to be beaten. When the model classifier lands in W5, the comparison against
this baseline is what tells us whether the model is adding judgment or just
cost. A system that cannot beat keyword matching does not need a language
model.

Its crudeness is therefore a feature, but it must never be mistaken for the
real thing: every classification it emits carries ``Confidence.LOW`` and a
rationale that says where it came from.
"""

from __future__ import annotations

import logging
import re

from scoring.schemas import (
    Confidence,
    Direction,
    Modality,
    Routine,
    Tacitness,
    TaskClassification,
)

LOG = logging.getLogger("scoring.baseline")

BASELINE_VERSION = "baseline_keyword_v1"

# Verbs that signal rule-following symbolic work: the routine-cognitive cell.
ROUTINE_MARKERS = (
    "prepare", "compile", "calculate", "record", "maintain", "monitor",
    "compute", "update", "document", "collect", "enter", "verify", "reconcile",
    "summarize", "summarise", "create.*report", "create.*presentation",
)

# Verbs that signal judgment, negotiation or relationship work.
NON_ROUTINE_MARKERS = (
    "advise", "recommend", "evaluate", "assess", "negotiate", "confer",
    "collaborate", "determine", "develop.*strateg", "interpret", "judge",
    "persuade", "represent", "counsel", "draw conclusions",
)

# Physical presence or manual handling.
# Stems, not whole words: "examine.*facilit" silently fails to match
# "examining company facilities", which is exactly the task that most needs to
# land in the manual cell -- a language model cannot walk a factory floor.
MANUAL_MARKERS = ("inspect", "visit", "examin.*facilit", "tour.*facilit",
                  "travel", "operat.*equipment", "on.site")

# Work that resists articulation: relationships, trust, private judgement.
HIGH_TACITNESS_MARKERS = (
    "client relationship", "relationships", "confer with", "negotiat",
    "persuade", "counsel", "represent", "network", "trust", "rapport",
    "examine company facilities", "management",
)
MEDIUM_TACITNESS_MARKERS = (
    "advise", "recommend", "evaluate", "assess", "interpret", "determine",
    "collaborate",
)


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered) for p in patterns)


def classify_statement(task_id: str, statement: str) -> TaskClassification:
    """Classify one task statement by keyword. Always low confidence."""
    modality = Modality.MANUAL if _matches(statement, MANUAL_MARKERS) else Modality.COGNITIVE

    # Non-routine markers win ties: judgment work misread as routine would
    # inflate exposure, which is the error direction that matters here.
    if _matches(statement, NON_ROUTINE_MARKERS):
        routine = Routine.NON_ROUTINE
    elif _matches(statement, ROUTINE_MARKERS):
        routine = Routine.ROUTINE
    else:
        routine = Routine.NON_ROUTINE

    if _matches(statement, HIGH_TACITNESS_MARKERS):
        tacitness = Tacitness.HIGH
    elif _matches(statement, MEDIUM_TACITNESS_MARKERS):
        tacitness = Tacitness.MEDIUM
    else:
        tacitness = Tacitness.LOW

    # The baseline has no basis for a direction judgment and says so, rather
    # than guessing. Forcing a side here would fabricate the most
    # consequential field in the output.
    direction = Direction.UNCLEAR

    return TaskClassification(
        task_id=task_id,
        routine=routine, modality=modality, tacitness=tacitness,
        direction=direction, confidence=Confidence.LOW,
        rationale=(f"Keyword baseline ({BASELINE_VERSION}): matched "
                   f"{routine.value}/{modality.value}, tacitness "
                   f"{tacitness.value}. No model judgment applied; direction "
                   f"left unclear because keyword rules cannot tell "
                   f"augmentation from substitution."),
        evidence_claim_ids=[],
    )


def classify_all(tasks: list[dict]) -> list[TaskClassification]:
    """Classify a batch of view rows from ``VW_ROLE_TASKS``."""
    out = []
    for task in tasks:
        task_id = str(task.get("Task_ID") or task.get("task_id"))
        statement = str(task.get("Statement") or task.get("statement") or "")
        out.append(classify_statement(task_id, statement))
    LOG.info("classifier=%s status=ok tasks=%s confidence=low",
             BASELINE_VERSION, len(out))
    return out
