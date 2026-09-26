"""Run the full orchestration with real models, and compare to the baseline.

This is W5's proof. The plan's standard was explicit: the model classifier has
to beat the keyword baseline *meaningfully*, or it is adding cost rather than
judgment. So this script runs both over the same tasks and prints the
difference — including token spend, so the trade is visible.

The nodes are chained directly here rather than through LangGraph. Assembly is
W6; this establishes that the nodes work and what they are worth.
"""

from __future__ import annotations

import argparse
import logging
import sys

sys.path.insert(0, "src")

from nodes import classifier, intent, retrieval, review_gate, synthesis
from nodes.state import NodeDeps, Phase, RunState
from providers.accounting import Ledger
from scoring import baseline, exposure, run as runner
from scoring.schemas import Confidence, Direction
from tools.audit_adapter import AuditAdapter
from tools.consumption import ConsumptionTracker
from tools.evidence import EvidenceTools

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("run_orchestrated")

DEFAULT_REQUEST = ("Which of our equity research associate cost lines are exposed "
                   "to agent substitution, and on what timetable?")
BENCHMARK_MEASURE = "AIOE_language_modeling"


def _score_with(classifications, tasks, state, adjacent_weights, benchmark_pct):
    """Build a verdict from a set of classifications."""
    source_docs = {str(t["Task_ID"]): t["Source_Doc_ID"] for t in tasks}
    return runner.build_verdict(
        soc_code=state.scope.soc_code,
        classifications=classifications,
        source_doc_ids=source_docs,
        adoption_observations=state.evidence.adoption,
        historical_claims=retrieval.claims_for_lag(state),
        benchmark_percentile=benchmark_pct,
        benchmark_measure=BENCHMARK_MEASURE,
        adjacent_weights=adjacent_weights or None,
        our_percentile=None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", default=DEFAULT_REQUEST)
    parser.add_argument("--deliverable", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="Classify only the first N tasks (cost control)")
    args = parser.parse_args()

    context = runner.new_run(is_customer_deliverable=args.deliverable)
    tracker = ConsumptionTracker(run_id=context.run_id)
    audit = AuditAdapter(run_id=context.run_id)
    ledger = Ledger(run_id=context.run_id)
    tools = EvidenceTools(tracker=tracker, audit=audit)
    deps = NodeDeps(tools=tools, tracker=tracker, audit=audit, ledger=ledger)

    state = RunState(run_id=context.run_id, request=args.request)

    # --- 1. Intent & Scope ------------------------------------------------
    state = intent.run(state, deps)
    if state.phase is Phase.OUT_OF_SCOPE:
        print(f"\nOUT OF SCOPE: {state.errors[-1]}")
        sys.exit(0)
    if state.phase is Phase.FAILED:
        print(f"\nFAILED: {state.errors[-1]}")
        sys.exit(1)

    # --- 2. Evidence Retrieval -------------------------------------------
    state = retrieval.run(state, deps)
    if state.phase is Phase.FAILED:
        print(f"\nFAILED: {state.errors[-1]}")
        sys.exit(1)

    if args.limit:
        state.evidence.tasks = state.evidence.tasks[:args.limit]

    tasks = state.evidence.tasks
    adjacent_weights = [float(r["Importance"]) for r in state.evidence.adjacent_tasks
                        if r.get("Importance") is not None]
    benchmark_pct = (float(state.evidence.benchmarks[0]["Percentile"])
                     if state.evidence.benchmarks else None)

    # --- The control: keyword baseline over the same tasks ----------------
    base_classifications = baseline.classify_all(tasks)
    base_verdict, base_scores = _score_with(
        base_classifications, tasks, state, adjacent_weights, benchmark_pct)

    # --- 3A. Task Classifier (real models) --------------------------------
    state = classifier.run(state, deps)
    if state.phase is Phase.FAILED:
        print(f"\nFAILED: {state.errors[-1]}")
        sys.exit(1)

    # --- 3B/3C. Deterministic scoring, both paths -------------------------
    verdict, scores = _score_with(
        state.classifications, tasks, state, adjacent_weights, benchmark_pct)
    state.verdict, state.scores = verdict, scores
    state.phase = Phase.SCORED

    # --- Persist ----------------------------------------------------------
    from warehouse.session import Principal, connect
    with connect(Principal.SCORE) as conn:
        cursor = conn.cursor()
        runner.open_run(cursor, context)
        runner.persist_scores(cursor, context, scores,
                              model="gpt-6-astra", prompt_version=deps.prompt_version)
        runner.persist_verdict(cursor, context, verdict)
        runner.bind_sources(cursor, context, tracker.as_dict())

    # --- 4. Review Gate ---------------------------------------------------
    state = review_gate.run(state, deps, deliverable=args.deliverable)

    # --- 5. Synthesis -----------------------------------------------------
    state = synthesis.run(state, deps)

    with connect(Principal.SCORE) as conn:
        runner.close_run(conn.cursor(), context, verdict)

    # ======================================================================
    # Report
    # ======================================================================
    print(f"\n{'=' * 78}")
    print(f"W5 ORCHESTRATED RUN  —  {state.scope.soc_code}")
    print(f"{'=' * 78}")
    print(f"  run_id           {context.run_id}")
    print(f"  phase            {state.phase.value}")
    print(f"  report produced  {state.phase.produced_a_report}")
    print(f"  scope rationale  {state.scope.rationale[:70]}")
    print()

    def profile(classifications):
        return {
            "unclear": sum(1 for c in classifications
                           if c.direction is Direction.UNCLEAR),
            "augment": sum(1 for c in classifications
                           if c.direction is Direction.AUGMENT),
            "substitute": sum(1 for c in classifications
                              if c.direction is Direction.SUBSTITUTE),
            "low_conf": sum(1 for c in classifications
                            if c.confidence is Confidence.LOW),
        }

    base_p, model_p = profile(base_classifications), profile(state.classifications)

    print(f"  {'':22} {'BASELINE (keyword)':>20} {'MODEL (gpt-6-astra)':>22}")
    print(f"  {'-' * 66}")
    print(f"  {'exposure index':22} {base_verdict.exposure_index:>20.3f} "
          f"{verdict.exposure_index:>22.3f}")
    print(f"  {'tasks classified':22} {len(base_scores):>20} {len(scores):>22}")
    print(f"  {'direction: unclear':22} {base_p['unclear']:>20} "
          f"{model_p['unclear']:>22}")
    print(f"  {'direction: augment':22} {base_p['augment']:>20} "
          f"{model_p['augment']:>22}")
    print(f"  {'direction: substitute':22} {base_p['substitute']:>20} "
          f"{model_p['substitute']:>22}")
    print(f"  {'low confidence':22} {base_p['low_conf']:>20} "
          f"{model_p['low_conf']:>22}")
    print(f"  {'cited evidence':22} {0:>20} "
          f"{sum(1 for c in state.classifications if c.evidence_claim_ids):>22}")
    print()
    print(f"  LAG (identical by design — independent of classification)")
    print(f"    p10 {verdict.lag.p10} | p50 {verdict.lag.p50} | p90 {verdict.lag.p90}"
          f"   curve fitted: {verdict.lag.curve_fitted}")
    print(f"    baseline lag identical: "
          f"{(base_verdict.lag.p10, base_verdict.lag.p50, base_verdict.lag.p90) == (verdict.lag.p10, verdict.lag.p50, verdict.lag.p90)}")
    print()
    print(f"  GATE  {state.gate.outcome if state.gate else 'not reached'}")
    if state.gate:
        print(f"    passed: {', '.join(state.gate.checks_passed[:5]) or '(none)'}")
        print(f"    failed: {', '.join(state.gate.checks_failed) or '(none)'}")
        print(f"    {state.gate.reasoning[:160]}")
    print()

    spend = ledger.summary()
    print(f"  SPEND  {spend['calls']} model calls, "
          f"{spend['total_tokens']:,} tokens, "
          f"{spend['provider_time_ms']:,} ms of provider time")
    print(f"    cost: {spend['cost_status']}")
    for stage, usage in ledger.by_stage().items():
        print(f"    {stage:18s} {usage.total_tokens:>8,} tokens")
    print()

    if state.narrative:
        print(f"  NARRATIVE ({len(state.narrative)} chars, every figure verified "
              f"against the evidence)")
        print(f"  {'-' * 66}")
        for line in state.narrative.splitlines()[:16]:
            print(f"  {line[:74]}")
    else:
        print(f"  NO NARRATIVE — gate outcome "
              f"{state.gate.outcome if state.gate else 'n/a'} does not produce a report")

    if state.unresolved:
        print(f"\n  UNRESOLVED ({len(state.unresolved)}):")
        for item in state.unresolved[:8]:
            print(f"    - {item[:110]}")


if __name__ == "__main__":
    main()
