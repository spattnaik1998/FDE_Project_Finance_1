"""Score the finance cohort so the calibration gate can be reached.

    python scripts/score_cohort.py --classifier baseline    # free, instant
    python scripts/score_cohort.py --classifier model       # the real result
    python scripts/score_cohort.py --classifier model --limit 4

Scores every occupation in the cohort with **one** classifier, then ranks our
index and the published benchmark within that cohort. Using one classifier for
the whole cohort is not a convenience: a reference set scored by two different
methods is not a reference set, and a percentile computed inside it would be an
artefact of which occupations got which classifier.

Only the target occupation's verdict is persisted. The other eleven exist to
give the target a rank, and writing eleven verdicts whose lag interval is
identical --- the lag is a sector-level quantity and does not vary by
occupation --- would fill ``score.role_verdict`` with rows no one asked for.
The cohort's own indices are printed and returned so the ranking is auditable.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

sys.path.insert(0, "src")

import config
from nodes import classifier as classifier_node
from nodes import retrieval
from nodes.state import Evidence, NodeDeps, Phase, RunState, Scope
from providers.accounting import Ledger
from scoring import baseline, cohort as cohort_module, exposure
from scoring import run as scoring_run
from tools.audit_adapter import AuditAdapter
from tools.consumption import ConsumptionTracker
from tools.evidence import EvidenceTools
from warehouse.session import Principal, connect

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("score_cohort")

TARGET_SOC = "13-2051.00"
FAMILY = "13-2"
MEASURE = "AIOE_language_modeling"
SECTOR = "52"


def cohort_members(cursor) -> dict[str, dict]:
    """Occupations with both current tasks and an AIOE benchmark value."""
    rows = cursor.execute("""
        SELECT t.soc_code, o.title, COUNT(*) AS tasks
        FROM core.task t
        JOIN ref.occupation o ON o.soc_code = t.soc_code
        WHERE t.is_current = 1 AND t.soc_code LIKE ?
        GROUP BY t.soc_code, o.title
        ORDER BY t.soc_code""", FAMILY + "%").fetchall()

    # core.exposure_estimate, not dbo.VW_EXPOSURE_BENCHMARK -- the same
    # correction cohort.load_benchmarks already carries, which this script was
    # missed by. The VW_* layer is the AGENT's scope control and is granted to
    # db_fde_ro alone; this runs in the scoring tier under db_fde_score, which
    # holds SELECT on SCHEMA::core because it is the tier that computes over
    # facts. The query worked until privilege isolation was enabled and then
    # failed on the first run under it. Widening the view grants would have been
    # the quick fix and would have blurred the tiers.
    #
    # is_current = 1 reproduces the view's filter: under append-only
    # persistence a superseded version is still present, and including it would
    # put one occupation's benchmark into the distribution twice.
    benchmark = {r[0]: float(r[1]) for r in cursor.execute("""
        SELECT soc_code, percentile FROM core.exposure_estimate
        WHERE measure = ? AND is_current = 1 AND soc_code LIKE ?""",
        MEASURE, FAMILY + "%").fetchall() if r[1] is not None}

    members = {}
    for soc_code, title, tasks in rows:
        base = soc_code.split(".")[0]
        if base in benchmark:
            members[soc_code] = {"title": title, "tasks": int(tasks),
                                 "benchmark": benchmark[base]}
    return members


def classify(tasks: list[dict], *, use_model: bool, deps: NodeDeps,
             soc_code: str):
    """Classify one occupation's tasks with the chosen classifier."""
    if not use_model:
        return baseline.classify_all(tasks)

    state = RunState(run_id=f"cohort-{soc_code}", request="cohort scoring")
    state.scope = Scope(soc_code=soc_code, naics_sector=SECTOR,
                        geography="US", rationale="cohort member")
    state.evidence = Evidence(tasks=tasks)
    state.phase = Phase.EVIDENCE_RETRIEVED
    state = classifier_node.run(state, deps)
    if state.phase is Phase.FAILED:
        raise RuntimeError(f"classification failed for {soc_code}: "
                           f"{'; '.join(state.errors)}")
    return state.classifications


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classifier", choices=["baseline", "model"],
                        default="baseline")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap tasks per occupation (cost control)")
    parser.add_argument("--persist", action="store_true",
                        help="Persist the target occupation's verdict")
    parser.add_argument("--database", default=None)
    args = parser.parse_args()

    use_model = args.classifier == "model"
    started = time.time()

    context = scoring_run.new_run()
    tracker = ConsumptionTracker(run_id=context.run_id)
    audit = AuditAdapter(run_id=context.run_id, database=args.database)
    ledger = Ledger(run_id=context.run_id)
    tools = EvidenceTools(tracker=tracker, audit=audit, database=args.database)
    deps = NodeDeps(tools=tools, tracker=tracker, audit=audit, ledger=ledger)

    with connect(Principal.SCORE, database=args.database) as conn:
        members = cohort_members(conn.cursor())

    if not members:
        print("No cohort members found. Run scripts/load_cohort.py first.")
        return 1

    print(f"\n{'=' * 84}")
    print(f"COHORT SCORING  —  {len(members)} occupations, "
          f"classifier={args.classifier}")
    print(f"{'=' * 84}")

    our_scores: dict[str, float] = {}
    benchmark_values: dict[str, float] = {}
    per_occupation: dict[str, dict] = {}

    for soc_code, meta in members.items():
        result = tools.get_tasks(soc_code)
        tasks = result.rows[:args.limit] if args.limit else result.rows
        if not tasks:
            print(f"  {soc_code:12} skipped: no tasks returned")
            continue

        classifications = classify(tasks, use_model=use_model, deps=deps,
                                   soc_code=soc_code)
        source_docs = {str(t["Task_ID"]): t["Source_Doc_ID"] for t in tasks}
        scores = exposure.score_tasks(list(classifications), source_docs)
        weighting = exposure.equal_weighting(scores)

        our_scores[soc_code] = weighting.lower
        benchmark_values[soc_code] = meta["benchmark"]
        per_occupation[soc_code] = {
            "index": weighting.lower, "tasks": len(scores),
            "title": meta["title"],
            "augment": exposure.augmentation_share(scores),
            "unclear": exposure.unclear_share(scores),
            "classifications": classifications, "scores": scores,
            "source_docs": source_docs,
        }
        print(f"  {soc_code:12} index {weighting.lower:.3f}  "
              f"({len(scores):>2} tasks)  AIOE pct {meta['benchmark']:>6.2f}  "
              f"{meta['title'][:38]}")

    # ------------------------------------------------------------------
    # The cohort comparison
    # ------------------------------------------------------------------
    with connect(Principal.SCORE, database=args.database) as conn:
        population = cohort_module.load_population(conn.cursor(),
                                                   measure=MEASURE)

    calibration = cohort_module.calibrate_within_cohort(
        TARGET_SOC, our_scores, benchmark_values,
        population_values=population)

    print(f"\n{'=' * 84}")
    print(f"COHORT CALIBRATION  —  target {TARGET_SOC}")
    print(f"{'=' * 84}")
    summary = calibration.summary()
    print(f"  cohort size            {summary['cohort_size']}")
    print(f"  our percentile         {summary['our_percentile']}")
    print(f"  benchmark percentile   {summary['benchmark_percentile']}")
    print(f"  delta                  {summary['delta']}")
    print(f"  rank correlation       {summary['rank_correlation']}")
    print(f"  granularity            {summary['granularity_points']} points")
    print(f"  identified             {summary['identified']}")
    print(f"  benchmark spread ratio {calibration.benchmark_spread_ratio} "
          f"(discriminates: {calibration.benchmark_discriminates})")

    if calibration.detail:
        print(f"\n  {'occupation':14} {'our index':>10} {'our rank':>9} "
              f"{'AIOE pct':>9} {'AIOE rank':>10}")
        for soc_code in calibration.members:
            row = calibration.detail[soc_code]
            marker = " <-- target" if soc_code == TARGET_SOC else ""
            print(f"  {soc_code:14} {row['ours']:>10.3f} {row['our_rank']:>9.1f} "
                  f"{row['benchmark']:>9.2f} {row['benchmark_rank']:>10.1f}"
                  f"{marker}")

    # ------------------------------------------------------------------
    # Feed it through the three-state gate
    # ------------------------------------------------------------------
    target = per_occupation.get(TARGET_SOC)
    if target is None:
        print(f"\n  {TARGET_SOC} was not scored; no verdict to build.")
        return 1

    state = RunState(run_id=context.run_id, request="cohort scoring")
    state.scope = Scope(soc_code=TARGET_SOC, naics_sector=SECTOR,
                        geography="US", rationale="cohort target")
    state = retrieval.run(state, deps)

    adjacent = [float(r["Importance"]) for r in state.evidence.adjacent_tasks
                if r.get("Importance") is not None]

    verdict, scores = scoring_run.build_verdict(
        soc_code=TARGET_SOC,
        classifications=target["classifications"],
        source_doc_ids=target["source_docs"],
        adoption_observations=state.evidence.adoption,
        historical_claims=retrieval.claims_for_lag(state),
        benchmark_percentile=calibration.benchmark_percentile,
        benchmark_measure=MEASURE,
        adjacent_weights=adjacent or None,
        our_percentile=calibration.our_percentile,
        rank_correlation=calibration.rank_correlation,
        calibration_explanation=cohort_module.cohort_explanation(calibration))

    print(f"\n{'=' * 84}")
    print("VERDICT")
    print(f"{'=' * 84}")
    print(f"  exposure index         {verdict.exposure_index:.3f}")
    print(f"  sensitivity bound      {verdict.primary_weighting.lower:.3f}"
          + (f" / {verdict.sensitivity_weighting.lower:.3f}–"
             f"{verdict.sensitivity_weighting.upper:.3f}"
             if verdict.sensitivity_weighting else ""))
    print(f"  lag p10/p50/p90        {verdict.lag.p10} / {verdict.lag.p50} / "
          f"{verdict.lag.p90}  curve_fitted={verdict.lag.curve_fitted}")
    print(f"  calibration outcome    {verdict.calibration.outcome.value}")
    print(f"  our pct / benchmark    {verdict.calibration.our_percentile} / "
          f"{verdict.calibration.benchmark_percentile}")
    print(f"  delta                  {verdict.calibration.delta}")
    print(f"  within tolerance       {verdict.calibration.within_tolerance}")

    # config.MODEL_CLASSIFIER, not a literal.
    #
    # This line read "gpt-6-astra" and that is how a cohort scored on
    # gpt-5.4-mini came to be written under gpt-6-astra's key -- the exact
    # mixture the (cohort, classifier, rubric) key exists to make
    # unrepresentable, defeated by a hardcoded string one layer above it. A
    # percentile computed against it would have been an artefact of which model
    # happened to score which occupation, and nothing would have said so.
    #
    # It was caught only because the table had just been made append-only: the
    # genuine astra rows were still there, demoted rather than deleted, so the
    # mislabelling was both visible and reversible.
    classifier_name = (config.MODEL_CLASSIFIER if use_model
                       else baseline.BASELINE_VERSION)

    if args.persist:
        with connect(Principal.SCORE, database=args.database) as conn:
            cursor = conn.cursor()
            # The reference set first: it is what makes calibration reachable
            # in a later interactive run without rescoring eleven occupations.
            cohort_rows = cohort_module.persist_cohort(
                cursor, cohort_name=cohort_module.DEFAULT_COHORT,
                classifier=classifier_name,
                rubric_version=context.rubric_version,
                indices=our_scores,
                task_counts={s: d["tasks"] for s, d in per_occupation.items()},
                source_run_id=context.run_id)
            print(f"\n  cohort reference rows  {cohort_rows} "
                  f"({classifier_name}, {context.rubric_version})")
            scoring_run.open_run(cursor, context)
            scoring_run.persist_scores(
                cursor, context, scores,
                model=classifier_name,
                prompt_version=deps.prompt_version)
            scoring_run.persist_verdict(cursor, context, verdict)
            bindings = scoring_run.bind_sources(cursor, context,
                                                tracker.as_dict())
            status = scoring_run.close_run(cursor, context, verdict)
        print(f"\n  persisted run          {context.run_id}")
        print(f"  status                 {status}")
        print(f"  source bindings        {bindings}")
    else:
        print("\n  not persisted (pass --persist to write this run)")

    spend = ledger.summary()
    if spend["calls"]:
        print(f"\n  spend                  {spend['calls']} calls, "
              f"{spend['total_tokens']:,} tokens, {spend['cost_status']}")
    print(f"  elapsed                {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
