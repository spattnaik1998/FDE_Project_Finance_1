"""The application-tier facade the UI calls.

This module is allowed to reach the warehouse; the UI is not. It loads a
persisted run, renders the report, walks the traceability chain, and flattens
all of it into a :class:`ReportView` of plain strings.

Two things it deliberately does **not** do:

* **It does not score.** The UI renders a run that already happened. Nothing
  here recomputes an index, refits a lag or calls a model, so opening the app
  cannot change a number a customer was shown.
* **It does not format numbers of its own.** Every figure it puts on the view
  comes from the report's figure registry, which already refused to produce a
  figure without provenance. The gateway copies strings; it does no arithmetic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from report import provenance, reader, render
from report.reader import ReportData

from app.view_model import (ClaimView, ReportView, SourceView, StandingView,
                            TaskRowView)

LOG = logging.getLogger("app.gateway")

ABSENT = "not identifiable"

# Tone per persisted status, so the UI does not have to interpret the
# vocabulary. 'stop' means the figures must not drive a decision.
TONE = {
    "passed": "ok",
    "review_required": "warn",
    "gate_rejected": "stop",
    "failed": "stop",
    "running": "warn",
}


class NoRunAvailable(LookupError):
    """Nothing has been scored yet, so there is nothing to show."""


def available_runs(*, database: str | None = None, limit: int = 20):
    """Recent runs that persisted a verdict, newest first."""
    from warehouse.session import Principal, connect

    with connect(Principal.SCORE, database=database) as conn:
        rows = conn.cursor().execute("""
            SELECT TOP (?) CONVERT(NVARCHAR(36), r.run_id), r.status,
                   r.started_at, v.soc_code, v.exposure_index
            FROM score.run r
            JOIN score.role_verdict v ON v.run_id = r.run_id
            ORDER BY r.started_at DESC""", limit).fetchall()
    return [{"run_id": r[0], "status": r[1], "started_at": r[2],
             "soc_code": r[3], "exposure_index": float(r[4])} for r in rows]


def load_view(run_id: str | None = None, *,
              database: str | None = None) -> ReportView:
    """Assemble the view for one run. The UI's single entry point."""
    if run_id is None:
        run_id = reader.latest_run_id(database=database)
        if run_id is None:
            raise NoRunAvailable(
                "No run has persisted a verdict yet. Run "
                "`python scripts/run_graph.py` first; the UI renders results, "
                "it does not produce them.")

    data = reader.load_run(run_id, database=database)
    markdown, registry = render.render(data)
    trace = provenance.walk(markdown, registry, data)

    view = _to_view(data, registry, trace, markdown)
    LOG.info("view run=%s status=%s figures=%s complete=%s",
             view.run_id, view.status, view.trace_figures, view.trace_complete)
    return view


def _standing(data: ReportData) -> StandingView:
    """The headline, and why, in customer language."""
    headline, meaning = render.STANDING.get(
        data.status, ("UNKNOWN STANDING", "Status not recognised."))
    reason = None
    if not data.calibration_is_identifiable:
        reason = (
            "Calibration compares our exposure index to a published benchmark "
            "as a percentile — a rank within a distribution. This run scored a "
            "single occupation, and one score has no rank, so no percentile of "
            "our own exists to compare against. The comparison is not in "
            "disagreement; it is unidentifiable. Scoring several occupations "
            "together resolves it.")
    elif data.calibration_explanation:
        reason = data.calibration_explanation
    return StandingView(headline=headline, meaning=meaning,
                        tone=TONE.get(data.status, "warn"), reason=reason)


def _figure_literals(registry) -> frozenset[str]:
    """Every literal the report legitimately produced.

    The UI must display nothing outside this set. Formatted variants the view
    introduces for readability are added alongside, never in place of.
    """
    literals = {f.literal for f in registry.figures}
    return frozenset(literals)


def _to_view(data: ReportData, registry, trace, markdown: str) -> ReportView:
    counts = data.direction_counts()

    def fmt(value, spec=".3f"):
        """Format only what the report already registered, else say absent."""
        return ABSENT if value is None else format(value, spec)

    basis, grounding = data.lag_basis, ""
    marker = "Historical grounding:"
    if marker in basis:
        basis, grounding = basis.split(marker, 1)
        basis, grounding = basis.strip(), grounding.strip()

    return ReportView(
        run_id=data.run_id,
        status=data.status,
        soc_code=data.soc_code,
        occupation_title=data.occupation_title,
        generated_on=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        standing=_standing(data),

        exposure_index=fmt(data.exposure_index),
        weight_source=data.weight_source,
        weighting_note=(
            "O*NET publishes no incumbent importance ratings for this "
            "occupation, so every task is weighted equally. Borrowing ratings "
            "from an adjacent quantitative occupation was rejected: those "
            "weights are endogenous to the question."
            if data.weight_source == "equal" else
            f"Task weighting: {data.weight_source}."),
        tasks_scored=str(len(data.tasks)),

        lag_p10=fmt(data.lag_p10, ".1f"),
        lag_p50=fmt(data.lag_p50, ".1f"),
        lag_p90=fmt(data.lag_p90, ".1f"),
        lag_basis=basis,
        lag_grounding=grounding,
        curve_fitted=False,

        calibration_outcome=data.calibration_outcome,
        calibration_is_identifiable=data.calibration_is_identifiable,
        benchmark_measure=data.benchmark_measure,
        benchmark_percentile=fmt(data.benchmark_percentile, ".2f"),
        our_percentile=fmt(data.our_percentile, ".2f"),
        delta=fmt(data.delta, ".2f"),

        direction_augment=str(counts["augment"]),
        direction_substitute=str(counts["substitute"]),
        direction_unclear=str(counts["unclear"]),

        tasks=tuple(TaskRowView(
            statement=t.statement,
            raw=fmt(t.exposure_raw), tacit=fmt(t.tacitness),
            adjusted=fmt(t.exposure_adjusted),
            direction=t.direction, confidence=t.confidence)
            for t in data.tasks),
        sources=tuple(SourceView(
            doc_id=s.doc_id, title=s.title, publisher=s.publisher, url=s.url,
            format=s.format, sha256=s.sha256,
            used_as=", ".join(s.usage_types) or "—",
            is_unverified_mirror=s.needs_spot_check)
            for s in data.sources),
        claims=tuple(ClaimView(
            claim_id=c.claim_id, topic=c.topic, quote=c.quote,
            page=str(c.page), source_doc_id=c.source_doc_id)
            for c in data.claims),
        caveats=tuple(data.caveats),

        trace_figures=str(len(trace.links)),
        trace_complete=trace.is_complete,
        trace_customer_deliverable=trace.customer_deliverable,
        trace_detail=trace.failure_detail(),

        git_sha=data.git_sha,
        rubric_version=data.rubric_version,
        calibration_policy_version=data.calibration_policy_version,
        is_customer_deliverable=data.is_customer_deliverable,

        figures=_figure_literals(registry),
        markdown=markdown,
    )


# ---------------------------------------------------------------------------
# The request half of the tier contract
# ---------------------------------------------------------------------------
#
# TDD 1.1 draws a typed request from the presentation tier into orchestration.
# Only the response direction existed until now: the UI rendered persisted runs
# and a CLI script drove the graph. This is the missing half.
#
# It lives in the gateway rather than in the UI for the same reason load_view
# does -- this is the application tier, which legitimately holds credentials and
# may import the orchestration package. The UI calls submit() and receives plain
# values, so it still holds no handle and computes nothing.

def in_scope_occupations(*, database: str | None = None) -> list[dict]:
    """Occupations the warehouse actually publishes, for the request form.

    A form that mostly returns "out of scope" is a poor way to learn what the
    system covers, so the UI shows the answer up front rather than making the
    customer guess and pay for a refusal.
    """
    from warehouse.session import Principal, connect

    with connect(Principal.SCORE, database=database) as conn:
        rows = conn.cursor().execute("""
            SELECT o.soc_code, o.title, COUNT(*) AS tasks
            FROM core.task t
            JOIN ref.occupation o ON o.soc_code = t.soc_code
            WHERE t.is_current = 1
            GROUP BY o.soc_code, o.title
            ORDER BY o.title""").fetchall()
    return [{"soc_code": r[0], "title": r[1], "tasks": int(r[2])} for r in rows]


def submit(request, *, database: str | None = None) -> "SubmissionResult":
    """Run one analysis from a typed request and return a typed result.

    Blocking by design. A run is a fixed node set over a known task count, so
    its cost is predictable and the caller is told it up front; a fire-and-forget
    submission would hand back a job id and lose the refusal path, which is the
    outcome most likely to matter.

    Every failure becomes a :class:`RefusalReason` rather than an exception. The
    presentation tier has no sensible handling for a traceback, and "that
    occupation is not published" is a correct answer that a customer should read
    as one.
    """
    from app.contract import RefusalReason, SubmissionResult
    from graph import runner as graph_runner
    from nodes.state import Phase

    try:
        outcome = graph_runner.invoke(
            request.question,
            deliverable=request.is_customer_deliverable,
            database=database)
    except Exception as exc:                        # noqa: BLE001 - surfaced
        LOG.warning("submit failed status=error error=%s", exc)
        return SubmissionResult(
            accepted=False,
            refusal=RefusalReason(
                code="orchestration_error",
                message=(f"The run could not be completed: "
                         f"{type(exc).__name__}. Nothing was persisted."),
            ))

    spend = outcome.ledger.summary()
    state = outcome.state

    if state.phase is Phase.OUT_OF_SCOPE:
        hint = tuple(f"{o['title']} ({o['soc_code']})"
                     for o in in_scope_occupations(database=database))
        return SubmissionResult(
            accepted=False,
            refusal=RefusalReason(
                code="out_of_scope",
                message=(state.errors[-1] if state.errors else
                         "The request resolved to an occupation this warehouse "
                         "does not publish, so no analysis was produced."),
                in_scope_hint=hint),
            calls=spend["calls"], tokens=spend["total_tokens"],
            duration_ms=spend["duration_ms"])

    if state.verdict is None:
        return SubmissionResult(
            accepted=False,
            refusal=RefusalReason(
                code="no_verdict",
                message=(f"The run halted at {state.phase.value} without "
                         f"producing a verdict. "
                         f"{'; '.join(state.errors) or 'No error was recorded.'}"),
            ),
            calls=spend["calls"], tokens=spend["total_tokens"],
            duration_ms=spend["duration_ms"])

    LOG.info("submit accepted run=%s status=%s calls=%s",
             outcome.context.run_id, outcome.status, spend["calls"])
    return SubmissionResult(
        accepted=True, run_id=outcome.context.run_id, status=outcome.status,
        calls=spend["calls"], tokens=spend["total_tokens"],
        duration_ms=spend["duration_ms"])
