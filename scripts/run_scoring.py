"""Score one occupation end to end, with no agent involved.

This is the P2 control run. It reads evidence through the same five views the
agent will later use, classifies with the keyword baseline, computes exposure
and lag on independent paths, calibrates, and persists a verdict.

Whatever number this produces is the bar the model classifier has to beat in
W5. If it cannot, the model is adding cost rather than judgment.
"""

from __future__ import annotations

import argparse
import logging
import sys

sys.path.insert(0, "src")

from scoring import baseline, run as runner
from tools.audit_adapter import AuditAdapter
from tools.consumption import ConsumptionTracker
from tools.evidence import EvidenceTools
from warehouse.session import Principal, connect

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("run_scoring")

TARGET_SOC = "13-2051.00"
BENCHMARK_SOC = "13-2051"        # AIOE uses the 6-digit code without the suffix
BENCHMARK_MEASURE = "AIOE_language_modeling"
FINANCE_SECTOR = "52"
ADJACENT_SOC = "13-2099.01"


def _rows(cursor, sql: str, *params) -> list[dict]:
    cursor.execute(sql, *params)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--soc", default=TARGET_SOC)
    parser.add_argument("--deliverable", action="store_true",
                        help="Mark the run customer-deliverable (gates on mirrors)")
    args = parser.parse_args()

    context = runner.new_run(is_customer_deliverable=args.deliverable)
    tracker = ConsumptionTracker(run_id=context.run_id)
    audit = AuditAdapter(run_id=context.run_id)
    tools = EvidenceTools(tracker=tracker, audit=audit, node="evidence_retrieval")

    # The control run reads through the same six tools the agent will use, so
    # the consumption binding and the audit trail are exercised now rather
    # than first appearing in W5.
    tasks = tools.get_tasks(args.soc).rows
    adoption = tools.get_adoption_curve(FINANCE_SECTOR).rows
    claims = tools.search_claims(topic="lag_length").rows
    claims += tools.search_claims(topic="j_curve_definition").rows

    benchmark_rows = tools.get_exposure_benchmarks(
        BENCHMARK_SOC, measure=BENCHMARK_MEASURE).rows
    benchmark_percentile = (float(benchmark_rows[0]["Percentile"])
                            if benchmark_rows else None)

    adjacent_weights = [float(r["Importance"])
                        for r in tools.get_tasks(ADJACENT_SOC).rows
                        if r.get("Importance") is not None]

    classifications = baseline.classify_all(tasks)
    source_docs = {t["Task_ID"]: t["Source_Doc_ID"] for t in tasks}

    verdict, scores = runner.build_verdict(
        soc_code=args.soc,
        classifications=classifications,
        source_doc_ids=source_docs,
        adoption_observations=adoption,
        historical_claims=claims,
        benchmark_percentile=benchmark_percentile,
        benchmark_measure=BENCHMARK_MEASURE,
        adjacent_weights=adjacent_weights or None,
        adjacent_soc=ADJACENT_SOC,
        our_percentile=None,   # one occupation scored: not identifiable
    )

    with connect(Principal.SCORE) as conn:
        cursor = conn.cursor()
        runner.open_run(cursor, context)
        runner.persist_scores(cursor, context, scores,
                              model=baseline.BASELINE_VERSION,
                              prompt_version="n/a-baseline")
        runner.persist_verdict(cursor, context, verdict)
        runner.bind_sources(cursor, context, tracker.as_dict())
        status = runner.close_run(cursor, context, verdict)

    # --- Report -----------------------------------------------------------
    print(f"\n{'=' * 78}")
    print(f"P2 CONTROL RUN (no agent)  —  {args.soc}")
    print(f"{'=' * 78}")
    print(f"  run_id           {context.run_id}")
    print(f"  classifier       {baseline.BASELINE_VERSION} (all low confidence)")
    print(f"  adjacent weights {len(adjacent_weights)} ratings from {ADJACENT_SOC}")
    print(f"  status           {status}")
    print()
    print(f"  EXPOSURE index   {verdict.exposure_index:.3f}   "
          f"(equal weighting, {len(scores)} tasks)")
    if verdict.sensitivity_weighting:
        s = verdict.sensitivity_weighting
        print(f"  sensitivity      {s.lower:.3f} – {s.upper:.3f}   "
              f"(bound under {ADJACENT_SOC})")
    print(f"  LAG years        p10 {verdict.lag.p10:.1f} | p50 {verdict.lag.p50:.1f} "
          f"| p90 {verdict.lag.p90:.1f}   (curve fitted: {verdict.lag.curve_fitted})")
    print(f"  observation win  {verdict.lag.observation_window_years:.2f} years")
    print(f"  augmentation     {verdict.augmentation_share:.0%}   "
          f"unclear {verdict.unclear_share:.0%}")
    print(f"  calibration      {verdict.calibration.outcome.value} "
          f"(benchmark {verdict.calibration.benchmark_percentile})")
    print()
    print("  Most exposed tasks:")
    for score in sorted(scores, key=lambda s: -s.exposure_adjusted)[:5]:
        statement = next(t["Statement"] for t in tasks if t["Task_ID"] == score.task_id)
        print(f"    {score.exposure_adjusted:.3f}  (raw {score.exposure_raw:.2f}, "
              f"tacit -{score.tacitness_penalty:.2f})  {statement[:62]}")
    print()
    print("  Least exposed tasks:")
    for score in sorted(scores, key=lambda s: s.exposure_adjusted)[:3]:
        statement = next(t["Statement"] for t in tasks if t["Task_ID"] == score.task_id)
        print(f"    {score.exposure_adjusted:.3f}  (raw {score.exposure_raw:.2f}, "
              f"tacit -{score.tacitness_penalty:.2f})  {statement[:62]}")
    print()
    print(f"  Caveats ({len(verdict.caveats)}):")
    for caveat in verdict.caveats:
        print(f"    - {caveat[:120]}")
    print()
    summary = tracker.summary()
    print(f"  Sources bound:   {summary['bindings']} bindings across "
          f"{summary['distinct_sources']} distinct sources {summary['by_usage']}")
    print(f"  Audit entries:   {audit.entries_written}")


if __name__ == "__main__":
    main()
