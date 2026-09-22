"""Run lifecycle: assemble a verdict, persist it, bind its sources.

This is the only module that touches both paths, and it touches them as a
consumer: it calls the exposure path and the lag path separately and puts their
outputs side by side. It never passes one into the other.

Everything persisted here goes through the constraints proven in W1 — a verdict
with no caveats and an inverted lag interval are both unrepresentable — so the
guardrails are enforced by the database at the moment of writing, not by this
code remembering to check.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Sequence

import pyodbc

from scoring import calibration, exposure, lag
from scoring.schemas import (
    CalibrationOutcome,
    LagInterval,
    RoleVerdict,
    TaskClassification,
    TaskScore,
    WeightingBound,
)

LOG = logging.getLogger("scoring.run")

RUBRIC_VERSION = exposure.RUBRIC_VERSION

# Fixed caveats that must travel with every verdict. These are properties of
# the published data, not of a particular run, and the charter requires them
# stated rather than discovered by the reader.
STANDING_CAVEATS = [
    "Adoption evidence is sector-level (NAICS 52, pooling banking and insurance "
    "with securities) while the cost line is securities (NAICS 523). Census "
    "publishes no securities breakout for technology adoption. This is a "
    "property of the published data, not a modelling choice.",
    "Task weighting is an equal-weight aggregation convention, not a claim that "
    "every task is economically equally important. O*NET publishes no "
    "importance ratings for SOC 13-2051: its task list is analyst-written "
    "rather than survey-based.",
    "The lag interval is not a fitted curve. The observed LLM-era window is "
    "under two years, which cannot identify a saturation level.",
    "Exposure is technical susceptibility, not displacement. Among finance "
    "firms that adopted AI, the dominant reported effect was more skilled "
    "workers (47.2% up, 1.6% down), not fewer workers (12.5% up, 8.4% down).",
]


@dataclass
class RunContext:
    """Identity of one scoring run, for reproducibility."""

    run_id: str
    git_sha: str
    config_hash: str
    rubric_version: str
    calibration_policy_version: str
    is_customer_deliverable: bool = False


def _git_sha() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        return sha if len(sha) == 40 else "0" * 40
    except Exception:
        return "0" * 40


def _config_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def new_run(*, is_customer_deliverable: bool = False) -> RunContext:
    """Create a run identity. The config hash covers the rubric that produced it."""
    payload = {
        "exposure_matrix": {f"{r.value}|{m.value}": v
                            for (r, m), v in exposure.EXPOSURE_MATRIX.items()},
        "tacitness_penalty": {k.value: v
                              for k, v in exposure.TACITNESS_PENALTY.items()},
        "historical_prior_years": lag.HISTORICAL_PRIOR_YEARS,
        "reference_penetration_pct": lag.REFERENCE_PENETRATION_PCT,
        "calibration_tolerance": calibration.DEFAULT_TOLERANCE_POINTS,
    }
    return RunContext(
        run_id=str(uuid.uuid4()), git_sha=_git_sha(),
        config_hash=_config_hash(payload), rubric_version=RUBRIC_VERSION,
        calibration_policy_version=calibration.CALIBRATION_POLICY_VERSION,
        is_customer_deliverable=is_customer_deliverable)


def build_verdict(*, soc_code: str,
                  classifications: Sequence[TaskClassification],
                  source_doc_ids: dict[str, str],
                  adoption_observations: Sequence[dict],
                  historical_claims: Sequence[dict],
                  benchmark_percentile: float | None,
                  benchmark_measure: str = "AIOE_language_modeling",
                  adjacent_weights: Sequence[float] | None = None,
                  adjacent_soc: str = "13-2099.01",
                  our_percentile: float | None = None,
                  calibration_explanation: str | None = None
                  ) -> tuple[RoleVerdict, list[TaskScore]]:
    """Assemble a role verdict from the two independent paths.

    The two calls below are the whole design. ``exposure`` never sees the
    adoption observations; ``lag`` never sees the task scores.
    """
    scores = exposure.score_tasks(list(classifications), source_doc_ids)

    primary = exposure.equal_weighting(scores)
    sensitivity: WeightingBound | None = None
    if adjacent_weights:
        sensitivity = exposure.adjacent_soc_bound(
            scores, list(adjacent_weights), adjacent_soc)

    lag_interval: LagInterval = lag.estimate_lag(
        list(adoption_observations), list(historical_claims))

    calibration_result = calibration.calibrate(
        our_percentile, benchmark_percentile,
        benchmark_measure=benchmark_measure,
        explanation=calibration_explanation)

    caveats = list(STANDING_CAVEATS)

    unclear = exposure.unclear_share(scores)
    if unclear > 0:
        caveats.append(
            f"{unclear:.0%} of tasks could not be resolved to augment or "
            f"substitute and are carried forward as unclear rather than "
            f"forced to a side.")

    profile = exposure.confidence_profile(scores)
    if profile.get("low"):
        caveats.append(
            f"{profile['low']} of {len(scores)} task classifications carry low "
            f"confidence.")

    if sensitivity and not sensitivity.is_point_estimate:
        caveats.append(
            f"Under the importance distribution of {adjacent_soc} the role "
            f"index lies between {sensitivity.lower:.3f} and "
            f"{sensitivity.upper:.3f}; no task-level mapping exists between "
            f"the occupations, so only a bound is reported.")

    if calibration_result.outcome is not CalibrationOutcome.PASS:
        caveats.append(
            f"Calibration outcome is {calibration_result.outcome.value}: "
            f"{calibration_result.explanation}")

    verdict = RoleVerdict(
        soc_code=soc_code,
        exposure_index=primary.lower,
        primary_weighting=primary,
        sensitivity_weighting=sensitivity,
        lag=lag_interval,
        augmentation_share=exposure.augmentation_share(scores),
        unclear_share=unclear,
        calibration=calibration_result,
        caveats=caveats,
    )
    return verdict, scores


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def open_run(cursor: pyodbc.Cursor, context: RunContext) -> None:
    cursor.execute("""
        INSERT INTO score.run
            (run_id, git_sha, config_hash, rubric_version,
             calibration_policy_version, is_customer_deliverable, status)
        VALUES (?, ?, ?, ?, ?, ?, 'running')""",
        context.run_id, context.git_sha, context.config_hash,
        context.rubric_version, context.calibration_policy_version,
        1 if context.is_customer_deliverable else 0)


def persist_scores(cursor: pyodbc.Cursor, context: RunContext,
                   scores: Sequence[TaskScore], model: str,
                   prompt_version: str) -> int:
    for score in scores:
        cursor.execute("""
            INSERT INTO score.task_score
                (run_id, task_id, source_doc_id, exposure_raw, tacitness,
                 exposure_adjusted, direction, confidence, rationale,
                 evidence_claim_ids, model, prompt_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            context.run_id, score.task_id, score.source_doc_id,
            score.exposure_raw, score.tacitness_penalty, score.exposure_adjusted,
            score.direction.value, score.confidence.value, score.rationale,
            json.dumps(score.evidence_claim_ids) if score.evidence_claim_ids else None,
            model, prompt_version)
    return len(scores)


def persist_verdict(cursor: pyodbc.Cursor, context: RunContext,
                    verdict: RoleVerdict) -> None:
    """Write the verdict. The database refuses it if caveats are empty."""
    cursor.execute("""
        INSERT INTO score.role_verdict
            (run_id, soc_code, exposure_index, exposure_percentile,
             lag_years_p10, lag_years_p50, lag_years_p90, lag_basis,
             augmentation_share, weight_source, caveats)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        context.run_id, verdict.soc_code, verdict.exposure_index,
        verdict.calibration.our_percentile,
        verdict.lag.p10, verdict.lag.p50, verdict.lag.p90, verdict.lag.basis,
        verdict.augmentation_share, verdict.primary_weighting.weight_source,
        "\n\n".join(verdict.caveats))

    cal = verdict.calibration
    cursor.execute("""
        INSERT INTO score.calibration
            (run_id, benchmark_measure, benchmark_percentile, our_percentile,
             delta, within_tolerance, outcome, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        context.run_id, cal.benchmark_measure,
        # NOT coerced to 0.0. These were NOT NULL columns and the writer used
        # to substitute zero for an absent value, which persisted "our
        # percentile 0.00, delta 0.00" on every single-occupation run -- a
        # score at the 0th percentile in perfect agreement with a benchmark it
        # is simultaneously recorded as disagreeing with. An unidentifiable
        # comparison is NULL; it is not zero.
        cal.benchmark_percentile, cal.our_percentile, cal.delta,
        1 if cal.within_tolerance else 0, cal.outcome.value, cal.explanation)


def bind_sources(cursor: pyodbc.Cursor, context: RunContext,
                 consumed: dict[str, set[str]]) -> int:
    """Record which source versions this run actually consumed.

    ``consumed`` maps usage_type to the set of source_doc_ids drawn on. Binding
    happens on consumption, not availability: a source that merely sat in the
    warehouse did not contribute to the result.
    """
    written = 0
    for usage_type, doc_ids in consumed.items():
        for doc_id in sorted(doc_ids):
            cursor.execute("""
                IF NOT EXISTS (SELECT 1 FROM audit.run_source_binding
                               WHERE run_id = ? AND source_doc_id = ? AND usage_type = ?)
                INSERT INTO audit.run_source_binding
                    (run_id, source_doc_id, usage_type)
                VALUES (?, ?, ?)""",
                context.run_id, doc_id, usage_type,
                context.run_id, doc_id, usage_type)
            written += 1
    return written


def close_run(cursor: pyodbc.Cursor, context: RunContext,
              verdict: RoleVerdict, gate_outcome: str | None = None) -> str:
    """Set the terminal status, preferring the gate's decision.

    ``gate_outcome`` is authoritative when the Review Gate ran, because the
    gate -- not the calibration arithmetic -- decides whether a run is fit to
    report. It may be *stricter* than the calibration: a run whose numbers
    calibrate cleanly can still be rejected on evidence grounds.

    Without a gate outcome the status falls back to the calibration result,
    which is the W2 behaviour for a run scored without orchestration. This
    parameter was added after a test caught a gate-rejected run being persisted
    as ``passed``.
    """
    from_calibration = {
        CalibrationOutcome.PASS: "passed",
        CalibrationOutcome.REVIEW_REQUIRED: "review_required",
        CalibrationOutcome.GATE_REJECTED: "gate_rejected",
    }[verdict.calibration.outcome]

    status = gate_outcome_to_status(gate_outcome) or from_calibration

    cursor.execute("""UPDATE score.run
                      SET finished_at = SYSUTCDATETIME(), status = ?
                      WHERE run_id = ?""", status, context.run_id)
    LOG.info("run=%s status=%s source=%s exposure_index=%.3f lag=%.1f-%.1f-%.1f",
             context.run_id, status,
             "gate" if gate_outcome else "calibration",
             verdict.exposure_index, verdict.lag.p10, verdict.lag.p50,
             verdict.lag.p90)
    return status


def gate_outcome_to_status(gate_outcome: str | None) -> str | None:
    """Map a gate decision to a persisted run status, or None if absent."""
    return {
        "pass": "passed",
        "review_required": "review_required",
        "gate_rejected": "gate_rejected",
    }.get(gate_outcome or "")
