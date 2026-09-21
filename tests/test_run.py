"""Run lifecycle: assemble a verdict, persist it, bind its sources.

These tests exercise the join between the scoring service and the warehouse
constraints proven in W1. The point is that the guardrails fire at the moment of
writing — this code does not have to remember to check.
"""

from __future__ import annotations

import pytest

from scoring import run as runner
from scoring.schemas import (
    CalibrationOutcome,
    Confidence,
    Direction,
    Modality,
    Routine,
    Tacitness,
    TaskClassification,
)

REASON = "Equal-weight convention differs from the benchmark's estimand."


def classify(task_id: str, *, routine=Routine.ROUTINE,
             modality=Modality.COGNITIVE, tacitness=Tacitness.LOW,
             direction=Direction.AUGMENT, confidence=Confidence.HIGH):
    return TaskClassification(
        task_id=task_id, routine=routine, modality=modality, tacitness=tacitness,
        direction=direction, confidence=confidence, rationale="fixture")


@pytest.fixture
def classifications():
    return [
        classify("t1"),
        classify("t2", routine=Routine.NON_ROUTINE, tacitness=Tacitness.HIGH,
                 direction=Direction.UNCLEAR, confidence=Confidence.LOW),
        classify("t3", modality=Modality.MANUAL, direction=Direction.SUBSTITUTE),
    ]


@pytest.fixture
def docs(classifications):
    return {c.task_id: "d1" for c in classifications}


def build(classifications, docs, adoption_series, lag_claims, **over):
    kwargs = dict(soc_code="13-2051.00", classifications=classifications,
                  source_doc_ids=docs, adoption_observations=adoption_series,
                  historical_claims=lag_claims, benchmark_percentile=87.0)
    kwargs.update(over)
    return runner.build_verdict(**kwargs)


# --- Run identity -----------------------------------------------------------

def test_run_identity_is_reproducible():
    """The config hash covers the rubric, so a rubric change changes the hash."""
    a, b = runner.new_run(), runner.new_run()
    assert a.config_hash == b.config_hash
    assert a.run_id != b.run_id
    assert len(a.git_sha) == 40


def test_config_hash_changes_when_the_rubric_changes(monkeypatch):
    from scoring import exposure
    baseline = runner.new_run().config_hash
    monkeypatch.setitem(exposure.TACITNESS_PENALTY, Tacitness.HIGH, 0.99)
    assert runner.new_run().config_hash != baseline


def test_run_is_not_customer_deliverable_by_default():
    assert runner.new_run().is_customer_deliverable is False


# --- Verdict assembly -------------------------------------------------------

def test_verdict_carries_exposure_and_lag_as_separate_fields(
        classifications, docs, adoption_series, lag_claims):
    verdict, scores = build(classifications, docs, adoption_series, lag_claims)
    assert 0.0 <= verdict.exposure_index <= 1.0
    assert verdict.lag.p10 <= verdict.lag.p50 <= verdict.lag.p90
    assert len(scores) == 3


def test_exposure_index_is_the_equal_weighted_mean(
        classifications, docs, adoption_series, lag_claims):
    verdict, scores = build(classifications, docs, adoption_series, lag_claims)
    expected = sum(s.exposure_adjusted for s in scores) / len(scores)
    assert verdict.exposure_index == pytest.approx(expected, abs=1e-6)


def test_verdict_always_carries_standing_caveats(
        classifications, docs, adoption_series, lag_claims):
    verdict, _ = build(classifications, docs, adoption_series, lag_claims)
    joined = " ".join(verdict.caveats).lower()
    assert "naics 52" in joined and "523" in joined
    assert "aggregation convention" in joined
    assert "not a fitted curve" in joined


def test_unclear_tasks_generate_their_own_caveat(
        classifications, docs, adoption_series, lag_claims):
    verdict, _ = build(classifications, docs, adoption_series, lag_claims)
    assert verdict.unclear_share > 0
    assert any("unclear" in c.lower() for c in verdict.caveats)


def test_low_confidence_classifications_generate_a_caveat(
        classifications, docs, adoption_series, lag_claims):
    verdict, _ = build(classifications, docs, adoption_series, lag_claims)
    assert any("low confidence" in c.lower() for c in verdict.caveats)


def test_sensitivity_bound_is_reported_when_adjacent_weights_are_supplied(
        classifications, docs, adoption_series, lag_claims):
    verdict, _ = build(classifications, docs, adoption_series, lag_claims,
                       adjacent_weights=[1.0, 3.0, 5.0])
    assert verdict.sensitivity_weighting is not None
    assert not verdict.sensitivity_weighting.is_point_estimate
    assert any("importance distribution" in c.lower() for c in verdict.caveats)


def test_sensitivity_is_absent_when_no_weights_are_supplied(
        classifications, docs, adoption_series, lag_claims):
    verdict, _ = build(classifications, docs, adoption_series, lag_claims)
    assert verdict.sensitivity_weighting is None


def test_unidentifiable_calibration_becomes_a_caveat(
        classifications, docs, adoption_series, lag_claims):
    verdict, _ = build(classifications, docs, adoption_series, lag_claims)
    assert verdict.calibration.outcome is CalibrationOutcome.REVIEW_REQUIRED
    assert any("calibration outcome" in c.lower() for c in verdict.caveats)


def test_verdict_with_no_caveats_is_unconstructable():
    from scoring.schemas import (CalibrationResult, LagInterval, RoleVerdict,
                                 WeightingBound)
    with pytest.raises(Exception):
        RoleVerdict(
            soc_code="13-2051.00", exposure_index=0.5,
            primary_weighting=WeightingBound(weight_source="equal", lower=0.5,
                                             upper=0.5, note="n"),
            sensitivity_weighting=None,
            lag=LagInterval(p10=1, p50=2, p90=3, basis="b",
                            observation_window_years=1.0),
            augmentation_share=0.5, unclear_share=0.0,
            calibration=CalibrationResult(
                benchmark_measure="m", benchmark_percentile=87.0,
                our_percentile=87.0, delta=0.0, within_tolerance=True,
                outcome=CalibrationOutcome.PASS),
            caveats=[])


# --- Persistence ------------------------------------------------------------

def test_a_complete_run_persists_and_satisfies_every_constraint(
        cur, doc, soc, classifications, docs, adoption_series, lag_claims):
    for task_id in docs:
        cur.execute("""INSERT INTO core.task
                           (task_id, soc_code, statement, weight_source, source_doc_id)
                       VALUES (?, ?, 'Analyse financial statements.', 'equal', ?)""",
                    task_id, soc, doc)

    context = runner.new_run()
    verdict, scores = build(classifications, {k: doc for k in docs},
                            adoption_series, lag_claims)

    runner.open_run(cur, context)
    written = runner.persist_scores(cur, context, scores, "gpt-6-astra", "v1")
    runner.persist_verdict(cur, context, verdict)
    bound = runner.bind_sources(cur, context, {
        "task_source": {doc}, "adoption_evidence": {doc}, "claim_evidence": {doc}})
    status = runner.close_run(cur, context, verdict)

    assert written == 3
    assert bound == 3
    assert status == "review_required"

    assert cur.execute("SELECT COUNT(*) FROM score.task_score WHERE run_id = ?",
                       context.run_id).fetchone()[0] == 3
    assert cur.execute("SELECT COUNT(*) FROM score.role_verdict WHERE run_id = ?",
                       context.run_id).fetchone()[0] == 1
    assert cur.execute("SELECT COUNT(*) FROM audit.run_source_binding WHERE run_id = ?",
                       context.run_id).fetchone()[0] == 3


def test_persisted_verdict_keeps_the_lag_interval_ordered(
        cur, doc, soc, classifications, docs, adoption_series, lag_claims):
    context = runner.new_run()
    verdict, _ = build(classifications, {k: doc for k in docs},
                       adoption_series, lag_claims)
    runner.open_run(cur, context)
    runner.persist_verdict(cur, context, verdict)

    row = cur.execute("""SELECT lag_years_p10, lag_years_p50, lag_years_p90
                         FROM score.role_verdict WHERE run_id = ?""",
                      context.run_id).fetchone()
    assert float(row[0]) <= float(row[1]) <= float(row[2])


def test_failed_calibration_does_not_produce_a_passed_run(
        cur, doc, soc, classifications, docs, adoption_series, lag_claims):
    """A downstream reader must not mistake a rejected run for a clean one."""
    context = runner.new_run()
    verdict, _ = build(classifications, {k: doc for k in docs},
                       adoption_series, lag_claims,
                       our_percentile=20.0, benchmark_percentile=87.0)
    assert verdict.calibration.outcome is CalibrationOutcome.GATE_REJECTED

    runner.open_run(cur, context)
    runner.persist_verdict(cur, context, verdict)
    status = runner.close_run(cur, context, verdict)

    assert status == "gate_rejected"
    assert cur.execute("SELECT status FROM score.run WHERE run_id = ?",
                       context.run_id).fetchone()[0] == "gate_rejected"


def test_clean_calibration_produces_a_passed_run(
        cur, doc, soc, classifications, docs, adoption_series, lag_claims):
    context = runner.new_run()
    verdict, _ = build(classifications, {k: doc for k in docs},
                       adoption_series, lag_claims,
                       our_percentile=85.0, benchmark_percentile=87.0)
    runner.open_run(cur, context)
    runner.persist_verdict(cur, context, verdict)
    assert runner.close_run(cur, context, verdict) == "passed"


def test_source_binding_is_idempotent(cur, doc, soc):
    context = runner.new_run()
    runner.open_run(cur, context)
    runner.bind_sources(cur, context, {"task_source": {doc}})
    runner.bind_sources(cur, context, {"task_source": {doc}})
    assert cur.execute("SELECT COUNT(*) FROM audit.run_source_binding WHERE run_id = ?",
                       context.run_id).fetchone()[0] == 1


def test_evidence_claim_ids_persist_as_json(cur, doc, soc):
    cur.execute("""INSERT INTO core.task
                       (task_id, soc_code, statement, weight_source, source_doc_id)
                   VALUES ('t1', ?, 'Analyse statements.', 'equal', ?)""", soc, doc)
    context = runner.new_run()
    runner.open_run(cur, context)

    from scoring import exposure
    classification = TaskClassification(
        task_id="t1", routine=Routine.ROUTINE, modality=Modality.COGNITIVE,
        tacitness=Tacitness.LOW, direction=Direction.AUGMENT,
        confidence=Confidence.HIGH, rationale="r",
        evidence_claim_ids=["doc:topic:1:0", "doc:topic:2:0"])
    scores = exposure.score_tasks([classification], {"t1": doc})
    runner.persist_scores(cur, context, scores, "gpt-6-astra", "v1")

    stored = cur.execute("""SELECT evidence_claim_ids FROM score.task_score
                            WHERE run_id = ?""", context.run_id).fetchone()[0]
    import json
    assert json.loads(stored) == ["doc:topic:1:0", "doc:topic:2:0"]
