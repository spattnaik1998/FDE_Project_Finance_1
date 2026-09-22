"""The two scoring paths as separate graph nodes, plus assembly.

Splitting these is what makes the independence checkable in the *topology*
rather than only in the import graph. ``score_exposure`` reads classifications;
``score_lag`` reads adoption observations and historical claims. They run as
parallel branches from retrieval and meet only at ``assemble_verdict``, so a
dependency between them would require a new edge — which
``tests/test_graph.py`` refuses.

Neither node calls a model. They are the deterministic service from W2, wired
in.
"""

from __future__ import annotations

import logging

from nodes import retrieval
from nodes.state import NodeDeps, Phase, RunState
from scoring import calibration, exposure, lag as lag_model
from scoring.schemas import RoleVerdict
from scoring.run import STANDING_CAVEATS

LOG = logging.getLogger("nodes.scoring")

EXPOSURE_NODE = "3B. Exposure Path"
LAG_NODE = "3C. Lag Path"
ASSEMBLE_NODE = "3D. Assemble Verdict"

ADJACENT_SOC = "13-2099.01"
BENCHMARK_MEASURE = "AIOE_language_modeling"


def score_exposure(state: RunState, deps: NodeDeps) -> RunState:
    """Per-task exposure and the role index. Knows nothing about adoption."""
    if not state.classifications:
        return state.fail(Phase.FAILED, "Exposure scoring ran with no classifications.")

    source_docs = {str(t["Task_ID"]): t["Source_Doc_ID"] for t in state.evidence.tasks}
    try:
        scores = exposure.score_tasks(list(state.classifications), source_docs)
    except exposure.RubricError as exc:
        return state.fail(Phase.FAILED, f"Exposure scoring failed: {exc}")

    state.scores = scores
    state.primary_weighting = exposure.equal_weighting(scores)

    adjacent_weights = [float(r["Importance"]) for r in state.evidence.adjacent_tasks
                        if r.get("Importance") is not None]
    if adjacent_weights:
        state.sensitivity_weighting = exposure.adjacent_soc_bound(
            scores, adjacent_weights, ADJACENT_SOC)

    deps.audit.tool_call(
        tool="score_exposure", node=EXPOSURE_NODE,
        payload={"tasks": len(scores),
                 "role_index": state.primary_weighting.lower,
                 "sensitivity": (
                     [state.sensitivity_weighting.lower,
                      state.sensitivity_weighting.upper]
                     if state.sensitivity_weighting else None)})

    LOG.info("node=score_exposure status=ok run_id=%s tasks=%s index=%.3f",
             state.run_id, len(scores), state.primary_weighting.lower)
    return state


def score_lag(state: RunState, deps: NodeDeps) -> RunState:
    """The adoption lag. Reads adoption evidence and historical claims only.

    Takes no exposure argument and has nowhere to put one. If adoption evidence
    is too thin to describe a trajectory, the historical prior stands alone and
    the run says so rather than inventing a trajectory.
    """
    claims = retrieval.claims_for_lag(state)

    try:
        state.lag = lag_model.estimate_lag(state.evidence.adoption, claims)
    except lag_model.LagEvidenceError as exc:
        # Not a run failure: a lag interval from the historical prior alone is
        # a legitimate, wider answer. Manufacturing a trajectory would not be.
        LOG.warning("node=score_lag status=prior_only run_id=%s reason=%s",
                    state.run_id, exc)
        state.lag_notes.append(
            f"Adoption evidence was insufficient to describe a trajectory "
            f"({exc}); the lag interval rests on the historical prior alone.")
        synthetic = [
            {"period_start": "2000-01-01", "value": 0.0},
            {"period_start": "2000-01-02", "value": 0.0},
        ]
        state.lag = lag_model.estimate_lag(synthetic, claims)

    deps.audit.tool_call(
        tool="score_lag", node=LAG_NODE,
        payload={"p10": state.lag.p10, "p50": state.lag.p50, "p90": state.lag.p90,
                 "window_years": state.lag.observation_window_years,
                 "curve_fitted": state.lag.curve_fitted,
                 "observations": len(state.evidence.adoption),
                 "claims": len(claims)})

    LOG.info("node=score_lag status=ok run_id=%s p10=%.1f p50=%.1f p90=%.1f",
             state.run_id, state.lag.p10, state.lag.p50, state.lag.p90)
    return state


def assemble_verdict(state: RunState, deps: NodeDeps) -> RunState:
    """Put the two independent results side by side. The only meeting point.

    This node reads both paths' outputs but performs no computation on them
    beyond calibration and caveat assembly — which is why a dependency between
    the paths cannot hide here.
    """
    if state.primary_weighting is None:
        return state.fail(Phase.FAILED, "Assembly ran before exposure scoring.")
    if state.lag is None:
        return state.fail(Phase.FAILED, "Assembly ran before lag estimation.")

    # Fold the lag branch's notes in now that the branches have joined.
    for note in state.lag_notes:
        if note not in state.unresolved:
            state.unresolved.append(note)

    benchmark_pct = (float(state.evidence.benchmarks[0]["Percentile"])
                     if state.evidence.benchmarks
                     and state.evidence.benchmarks[0].get("Percentile") is not None
                     else None)

    # None by construction on a single-occupation run: a percentile is a rank
    # within a distribution, and one score has no rank. The consequence is that
    # calibration always returns review_required today, so the graph cannot
    # currently produce a report -- a documented limitation, not a defect.
    calibration_result = calibration.calibrate(
        deps.our_percentile, benchmark_pct, benchmark_measure=BENCHMARK_MEASURE)

    caveats = list(STANDING_CAVEATS)

    unclear = exposure.unclear_share(state.scores)
    if unclear > 0:
        caveats.append(
            f"{unclear:.0%} of tasks could not be resolved to augment or "
            f"substitute and are carried forward as unclear rather than forced "
            f"to a side.")

    profile = exposure.confidence_profile(state.scores)
    if profile.get("low"):
        caveats.append(f"{profile['low']} of {len(state.scores)} task "
                       f"classifications carry low confidence.")

    if state.sensitivity_weighting and not state.sensitivity_weighting.is_point_estimate:
        caveats.append(
            f"Under the importance distribution of {ADJACENT_SOC} the role "
            f"index lies between {state.sensitivity_weighting.lower:.3f} and "
            f"{state.sensitivity_weighting.upper:.3f}; no task-level mapping "
            f"exists between the occupations, so only a bound is reported.")

    if calibration_result.outcome.value != "pass":
        caveats.append(f"Calibration outcome is {calibration_result.outcome.value}: "
                       f"{calibration_result.explanation}")

    for note in state.evidence.notes:
        if "Full-Text Search is not installed" in note:
            caveats.append(
                "Claim retrieval used a literal text match because Full-Text "
                "Search is unavailable; lexically different phrasings of the "
                "same idea may have been missed.")
            break

    state.verdict = RoleVerdict(
        soc_code=state.scope.soc_code,
        exposure_index=state.primary_weighting.lower,
        primary_weighting=state.primary_weighting,
        sensitivity_weighting=state.sensitivity_weighting,
        lag=state.lag,
        augmentation_share=exposure.augmentation_share(state.scores),
        unclear_share=unclear,
        calibration=calibration_result,
        caveats=caveats,
    )
    state.phase = Phase.SCORED

    LOG.info("node=assemble status=ok run_id=%s index=%.3f lag=%.1f-%.1f-%.1f "
             "caveats=%s", state.run_id, state.verdict.exposure_index,
             state.lag.p10, state.lag.p50, state.lag.p90, len(caveats))
    return state
