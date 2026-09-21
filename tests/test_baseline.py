"""The keyword baseline: the control the model has to beat.

Two things must hold. It has to be *good enough to be a fair bar* — it should
put presentation-drafting above relationship-building, or beating it means
nothing. And it has to be *honest about being crude* — every classification low
confidence, every direction unclear, because keyword rules cannot tell
augmentation from substitution and guessing would fabricate the most
consequential field in the output.
"""

from __future__ import annotations

import pytest

from scoring import baseline, exposure
from scoring.schemas import Confidence, Direction, Modality, Routine, Tacitness

# Real statements from O*NET SOC 13-2051.
ROUTINE_COGNITIVE = "Draw charts and graphs, using computer spreadsheets, to illustrate technical reports."
RELATIONSHIP = "Develop and maintain client relationships."
ADVISORY = "Advise clients on aspects of capitalization, such as amounts, sources, or timing."
PHYSICAL = "Assess companies as investments for clients by examining company facilities."


def classify(statement: str, task_id: str = "t1"):
    return baseline.classify_statement(task_id, statement)


# --- Honesty about its own limits -------------------------------------------

def test_every_classification_is_low_confidence():
    for statement in (ROUTINE_COGNITIVE, RELATIONSHIP, ADVISORY, PHYSICAL):
        assert classify(statement).confidence is Confidence.LOW


def test_direction_is_always_unclear():
    """Keyword rules cannot tell augmentation from substitution, so they say so."""
    for statement in (ROUTINE_COGNITIVE, RELATIONSHIP, ADVISORY, PHYSICAL):
        assert classify(statement).direction is Direction.UNCLEAR


def test_rationale_names_the_baseline_and_says_why_direction_is_unclear():
    rationale = classify(ROUTINE_COGNITIVE).rationale
    assert baseline.BASELINE_VERSION in rationale
    assert "no model judgment" in rationale.lower()
    assert "cannot tell" in rationale.lower()


def test_baseline_cites_no_evidence():
    """It has read nothing, so it must claim nothing."""
    assert classify(ADVISORY).evidence_claim_ids == []


# --- It is a fair bar -------------------------------------------------------

def test_chart_drawing_is_classified_routine_cognitive():
    result = classify(ROUTINE_COGNITIVE)
    assert result.routine is Routine.ROUTINE
    assert result.modality is Modality.COGNITIVE
    assert result.tacitness is Tacitness.LOW


def test_relationship_work_gets_the_high_tacitness_discount():
    """Polanyi's bound applied to the clearest case in the task list."""
    assert classify(RELATIONSHIP).tacitness is Tacitness.HIGH


def test_advisory_work_is_non_routine():
    assert classify(ADVISORY).routine is Routine.NON_ROUTINE


def test_facility_inspection_is_classified_manual():
    assert classify(PHYSICAL).modality is Modality.MANUAL


def test_baseline_ranks_drafting_above_relationship_building():
    """If it got this backwards it would not be a meaningful control."""
    drafting = exposure.score_task(classify(ROUTINE_COGNITIVE, "a"), "d")
    relationship = exposure.score_task(classify(RELATIONSHIP, "b"), "d")
    assert drafting.exposure_adjusted > relationship.exposure_adjusted


def test_unrecognised_statements_default_to_non_routine():
    """Misreading judgment work as routine would inflate exposure, which is the
    error direction that matters, so the default leans the other way."""
    assert classify("Xyzzy the frobnicator.").routine is Routine.NON_ROUTINE


def test_non_routine_markers_win_over_routine_markers():
    """'Prepare' and 'recommend' in one statement: judgment should dominate."""
    mixed = "Prepare plans of action and recommend investment strategies to clients."
    assert classify(mixed).routine is Routine.NON_ROUTINE


# --- Determinism ------------------------------------------------------------

def test_baseline_is_deterministic():
    a = classify(ADVISORY)
    b = classify(ADVISORY)
    assert a.model_dump() == b.model_dump()


def test_classify_all_handles_warehouse_column_names():
    rows = [{"Task_ID": "21579", "Statement": ROUTINE_COGNITIVE},
            {"Task_ID": "21580", "Statement": RELATIONSHIP}]
    results = baseline.classify_all(rows)
    assert [r.task_id for r in results] == ["21579", "21580"]


def test_classify_all_handles_lowercase_column_names():
    rows = [{"task_id": "1", "statement": ADVISORY}]
    assert baseline.classify_all(rows)[0].task_id == "1"


def test_empty_statement_does_not_crash():
    result = classify("")
    assert result.routine is Routine.NON_ROUTINE
    assert result.confidence is Confidence.LOW
