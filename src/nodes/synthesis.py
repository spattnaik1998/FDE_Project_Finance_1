"""Synthesis: narrate a verdict that has already been computed.

Runs on OpenAI. It adds prose, not findings, and two things are checked
mechanically after it answers:

1. **Every number** must appear in the material supplied (``figure_guard``).
2. **Every citation** must be a claim ID retrieval returned.

A draft that fails either is rejected, the specific problem is named back to the
model, and it gets exactly one retry. If the second draft also fails, the run
produces no narrative rather than a plausible one — because the failure mode
this guards against is not an obviously wrong report, it is a fluent report
containing one invented number that a customer acts on.

The gate runs before this node, so synthesis is only reached on a pass. A
rejected or review-required run produces no narrative at all.
"""

from __future__ import annotations

import logging

from nodes import figure_guard, prompts
from nodes.state import NodeDeps, Phase, RunState
from providers.base import CallContext, ProviderError
from providers.registry import Stage

LOG = logging.getLogger("nodes.synthesis")

NODE = "5. Synthesis"

MAX_TOKENS = 4000
MAX_ATTEMPTS = 2


def _verdict_block(state: RunState) -> str:
    verdict = state.verdict
    sensitivity = (
        f"{verdict.sensitivity_weighting.lower:.3f} to "
        f"{verdict.sensitivity_weighting.upper:.3f}"
        if verdict.sensitivity_weighting else "not reported")
    cal = verdict.calibration
    return "\n".join([
        f"Occupation: {state.scope.occupation_title} ({verdict.soc_code})",
        f"Exposure index: {verdict.exposure_index:.3f} "
        f"({verdict.primary_weighting.weight_source} weighting, "
        f"{len(state.scores)} tasks)",
        f"Sensitivity bound: {sensitivity}",
        f"Adoption lag: p10 {verdict.lag.p10}, p50 {verdict.lag.p50}, "
        f"p90 {verdict.lag.p90} years",
        f"Observation window: {verdict.lag.observation_window_years:.2f} years; "
        f"no curve fitted",
        f"Lag basis: {verdict.lag.basis}",
        f"Augmentation share: {verdict.augmentation_share:.3f}",
        f"Unclear share: {verdict.unclear_share:.3f}",
        f"Calibration: {cal.outcome.value}, benchmark percentile "
        f"{cal.benchmark_percentile}, ours {cal.our_percentile}",
    ])


def _task_block(state: RunState, limit: int = 12) -> str:
    ordered = sorted(state.scores, key=lambda s: -s.exposure_adjusted)[:limit]
    statements = {str(t["Task_ID"]): t["Statement"] for t in state.evidence.tasks}
    return "\n".join(
        f"  {s.exposure_adjusted:.3f} (raw {s.exposure_raw:.2f}, tacitness "
        f"{s.tacitness_penalty:.2f}, {s.direction.value}, "
        f"{s.confidence.value} confidence) — {statements.get(s.task_id, '')[:90]}"
        for s in ordered)


def _evidence_block(state: RunState, limit: int = 8) -> str:
    if not state.evidence.claims:
        return "  (no claim evidence; cite nothing)"
    return "\n".join(
        f"  [{c['Claim_ID']}] {c['Publisher']}, p.{c['Page']} — \"{c['Quote'][:200]}\""
        for c in state.evidence.claims[:limit])


def _build_prompt(state: RunState, problem: str | None = None) -> str:
    prompt = prompts.SYNTHESIS_USER.format(
        verdict_block=_verdict_block(state),
        task_block=_task_block(state),
        evidence_block=_evidence_block(state),
        caveat_block="\n".join(f"  - {c}" for c in state.verdict.caveats))
    if problem:
        prompt += prompts.SYNTHESIS_RETRY_SUFFIX.format(problem=problem)
    return prompt


def validate(narrative: str, state: RunState) -> tuple[bool, str]:
    """Check a draft for invented figures and invented citations."""
    report = figure_guard.check(
        narrative, state.verdict, state.scores, state.evidence.tasks,
        state.evidence.claims, state.evidence.adoption, state.evidence.benchmarks)

    _supported, invented = figure_guard.citations_in(
        narrative, state.evidence.claim_ids)

    problems: list[str] = []
    if not report.clean:
        problems.append(report.message())
    if invented:
        problems.append(
            f"{len(invented)} citation(s) are not in the supplied evidence: "
            f"{', '.join(sorted(invented)[:4])}")

    return (not problems), " ".join(problems)


def run(state: RunState, deps: NodeDeps) -> RunState:
    """Produce a narrative, or none at all."""
    if state.verdict is None:
        return state.fail(Phase.FAILED, "Synthesis ran with no verdict.")
    if state.gate is None or not state.gate.allows_report:
        # Not an error: a gated run is supposed to stop here.
        LOG.info("node=synthesis status=skipped run_id=%s gate=%s",
                 state.run_id, state.gate.outcome if state.gate else "absent")
        return state

    provider = deps.provider(Stage.SYNTHESIS)
    problem: str | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = provider.complete(
                _build_prompt(state, problem),
                system=prompts.SYNTHESIS_SYSTEM,
                max_tokens=MAX_TOKENS,
                context=CallContext(run_id=state.run_id,
                                    stage=Stage.SYNTHESIS.value,
                                    prompt_version=deps.prompt_version))
        except ProviderError as exc:
            return state.fail(Phase.FAILED, f"Synthesis failed: {exc}")

        deps.ledger.record(response, stage=Stage.SYNTHESIS.value,
                           prompt_version=deps.prompt_version)

        narrative = (response.text or "").strip()
        ok, problem = validate(narrative, state)

        deps.audit.model_call(
            node=NODE, provider=response.provider, model=response.model,
            prompt_version=deps.prompt_version,
            decision={"attempt": attempt, "accepted": ok,
                      "problem": problem or None, "narrative": narrative},
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            duration_ms=response.duration_ms,
            status="ok" if ok else "rejected_unsourced_figure")

        if ok:
            state.narrative = narrative
            state.phase = Phase.SYNTHESISED
            LOG.info("node=synthesis status=ok run_id=%s attempt=%s chars=%s",
                     state.run_id, attempt, len(narrative))
            return state

        LOG.error("node=synthesis status=rejected run_id=%s attempt=%s problem=%s",
                  state.run_id, attempt, problem[:200])

    # Both drafts contained unsupported figures. No narrative is produced.
    state.unresolved.append(
        f"Synthesis rejected after {MAX_ATTEMPTS} attempts: {problem}")
    return state.fail(
        Phase.FAILED,
        f"No narrative produced: every draft contained a figure or citation the "
        f"evidence does not support. A fluent report with one invented number is "
        f"worse than no report. Last problem: {problem}")
