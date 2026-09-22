"""Invoke the graph, persist what it produced, and report honestly.

The graph itself writes only to the audit log. Persistence of the verdict,
scores and source bindings happens here, around the invocation, so the graph
stays a pure state machine that a test can drive without a database.

One deliberate simplification against the TDD diagram: the Review Gate reads
the verdict from the run state rather than re-reading it from ``score.*``.
The value is identical — it was assembled one node earlier and is persisted
immediately after — and reading state keeps the gate testable without a
database. Recorded here rather than left as a silent divergence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from graph import build
from nodes.state import NodeDeps, Phase, RunState
from providers.accounting import Ledger
from scoring import run as scoring_run
from tools.audit_adapter import AuditAdapter
from tools.consumption import ConsumptionTracker
from tools.evidence import EvidenceTools
from warehouse.session import Principal, connect

LOG = logging.getLogger("graph.runner")


@dataclass
class RunOutcome:
    """What a completed invocation produced."""

    state: RunState
    context: scoring_run.RunContext
    ledger: Ledger
    tracker: ConsumptionTracker
    persisted: bool = False
    status: str = "unknown"
    bindings: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def produced_a_report(self) -> bool:
        return self.state.phase.produced_a_report and bool(self.state.narrative)

    def summary(self) -> dict[str, Any]:
        verdict = self.state.verdict
        return {
            **self.state.summary(),
            "status": self.status,
            "persisted": self.persisted,
            "bindings": self.bindings,
            "lag": ([verdict.lag.p10, verdict.lag.p50, verdict.lag.p90]
                    if verdict else None),
            "curve_fitted": verdict.lag.curve_fitted if verdict else None,
            "spend": self.ledger.summary(),
        }


def make_deps(run_id: str, *, database: str | None = None, provider_for=None,
              our_percentile: float | None = None) -> NodeDeps:
    """Assemble the dependencies a run needs.

    ``provider_for`` is injectable so a test can drive the whole graph without
    a model call.
    """
    tracker = ConsumptionTracker(run_id=run_id)
    audit = AuditAdapter(run_id=run_id, database=database)
    return NodeDeps(
        tools=EvidenceTools(tracker=tracker, audit=audit, database=database),
        tracker=tracker, audit=audit, ledger=Ledger(run_id=run_id),
        provider_for=provider_for, our_percentile=our_percentile)


def invoke(request: str, *, deliverable: bool = False,
           database: str | None = None, provider_for=None,
           deps: NodeDeps | None = None,
           context: scoring_run.RunContext | None = None,
           our_percentile: float | None = None,
           persist: bool = True) -> RunOutcome:
    """Run one analysis end to end."""
    context = context or scoring_run.new_run(is_customer_deliverable=deliverable)
    deps = deps or make_deps(context.run_id, database=database,
                             provider_for=provider_for,
                             our_percentile=our_percentile)

    graph = build.compile_graph(deps, deliverable=deliverable, database=database)
    initial = RunState(run_id=context.run_id, request=request)

    # LangGraph returns the accumulated state; with a dataclass schema that is
    # a dict of fields, so it is rehydrated rather than used raw.
    raw = graph.invoke(initial)
    state = raw if isinstance(raw, RunState) else RunState(
        **{k: v for k, v in raw.items() if k in RunState.__dataclass_fields__})

    outcome = RunOutcome(state=state, context=context, ledger=deps.ledger,
                         tracker=deps.tracker)

    if not persist:
        outcome.status = state.phase.value
        outcome.notes.append("Persistence skipped by request.")
        return outcome

    # A run that never produced a verdict has nothing to persist. Recording
    # that explicitly beats an empty row that looks like a result.
    if state.verdict is None:
        outcome.status = state.phase.value
        outcome.notes.append(
            f"No verdict was produced (phase {state.phase.value}); nothing "
            f"persisted. Errors: {'; '.join(state.errors) or 'none'}")
        LOG.warning("run=%s status=%s persisted=false", context.run_id,
                    state.phase.value)
        return outcome

    with connect(Principal.SCORE, database=database) as conn:
        cursor = conn.cursor()
        scoring_run.open_run(cursor, context)
        scoring_run.persist_scores(cursor, context, state.scores,
                                   model=_classifier_model(deps),
                                   prompt_version=deps.prompt_version)
        scoring_run.persist_verdict(cursor, context, state.verdict)
        outcome.bindings = scoring_run.bind_sources(
            cursor, context, deps.tracker.as_dict())
        outcome.status = scoring_run.close_run(
            cursor, context, state.verdict,
            gate_outcome=state.gate.outcome if state.gate else None)

    outcome.persisted = True
    LOG.info("run=%s status=%s phase=%s report=%s bindings=%s",
             context.run_id, outcome.status, state.phase.value,
             outcome.produced_a_report, outcome.bindings)
    return outcome


def _classifier_model(deps: NodeDeps) -> str:
    """Which model produced the classifications, for the score rows."""
    for call in deps.ledger.calls:
        if call.stage == "task_classifier":
            return call.model
    return "unknown"
