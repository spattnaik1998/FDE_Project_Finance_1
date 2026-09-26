"""Drive the assembled graph against the real warehouse.

W5's script chained the nodes by hand. This one hands control to LangGraph and
prints what the graph itself decided: which nodes ran, which edges were taken,
and where the run stopped.

The topology is printed first, before any model call, because the two claims
the architecture rests on are visible there and nowhere else:

* the exposure and lag paths fan out from retrieval and meet only at assembly,
  with no edge between them;
* a gated run terminates without reaching synthesis.
"""

from __future__ import annotations

import argparse
import logging
import sys

sys.path.insert(0, "src")

from graph import build, runner

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")

DEFAULT_REQUEST = ("Which of our equity research associate cost lines are exposed "
                   "to agent substitution, and on what timetable?")


def print_topology() -> None:
    edges = sorted(build.edges())
    print(f"\n{'=' * 78}")
    print(f"GRAPH TOPOLOGY  —  {build.GRAPH_VERSION}")
    print(f"{'=' * 78}")
    for source, target in edges:
        print(f"  {source:22s} -> {target}")
    print()
    print(f"  exposure path reaches lag path:  "
          f"{build.reaches(build.EXPOSURE_PATH, build.LAG_PATH)}")
    print(f"  lag path reaches exposure path:  "
          f"{build.reaches(build.LAG_PATH, build.EXPOSURE_PATH)}")
    print(f"  fields written by both branches: "
          f"{build.concurrent_write_conflicts() or '(none)'}")
    # Asked of the routing function, not the drawn edges: LangGraph's drawable
    # graph omits a conditional edge whose target is END, so the termination
    # branch is invisible in the topology above.
    from nodes.state import GateDecision, RunState
    rejected = RunState(run_id="topology-probe", request="",
                        gate=GateDecision(outcome="gate_rejected"))
    print(f"  gate_rejected routes to:         "
          f"{build.route_after_gate(rejected)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", default=DEFAULT_REQUEST)
    parser.add_argument("--deliverable", action="store_true")
    parser.add_argument("--topology-only", action="store_true",
                        help="Print the graph and exit; no model calls, no cost")
    args = parser.parse_args()

    print_topology()
    if args.topology_only:
        return

    outcome = runner.invoke(args.request, deliverable=args.deliverable)
    state = outcome.state
    verdict = state.verdict

    print(f"\n{'=' * 78}")
    print(f"GRAPH RUN  —  {state.scope.soc_code if state.scope else 'no scope'}")
    print(f"{'=' * 78}")
    print(f"  run_id           {outcome.context.run_id}")
    print(f"  phase            {state.phase.value}")
    print(f"  status persisted {outcome.status}")
    print(f"  source bindings  {outcome.bindings}")
    print(f"  report produced  {outcome.produced_a_report}")
    print()

    if verdict:
        # The sensitivity is a WeightingBound, not two scalars. An earlier
        # version of this script read verdict.sensitivity_low / _high, which
        # do not exist -- and it never surfaced because the full path had only
        # ever been driven with --topology-only or through runner.invoke
        # directly. The first real end-to-end run crashed here, after the graph
        # had already succeeded and persisted.
        sensitivity = verdict.sensitivity_weighting
        bound = (f"sensitivity {sensitivity.lower:.3f}–{sensitivity.upper:.3f}"
                 if sensitivity else "no adjacent-SOC sensitivity available")
        print(f"  EXPOSURE  {verdict.exposure_index:.3f}   ({bound})")
        print(f"  LAG       p10 {verdict.lag.p10} | p50 {verdict.lag.p50} | "
              f"p90 {verdict.lag.p90}   curve fitted: {verdict.lag.curve_fitted}")
        calibration = verdict.calibration
        print(f"  CALIBRATION  {calibration.outcome.value}  "
              f"ours={calibration.our_percentile} "
              f"benchmark={calibration.benchmark_percentile} "
              f"delta={calibration.delta}")
    else:
        print("  NO VERDICT — the graph halted before assembly")

    print()
    print(f"  GATE  {state.gate.outcome if state.gate else 'not reached'}")

    spend = outcome.ledger.summary()
    print(f"\n  SPEND  {spend['calls']} model calls, "
          f"{spend['total_tokens']:,} tokens, "
          f"{spend['provider_time_ms']:,} ms of provider time")
    print(f"    cost: {spend['cost_status']}")

    if state.narrative:
        print(f"\n  NARRATIVE ({len(state.narrative)} chars)")
        print(f"  {'-' * 66}")
        for line in state.narrative.splitlines()[:16]:
            print(f"  {line[:74]}")
    else:
        print(f"\n  NO NARRATIVE — synthesis was not reached")

    for note in outcome.notes:
        print(f"\n  NOTE  {note[:200]}")

    if state.unresolved:
        print(f"\n  UNRESOLVED ({len(state.unresolved)}):")
        for item in state.unresolved[:8]:
            print(f"    - {item[:110]}")


if __name__ == "__main__":
    main()
