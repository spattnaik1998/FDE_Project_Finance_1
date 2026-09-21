"""The exposure rubric: deterministic, so exact assertions are appropriate.

The rubric is a lookup table on purpose — small enough to read and argue with.
These tests pin the numbers so a change to them is a deliberate act with a
visible diff, not a drift.
"""

from __future__ import annotations

import pytest

from scoring import exposure
from scoring.schemas import (
    Confidence,
    Direction,
    Modality,
    Routine,
    Tacitness,
    TaskClassification,
)


def classify(*, routine=Routine.ROUTINE, modality=Modality.COGNITIVE,
             tacitness=Tacitness.LOW, direction=Direction.UNCLEAR,
             confidence=Confidence.HIGH, task_id="t1",
             claims=None) -> TaskClassification:
    return TaskClassification(
        task_id=task_id, routine=routine, modality=modality, tacitness=tacitness,
        direction=direction, confidence=confidence,
        rationale="fixture rationale", evidence_claim_ids=claims or [])


# --- Determinism ------------------------------------------------------------

def test_scoring_is_deterministic():
    a = exposure.score_task(classify(), "d1")
    b = exposure.score_task(classify(), "d1")
    assert a.model_dump() == b.model_dump()


# --- The matrix -------------------------------------------------------------

@pytest.mark.parametrize("routine,modality,expected", [
    (Routine.ROUTINE, Modality.COGNITIVE, 0.90),
    (Routine.NON_ROUTINE, Modality.COGNITIVE, 0.55),
    (Routine.ROUTINE, Modality.MANUAL, 0.20),
    (Routine.NON_ROUTINE, Modality.MANUAL, 0.05),
])
def test_matrix_cells_are_pinned(routine, modality, expected):
    assert exposure.exposure_raw(classify(routine=routine, modality=modality)) == expected


def test_routine_cognitive_is_the_most_exposed_cell():
    """Rule-following symbolic work is what current models actually do."""
    values = {k: v for k, v in exposure.EXPOSURE_MATRIX.items()}
    top = max(values, key=values.get)
    assert top == (Routine.ROUTINE, Modality.COGNITIVE)


def test_manual_work_scores_below_all_cognitive_work():
    """A language model does not move boxes. This is LLM exposure, not
    automation exposure in general."""
    cognitive = [v for (r, m), v in exposure.EXPOSURE_MATRIX.items()
                 if m is Modality.COGNITIVE]
    manual = [v for (r, m), v in exposure.EXPOSURE_MATRIX.items()
              if m is Modality.MANUAL]
    assert max(manual) < min(cognitive)


def test_every_matrix_cell_is_defined():
    for routine in Routine:
        for modality in Modality:
            assert (routine, modality) in exposure.EXPOSURE_MATRIX


def test_all_matrix_values_are_in_unit_range():
    assert all(0.0 <= v <= 1.0 for v in exposure.EXPOSURE_MATRIX.values())


# --- Tacitness --------------------------------------------------------------

@pytest.mark.parametrize("tacitness,penalty", [
    (Tacitness.LOW, 0.00), (Tacitness.MEDIUM, 0.25), (Tacitness.HIGH, 0.55)])
def test_tacitness_penalties_are_pinned(tacitness, penalty):
    assert exposure.tacitness_penalty(classify(tacitness=tacitness)) == penalty


def test_tacitness_discount_is_monotone():
    """More tacit must never mean more exposed."""
    scores = [exposure.score_task(classify(tacitness=t), "d1").exposure_adjusted
              for t in (Tacitness.LOW, Tacitness.MEDIUM, Tacitness.HIGH)]
    assert scores == sorted(scores, reverse=True)


def test_high_tacitness_materially_discounts_a_routine_task():
    """Polanyi's bound: a task whose rules cannot be stated resists
    substitution however routine it looks from outside."""
    plain = exposure.score_task(classify(tacitness=Tacitness.LOW), "d1")
    tacit = exposure.score_task(classify(tacitness=Tacitness.HIGH), "d1")
    assert plain.exposure_adjusted == pytest.approx(0.90)
    assert tacit.exposure_adjusted == pytest.approx(0.405)
    assert tacit.exposure_adjusted < plain.exposure_adjusted * 0.5


def test_penalty_is_reported_not_folded_away():
    """The discount must be visible in the output, not hidden in one number."""
    score = exposure.score_task(classify(tacitness=Tacitness.MEDIUM), "d1")
    assert score.tacitness_penalty == 0.25
    assert score.exposure_raw == 0.90
    assert score.exposure_adjusted == pytest.approx(0.675)


def test_schema_rejects_an_inconsistent_adjusted_value():
    """The contract enforces the arithmetic, so a hand-built score cannot lie."""
    from scoring.schemas import TaskScore
    with pytest.raises(Exception, match="must equal"):
        TaskScore(task_id="t1", source_doc_id="d1", exposure_raw=0.9,
                  tacitness_penalty=0.55, exposure_adjusted=0.9,
                  direction=Direction.AUGMENT, confidence=Confidence.HIGH,
                  rationale="r")


# --- Classification contract ------------------------------------------------

def test_classification_carries_no_numeric_field():
    """If a score could be supplied here, a model could set it."""
    numeric = {name for name, f in TaskClassification.model_fields.items()
               if f.annotation in (float, int)}
    assert not numeric, f"TaskClassification exposes numeric fields: {numeric}"


def test_classification_is_immutable():
    c = classify()
    with pytest.raises(Exception):
        c.tacitness = Tacitness.LOW


def test_classification_requires_a_rationale():
    with pytest.raises(Exception):
        TaskClassification(task_id="t1", routine=Routine.ROUTINE,
                           modality=Modality.COGNITIVE, tacitness=Tacitness.LOW,
                           direction=Direction.AUGMENT, confidence=Confidence.HIGH,
                           rationale="")


# --- Provenance -------------------------------------------------------------

def test_task_without_a_source_document_cannot_be_scored(caplog):
    with pytest.raises(exposure.RubricError, match="unprovenanced"):
        exposure.score_tasks([classify(task_id="t9")], {})


def test_source_document_is_carried_onto_the_score():
    scores = exposure.score_tasks([classify(task_id="t1")], {"t1": "onet_v1"})
    assert scores[0].source_doc_id == "onet_v1"


# --- Role aggregation -------------------------------------------------------

def test_equal_weighting_is_the_mean_and_is_a_point_estimate():
    scores = [
        exposure.score_task(classify(task_id="a", routine=Routine.ROUTINE), "d"),
        exposure.score_task(classify(task_id="b", routine=Routine.NON_ROUTINE), "d"),
    ]
    bound = exposure.equal_weighting(scores)
    assert bound.lower == pytest.approx((0.90 + 0.55) / 2)
    assert bound.is_point_estimate
    assert bound.weight_source == "equal"


def test_equal_weighting_note_states_it_is_a_convention():
    """It must not read as a claim that every task matters equally."""
    bound = exposure.equal_weighting(
        [exposure.score_task(classify(), "d")])
    assert "convention" in bound.note.lower()
    assert "no importance ratings" in bound.note.lower()


def test_role_index_from_zero_tasks_is_refused():
    with pytest.raises(exposure.RubricError):
        exposure.equal_weighting([])


def test_adjacent_soc_bound_brackets_every_possible_assignment():
    """No task mapping exists between occupations, so only a bound is honest."""
    scores = [
        exposure.score_task(classify(task_id="a", routine=Routine.ROUTINE), "d"),
        exposure.score_task(classify(task_id="b", routine=Routine.NON_ROUTINE,
                                     modality=Modality.MANUAL), "d"),
    ]
    bound = exposure.adjacent_soc_bound(scores, [1.0, 5.0], "13-2099.01")

    assert not bound.is_point_estimate, "a point estimate here would be invented"
    assert bound.lower < bound.upper
    equal = exposure.equal_weighting(scores).lower
    assert bound.lower <= equal <= bound.upper, \
        "the bound must contain the equal-weight result"


def test_adjacent_soc_bound_collapses_when_weights_are_uniform():
    """Uniform weights are equal weights, so the bound should collapse."""
    scores = [exposure.score_task(classify(task_id=t), "d") for t in ("a", "b", "c")]
    bound = exposure.adjacent_soc_bound(scores, [2.0, 2.0, 2.0], "13-2099.01")
    assert bound.upper - bound.lower < 1e-9


def test_adjacent_soc_bound_states_the_absent_mapping():
    scores = [exposure.score_task(classify(), "d")]
    bound = exposure.adjacent_soc_bound(scores, [1.0, 2.0], "13-2099.01")
    assert "no task-level mapping" in bound.note.lower()


def test_adjacent_soc_bound_refuses_zero_weights():
    scores = [exposure.score_task(classify(), "d")]
    with pytest.raises(exposure.RubricError):
        exposure.adjacent_soc_bound(scores, [0.0, 0.0], "13-2099.01")


def test_weighting_bound_rejects_inverted_bounds():
    from scoring.schemas import WeightingBound
    with pytest.raises(Exception):
        WeightingBound(weight_source="equal", lower=0.9, upper=0.1, note="n")


# --- Direction shares -------------------------------------------------------

def test_augmentation_share_counts_only_augment():
    scores = [
        exposure.score_task(classify(task_id="a", direction=Direction.AUGMENT), "d"),
        exposure.score_task(classify(task_id="b", direction=Direction.SUBSTITUTE), "d"),
        exposure.score_task(classify(task_id="c", direction=Direction.UNCLEAR), "d"),
    ]
    assert exposure.augmentation_share(scores) == pytest.approx(1 / 3)
    assert exposure.unclear_share(scores) == pytest.approx(1 / 3)


def test_unclear_is_carried_forward_not_forced_to_a_side():
    scores = [exposure.score_task(classify(direction=Direction.UNCLEAR), "d")]
    assert exposure.unclear_share(scores) == 1.0
    assert exposure.augmentation_share(scores) == 0.0


def test_confidence_profile_counts_every_level():
    scores = [
        exposure.score_task(classify(task_id="a", confidence=Confidence.HIGH), "d"),
        exposure.score_task(classify(task_id="b", confidence=Confidence.LOW), "d"),
    ]
    profile = exposure.confidence_profile(scores)
    assert profile == {"high": 1, "medium": 0, "low": 1}
