"""Review Gate: decide whether the run is fit to report.

Runs on Anthropic — a different vendor from the classifier whose work it is
grading. That is a mild independence property a single-provider setup loses.

The gate **cannot change a number.** It reads the persisted verdict and emits
one of three outcomes. Structural checks are computed in Python *before* the
model is asked, so a hard failure does not depend on a model noticing it; the
model's contribution is judgment on the soft question of whether a calibration
disagreement is a finding or a fault.

Three outcomes because disagreement and failure are different things. A binary
gate would either suppress a legitimate methodological disagreement or, loosened
enough to admit it, stop rejecting anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import config
from nodes import prompts
from nodes.state import GateDecision, NodeDeps, Phase, RunState
from providers.base import CallContext, ProviderError
from providers.registry import Stage
from scoring.schemas import CalibrationOutcome, Confidence

LOG = logging.getLogger("nodes.review_gate")

NODE = "4. Review Gate"


@dataclass
class StructuralCheck:
    """A check computed in code, not delegated to the model."""

    name: str
    passed: bool
    detail: str
    blocking: bool = True


def structural_checks(state: RunState, *, deliverable: bool = False,
                      tracker_sources: int = 0) -> list[StructuralCheck]:
    """Everything that can be decided without judgment.

    Computed before the model is consulted, so a hard failure never depends on
    a model spotting it.
    """
    verdict = state.verdict
    checks: list[StructuralCheck] = []

    checks.append(StructuralCheck(
        "verdict_present", verdict is not None,
        "A verdict was persisted." if verdict else "No verdict was produced."))
    if verdict is None:
        return checks

    checks.append(StructuralCheck(
        "caveats_non_empty", bool(verdict.caveats),
        f"{len(verdict.caveats)} caveat(s) carried."))

    checks.append(StructuralCheck(
        "lag_interval_ordered",
        verdict.lag.p10 <= verdict.lag.p50 <= verdict.lag.p90,
        f"p10 {verdict.lag.p10} <= p50 {verdict.lag.p50} <= p90 {verdict.lag.p90}."))

    checks.append(StructuralCheck(
        "no_curve_fitted", verdict.lag.curve_fitted is False,
        "No S-curve was fitted to the observed window."))

    checks.append(StructuralCheck(
        "every_task_scored",
        len(state.scores) == len(state.evidence.tasks),
        f"{len(state.scores)} score(s) for {len(state.evidence.tasks)} task(s)."))

    scored_with_rationale = sum(1 for s in state.scores if s.rationale.strip())
    checks.append(StructuralCheck(
        "every_score_has_a_rationale",
        scored_with_rationale == len(state.scores),
        f"{scored_with_rationale} of {len(state.scores)} carry a rationale."))

    checks.append(StructuralCheck(
        "sources_bound", tracker_sources > 0,
        f"{tracker_sources} source version(s) bound to this run."))

    # Non-blocking: informative, and the gate may weigh it.
    low = sum(1 for s in state.scores if s.confidence is Confidence.LOW)
    checks.append(StructuralCheck(
        "confidence_profile", low < len(state.scores) or not state.scores,
        f"{low} of {len(state.scores)} classification(s) at low confidence.",
        blocking=False))

    # Unverified mirrors block a customer-deliverable run only.
    mirrored = [c for c in state.evidence.claims
                if c.get("Is_Mirror") and not c.get("Verified_Against_Publisher")]
    checks.append(StructuralCheck(
        "mirror_policy",
        not (deliverable and mirrored),
        (f"{len(mirrored)} unverified mirror source(s) cited"
         + (" — blocks a customer-deliverable run."
            if deliverable and mirrored else
            " — permitted on an internal run, flagged."))
        if mirrored else "No unverified mirror sources cited.",
        blocking=deliverable))

    # Same shape as the mirror policy, for the same reason. An economy-profile
    # run is a rehearsal: a cheaper classifier, and no cohort reference set
    # scored by it, so its calibration is unidentifiable by construction.
    # Perfectly fine internally, and not something to hand a client. Blocking
    # only on a deliverable run, so development is not obstructed.
    economy = config.MODEL_PROFILE != "full"
    checks.append(StructuralCheck(
        "model_profile",
        not (deliverable and economy),
        (f"Running the {config.MODEL_PROFILE} model profile "
         f"({config.MODEL_CLASSIFIER} at {config.REASONING_EFFORT} effort)"
         + (" — blocks a customer-deliverable run."
            if deliverable and economy else
            " — permitted on an internal run, flagged."))
        if economy else config.model_profile_summary(),
        blocking=deliverable))

    return checks


def _decide_without_model(checks: list[StructuralCheck],
                          state: RunState) -> GateDecision | None:
    """Reject outright when a blocking structural check failed.

    The model is not consulted on these. A missing verdict or an inverted lag
    interval is not a judgment call.
    """
    failed = [c for c in checks if c.blocking and not c.passed]
    if not failed:
        return None
    return GateDecision(
        outcome="gate_rejected",
        checks_passed=[c.name for c in checks if c.passed],
        checks_failed=[c.name for c in failed],
        reasoning=("Rejected on structural grounds before review: "
                   + "; ".join(f"{c.name} — {c.detail}" for c in failed)))


def run(state: RunState, deps: NodeDeps, *, deliverable: bool = False) -> RunState:
    """Gate the run. Sets ``state.gate`` and the phase."""
    checks = structural_checks(state, deliverable=deliverable,
                               tracker_sources=deps.tracker.total_sources)

    hard = _decide_without_model(checks, state)
    if hard is not None:
        state.gate = hard
        state.phase = Phase.GATE_REJECTED
        LOG.error("node=gate status=gate_rejected run_id=%s failed=%s",
                  state.run_id, hard.checks_failed)
        deps.audit.model_call(node=NODE, provider="none", model="structural",
                              prompt_version=deps.prompt_version,
                              decision=hard.__dict__, status="gate_rejected")
        return state

    verdict = state.verdict
    cal = verdict.calibration
    sensitivity = (f"{verdict.sensitivity_weighting.lower:.3f}–"
                   f"{verdict.sensitivity_weighting.upper:.3f}"
                   if verdict.sensitivity_weighting else "not reported")

    provider = deps.provider(Stage.REVIEW_GATE)
    try:
        response = provider.structured(
            prompts.GATE_USER.format(
                run_id=state.run_id, deliverable=deliverable,
                exposure_index=f"{verdict.exposure_index:.3f}",
                weight_source=verdict.primary_weighting.weight_source,
                sensitivity=sensitivity,
                lag=f"{verdict.lag.p10} / {verdict.lag.p50} / {verdict.lag.p90}",
                window=f"{verdict.lag.observation_window_years:.2f}",
                curve_fitted=verdict.lag.curve_fitted,
                augmentation=f"{verdict.augmentation_share:.0%}",
                unclear=f"{verdict.unclear_share:.0%}",
                calibration_outcome=cal.outcome.value,
                benchmark=cal.benchmark_percentile,
                ours=cal.our_percentile,
                calibration_explanation=cal.explanation or "(none)",
                structural="\n".join(
                    f"  [{'ok' if c.passed else 'FAIL'}] {c.name}: {c.detail}"
                    for c in checks),
                caveat_count=len(verdict.caveats),
                caveats="\n".join(f"  - {c[:180]}" for c in verdict.caveats)),
            prompts.GATE_SCHEMA,
            schema_name="gate_decision",
            system=prompts.GATE_SYSTEM,
            max_tokens=2000,
            context=CallContext(run_id=state.run_id, stage=Stage.REVIEW_GATE.value,
                                prompt_version=deps.prompt_version))
    except ProviderError as exc:
        # A gate that cannot run must not wave the analysis through.
        state.gate = GateDecision(
            outcome="gate_rejected",
            checks_passed=[c.name for c in checks if c.passed],
            checks_failed=["review_gate_unavailable"],
            reasoning=f"The review gate could not be consulted ({exc}). A run "
                      f"that cannot be reviewed is not approved.")
        state.phase = Phase.GATE_REJECTED
        LOG.error("node=gate status=unavailable run_id=%s error=%s",
                  state.run_id, str(exc)[:160])
        return state

    deps.ledger.record(response, stage=Stage.REVIEW_GATE.value,
                       prompt_version=deps.prompt_version)
    deps.audit.model_call(node=NODE, provider=response.provider,
                          model=response.model,
                          prompt_version=deps.prompt_version,
                          decision=response.structured,
                          input_tokens=response.usage.input_tokens,
                          output_tokens=response.usage.output_tokens,
                          duration_ms=response.duration_ms)

    answer = response.structured or {}
    outcome = answer.get("outcome", "gate_rejected")

    # The computed calibration outcome is authoritative: the gate may not
    # upgrade a rejected calibration to a pass. It may only be at least as
    # strict as the arithmetic already was.
    if cal.outcome is CalibrationOutcome.GATE_REJECTED and outcome != "gate_rejected":
        LOG.warning("node=gate status=override_refused run_id=%s model_said=%s",
                    state.run_id, outcome)
        outcome = "gate_rejected"
        answer.setdefault("checks_failed", []).append("calibration_gate_rejected")
    elif cal.outcome is CalibrationOutcome.REVIEW_REQUIRED and outcome == "pass":
        LOG.warning("node=gate status=override_refused run_id=%s model_said=pass",
                    state.run_id)
        outcome = "review_required"
        answer.setdefault("checks_failed", []).append("calibration_review_required")

    state.gate = GateDecision(
        outcome=outcome,
        checks_passed=list(answer.get("checks_passed", [])),
        checks_failed=list(answer.get("checks_failed", [])),
        reasoning=answer.get("reasoning", ""))

    state.phase = {
        "pass": Phase.REVIEWED,
        "review_required": Phase.REVIEW_REQUIRED,
        "gate_rejected": Phase.GATE_REJECTED,
    }.get(outcome, Phase.GATE_REJECTED)

    LOG.info("node=gate status=%s run_id=%s passed=%s failed=%s",
             outcome, state.run_id, len(state.gate.checks_passed),
             len(state.gate.checks_failed))
    return state
