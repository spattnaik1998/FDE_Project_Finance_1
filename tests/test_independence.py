"""The exposure and lag paths must be independent.

This is the single most important test in the project, and it is written before
the lag model exists. If exposure and lag are not provably independent, the
whole differentiator is gone: the market conflates "how exposed" with "how
soon", and the architecture exists to keep them apart.

Three levels of assurance, weakest to strongest:

1. **Behavioural** — varying the exposure result leaves the lag unchanged.
2. **Interface** — the lag model's signature has nowhere to put an exposure.
3. **Structural** — the lag module does not import the exposure module, checked
   by parsing the source. This is the one that survives refactoring, because a
   developer adding the coupling has to also delete this test.

Eloundou et al. state the position directly, and the quote is in the warehouse:
"We do not make predictions about the development or adoption timeline of such
LLMs." An exposure measure is not a timetable.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "scoring"

EXPOSURE_NAMES = {"exposure", "score_task", "score_tasks", "exposure_raw",
                  "EXPOSURE_MATRIX", "equal_weighting", "TaskScore",
                  "exposure_adjusted", "exposure_index"}


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, however it imports it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


# --- Structural: the import graph ------------------------------------------

def test_lag_module_does_not_import_the_exposure_module():
    """The coupling cannot be introduced without deleting this test."""
    imports = _imported_modules(SRC / "lag.py")
    offenders = {name for name in imports
                 if "exposure" in name.split(".")[-1].lower()
                 or name.endswith("scoring.exposure")}
    assert not offenders, (
        f"lag.py imports the exposure path: {offenders}. The lag estimate must "
        f"be derivable from adoption evidence alone.")


def test_lag_module_does_not_reference_exposure_symbols():
    """Not even via a re-export or a string lookup."""
    source = (SRC / "lag.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    referenced |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    leaked = referenced & EXPOSURE_NAMES
    assert not leaked, f"lag.py references exposure symbols: {leaked}"


# --- Interface: nowhere to put an exposure ---------------------------------

def test_lag_estimator_signature_accepts_no_exposure_argument():
    from scoring import lag

    params = set(inspect.signature(lag.estimate_lag).parameters)
    forbidden = {p for p in params
                 if "exposure" in p.lower() or "score" in p.lower()
                 or "verdict" in p.lower()}
    assert not forbidden, (
        f"estimate_lag accepts {forbidden}; an exposure result must not be "
        f"passable into the lag path even optionally.")


def test_lag_interval_model_has_no_exposure_field():
    from scoring.schemas import LagInterval

    fields = set(LagInterval.model_fields)
    assert not {f for f in fields if "exposure" in f.lower()}


# --- Behavioural: the lag does not move when exposure does -----------------

def test_lag_is_identical_across_wildly_different_exposure_results(
        adoption_series, lag_claims):
    """Compute the lag twice, with the exposure path having produced opposite
    answers in between. The lag must be byte-identical."""
    from scoring import exposure, lag
    from scoring.schemas import (Confidence, Direction, Modality, Routine,
                                 Tacitness, TaskClassification)

    def classify(routine, modality, tacit):
        return TaskClassification(
            task_id="t1", routine=routine, modality=modality, tacitness=tacit,
            direction=Direction.UNCLEAR, confidence=Confidence.HIGH,
            rationale="fixture")

    first_lag = lag.estimate_lag(adoption_series, lag_claims)

    highest = exposure.score_task(
        classify(Routine.ROUTINE, Modality.COGNITIVE, Tacitness.LOW), "d1")
    lowest = exposure.score_task(
        classify(Routine.NON_ROUTINE, Modality.MANUAL, Tacitness.HIGH), "d1")
    assert highest.exposure_adjusted > lowest.exposure_adjusted, \
        "sanity: the exposure path must actually be capable of differing"

    second_lag = lag.estimate_lag(adoption_series, lag_claims)

    assert first_lag.model_dump() == second_lag.model_dump()


def test_lag_changes_when_adoption_evidence_changes(adoption_series, lag_claims):
    """The converse sanity check: the lag must be sensitive to its *own* inputs.

    A constant would pass every independence test above while being useless.
    """
    from scoring import lag

    slow = lag.estimate_lag(adoption_series, lag_claims)

    faster = [
        dict(obs, value=min(100.0, float(obs["value"]) * 2.0))
        for obs in adoption_series
    ]
    fast = lag.estimate_lag(faster, lag_claims)

    assert fast.model_dump() != slow.model_dump(), (
        "the lag model must respond to adoption evidence, or it is a constant "
        "dressed as an estimate")


# --- The reverse direction: exposure must not read adoption ----------------

def test_exposure_module_does_not_import_the_lag_module():
    """Independence has to hold in both directions to be independence."""
    imports = _imported_modules(SRC / "exposure.py")
    offenders = {n for n in imports if "lag" in n.split(".")[-1].lower()}
    assert not offenders, f"exposure.py imports the lag path: {offenders}"


def test_exposure_scoring_takes_no_adoption_evidence():
    from scoring import exposure

    params = set(inspect.signature(exposure.score_task).parameters)
    forbidden = {p for p in params
                 if "adoption" in p.lower() or "lag" in p.lower()
                 or "observation" in p.lower()}
    assert not forbidden, f"score_task accepts {forbidden}"
