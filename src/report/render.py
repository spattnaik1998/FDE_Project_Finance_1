"""Render a persisted run as the document a customer reads.

Seven sections (build plan 7.1-7.4). Two rules shape the whole thing:

**Exposure and lag are stated separately and never combined.** They are
computed on independent paths; presenting them as one "risk score" would throw
away the property the architecture was built to preserve. There is deliberately
no headline number that mixes them.

**The standing of the result leads.** A run that did not calibrate is reported
as a run that did not calibrate, in section 1, before any figure. The TDD
withholds the *automatic narrative* on ``review_required``; it does not
withhold the analysis from the human the run was halted for. Burying that
qualification in an appendix would be the dishonest way to satisfy both.

Every number goes through :class:`report.figures.FigureRegistry`, which refuses
to render a figure that cannot name its source document.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from report.figures import FigureRegistry
from report.reader import ReportData

LOG = logging.getLogger("report.render")

REPORT_VERSION = "report_v1"

# What each calibration state means for how the document should be read. The
# customer-facing sentence is the point: "review_required" is jargon, and a
# reader deciding a hiring budget needs to know what it costs them.
STANDING = {
    "passed": (
        "CALIBRATED",
        "This run's exposure index agrees with the published benchmark within "
        "the active tolerance. The figures below may be used as stated."),
    "review_required": (
        "NOT YET CALIBRATED — ANALYST REVIEW REQUIRED",
        "The exposure index below could not be checked against the published "
        "benchmark, so it carries no external validation. The per-task "
        "reasoning and the adoption lag are unaffected and stand on their own "
        "evidence. Treat the role-level index as provisional."),
    "gate_rejected": (
        "REJECTED — DO NOT USE",
        "The review gate rejected this run. The figures are retained for "
        "diagnosis and must not be used for a decision."),
    "failed": (
        "INCOMPLETE",
        "The run did not finish. Figures may be partial."),
}


def _shorten(text: str, limit: int) -> str:
    """Trim to ``limit`` without splitting a token.

    Cutting mid-token can manufacture a number the source never contained --
    "2025" becomes a bare "25" -- so the trim falls back to the last whitespace
    boundary. Paired with registering the *shortened* string rather than the
    full one, so what is registered is exactly what is rendered.
    """
    if len(text) <= limit:
        return text
    cut = text[:max(limit - 3, 1)]
    if " " in cut:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,;:") + "..."


def _h(text: str, level: int = 2) -> str:
    return f"{'#' * level} {text}"


def _section_1_standing(data: ReportData, fig: FigureRegistry) -> str:
    """What this document is, and how much weight it can carry."""
    headline, meaning = STANDING.get(
        data.status, ("UNKNOWN STANDING", "Status not recognised."))

    lines = [
        _h("1. Standing of this analysis"),
        "",
        f"**{headline}**",
        "",
        meaning,
        "",
    ]

    if not data.calibration_is_identifiable:
        # The specific reason, not the generic one. This is the finding W2
        # surfaced and it belongs in front of the customer, not in a log.
        lines += [
            "**Why calibration could not be performed.** Calibration compares "
            "our exposure index to a published benchmark *as a percentile* — "
            "a rank within a distribution. This run scored a single "
            "occupation, and one score has no rank, so no percentile of our "
            "own exists to compare. The comparison is not in disagreement; it "
            "is unidentifiable.",
            "",
            "This is a property of the run's scope, not a defect in the score "
            "or the evidence. It resolves when several occupations are scored "
            "together, at which point the index acquires a rank and the "
            "benchmark comparison becomes meaningful.",
            "",
        ]
        benchmark_sources = _benchmark_sources(data)
        if data.benchmark_percentile is not None and benchmark_sources:
            benchmark = fig.emit(
                data.benchmark_percentile,
                label="published benchmark percentile",
                origin="score.calibration.benchmark_percentile",
                source_doc_ids=benchmark_sources, spec=".2f")
            lines += [
                f"The benchmark itself is available and is recorded: "
                f"**percentile {benchmark}** on `{data.benchmark_measure}`. "
                f"It is reported here as context, not as a comparison — there "
                f"is nothing on our side to compare it against.",
                "",
            ]
        elif data.benchmark_percentile is not None:
            # The value is persisted but the run bound no benchmark artefact,
            # so citing the number would be unsupported *for this run*. The
            # absence is stated rather than the figure quietly printed.
            lines += [
                f"A benchmark value for `{data.benchmark_measure}` is recorded "
                f"against this run, but the run bound no benchmark source "
                f"document, so the figure is withheld: it cannot be traced to "
                f"an artefact this run demonstrably consumed.",
                "",
            ]
    elif data.calibration_explanation:
        lines += ["**Gate reasoning.** " + fig.emit_prose(
            data.calibration_explanation, label="calibration explanation",
            origin="score.calibration.explanation",
            source_doc_ids=_benchmark_sources(data) or _task_sources(data)), ""]

    if data.unverified_mirrors():
        mirrors = ", ".join(f"`{s.doc_id}`" for s in data.unverified_mirrors())
        lines += [
            f"**Unverified mirror in the evidence chain:** {mirrors}. The "
            f"content is hashed and reproducible, but was obtained from a "
            f"copy rather than the publisher. Spot-check before external use.",
            "",
        ]

    return "\n".join(lines)


def _section_2_exposure(data: ReportData, fig: FigureRegistry) -> str:
    """The role-level exposure index and what weighting it assumes."""
    task_sources = _task_sources(data)
    index = fig.emit(data.exposure_index, label="role exposure index",
                     origin="score.role_verdict.exposure_index",
                     source_doc_ids=task_sources)

    lines = [
        _h("2. Exposure"),
        "",
        f"**Role exposure index: {index}** (0 = no task exposed, "
        f"1 = every task fully exposed), under `{data.weight_source}` "
        f"task weighting.",
        "",
        "Exposure measures how much of the role's task content a language "
        "model could in principle perform. It is **not** a probability of "
        "replacement and **not** a timetable — the timetable is section 3, "
        "computed on a path that never reads this number.",
        "",
    ]

    if data.weight_source == "equal":
        lines += [
            "**Weighting convention.** O*NET publishes no incumbent importance "
            "ratings for this occupation, so every task is weighted equally. "
            "Borrowing ratings from an adjacent quantitative occupation was "
            "rejected: those weights are endogenous to the question, and "
            "importing them would move the result in the direction we are "
            "trying to measure.",
            "",
        ]

    counts = data.direction_counts()
    scored = fig.emit(len(data.tasks), label="tasks scored",
                      origin="score.task_score (row count)",
                      source_doc_ids=task_sources, spec="d",
                      derivation="COUNT(*) over score.task_score for this run")
    lines += [f"The index aggregates **{scored} scored tasks**; the full table "
              f"is section 5.", ""]

    if data.tasks:
        top = data.tasks[0]
        bottom = data.tasks[-1]
        high = fig.emit(top.exposure_adjusted, label="highest task exposure",
                        origin="score.task_score.exposure_adjusted",
                        source_doc_ids=(top.source_doc_id,))
        low = fig.emit(bottom.exposure_adjusted, label="lowest task exposure",
                       origin="score.task_score.exposure_adjusted",
                       source_doc_ids=(bottom.source_doc_id,))
        lines += [
            f"**The score discriminates rather than saturating.** The spread "
            f"runs from {high} — *"
            + fig.emit_prose(top.statement.rstrip('.'),
                             label=f"task statement {top.task_id}",
                             origin="core.task.statement",
                             source_doc_ids=(top.source_doc_id,))
            + f"* — down to {low} — *"
            + fig.emit_prose(bottom.statement.rstrip('.'),
                             label=f"task statement {bottom.task_id}",
                             origin="core.task.statement",
                             source_doc_ids=(bottom.source_doc_id,))
            + "*. A rubric that returned a similar number for both would not "
              "be measuring anything.",
            "",
        ]
    return "\n".join(lines)


def _section_3_lag(data: ReportData, fig: FigureRegistry) -> str:
    """The adoption lag, stated as an interval and never as a date."""
    adoption_sources = _adoption_sources(data)
    p10 = fig.emit(data.lag_p10, label="lag p10 (years)",
                   origin="score.role_verdict.lag_years_p10",
                   source_doc_ids=adoption_sources, spec=".1f")
    p50 = fig.emit(data.lag_p50, label="lag p50 (years)",
                   origin="score.role_verdict.lag_years_p50",
                   source_doc_ids=adoption_sources, spec=".1f")
    p90 = fig.emit(data.lag_p90, label="lag p90 (years)",
                   origin="score.role_verdict.lag_years_p90",
                   source_doc_ids=adoption_sources, spec=".1f")

    return "\n".join([
        _h("3. Adoption lag"),
        "",
        f"**p10 {p10} years · p50 {p50} years · p90 {p90} years** until the "
        f"reorganisation that would realise the exposure above.",
        "",
        "**This is computed independently of the exposure index.** The lag "
        "path reads adoption observations and historical diffusion claims; it "
        "has no access to the exposure score, enforced structurally rather "
        "than by convention. A capability being available and a firm being "
        "reorganised to use it are different events, and conflating them is "
        "the standard error in this literature.",
        "",
        "**No curve is fitted.** The observed adoption window is too short to "
        "identify a saturation level, so fitting an S-curve would manufacture "
        "precision the data cannot support. The interval is wide because the "
        "evidence is thin, and narrowing it would be a presentational choice "
        "rather than a finding.",
        "",
        _basis_block(data, fig, adoption_sources),
        "",
    ])


def _basis_block(data: ReportData, fig: FigureRegistry,
                 adoption_sources: tuple[str, ...]) -> str:
    """The lag basis, with the supporting claim IDs pulled out of the prose.

    ``lag_basis`` ends with the claim identifiers that grounded the historical
    prior. They belong in the document -- that is the grounding -- but reading
    them mid-sentence is noise for someone deciding a hiring budget, so they
    are set below the basis rather than inside it. The whole string is still
    registered, so nothing escapes the traceability walk.
    """
    basis = fig.emit_prose(data.lag_basis, label="lag basis",
                           origin="score.role_verdict.lag_basis",
                           source_doc_ids=adoption_sources)
    marker = "Historical grounding:"
    if marker not in basis:
        return f"*Basis:* {basis}\n"
    body, grounding = basis.split(marker, 1)
    return (f"*Basis:* {body.strip()}\n\n"
            f"*Historical grounding (claim IDs):* {grounding.strip()}\n")


def _section_4_direction(data: ReportData, fig: FigureRegistry) -> str:
    """Whether exposure means substitution or augmentation."""
    counts = data.direction_counts()
    task_sources = _task_sources(data)
    total = len(data.tasks) or 1

    augment = fig.emit(counts["augment"], label="tasks judged augmenting",
                       origin="score.task_score.direction",
                       source_doc_ids=task_sources, spec="d",
                       derivation="COUNT(direction = 'augment')")
    substitute = fig.emit(counts["substitute"],
                          label="tasks judged substituting",
                          origin="score.task_score.direction",
                          source_doc_ids=task_sources, spec="d",
                          derivation="COUNT(direction = 'substitute')")
    unclear = fig.emit(counts["unclear"], label="tasks with unclear direction",
                       origin="score.task_score.direction",
                       source_doc_ids=task_sources, spec="d",
                       derivation="COUNT(direction = 'unclear')")

    lines = [
        _h("4. Direction: augmentation or substitution"),
        "",
        f"Of the tasks scored: **{augment} augmenting**, "
        f"**{substitute} substituting**, **{unclear} unclear**.",
        "",
        "Direction is *chosen, not given* (Acemoglu & Johnson): the same "
        "capability can automate a task or make the person doing it more "
        "productive, and which one happens is an organisational decision. "
        "`unclear` is a first-class answer — a classifier that cannot tell "
        "should say so rather than be pushed into a judgment.",
        "",
    ]

    if counts["substitute"] == 0 and counts["augment"] > 0:
        lines += [
            "**No task was judged to be substituted outright.** That is "
            "consistent with the survey prior: among finance firms that "
            "adopted AI, far more reported their workforce becoming more "
            "skilled than reported it shrinking. An exposure score that "
            "output \"replaced\" would have to clear that evidence, and this "
            "one does not claim to.",
            "",
        ]
    if counts["unclear"] == total:
        lines += [
            "**Every task came back unclear.** This is the deterministic "
            "keyword baseline, which cannot distinguish the two cases at all. "
            "It is the control, not the product.",
            "",
        ]
    return "\n".join(lines)


def _section_5_tasks(data: ReportData, fig: FigureRegistry) -> str:
    """The per-task table the charter promises the customer."""
    lines = [
        _h("5. Per-task detail"),
        "",
        "`raw` is the Acemoglu–Autor cell score; `tacit` is the Polanyi "
        "penalty subtracted from it; `adjusted` is what enters the index. "
        "Tacitness is a *discount* on exposure: work whose rules nobody can "
        "articulate is work a model cannot be given.",
        "",
        "| Task | Raw | Tacit | Adjusted | Direction | Conf. |",
        "|---|---|---|---|---|---|",
    ]
    for task in data.tasks:
        raw = fig.emit(task.exposure_raw, label=f"raw exposure {task.task_id}",
                       origin="score.task_score.exposure_raw",
                       source_doc_ids=(task.source_doc_id,))
        tacit = fig.emit(task.tacitness, label=f"tacitness {task.task_id}",
                         origin="score.task_score.tacitness",
                         source_doc_ids=(task.source_doc_id,))
        adjusted = fig.emit(task.exposure_adjusted,
                            label=f"adjusted exposure {task.task_id}",
                            origin="score.task_score.exposure_adjusted",
                            source_doc_ids=(task.source_doc_id,))
        statement = fig.emit_prose(
            _shorten(task.statement, 88),
            label=f"task statement {task.task_id}",
            origin="core.task.statement",
            source_doc_ids=(task.source_doc_id,)).replace("|", "\\|")
        lines.append(f"| {statement} | {raw} | {tacit} | {adjusted} | "
                     f"{task.direction} | {task.confidence} |")
    lines.append("")
    return "\n".join(lines)


def _section_6_limitations(data: ReportData, fig: FigureRegistry) -> str:
    """What this analysis cannot tell you. Stated, not implied."""
    lines = [
        _h("6. Limitations"),
        "",
        "These are properties of the available evidence, not defects in the "
        "pipeline. They are listed because a customer acting on the figures "
        "needs to know where they stop being load-bearing.",
        "",
    ]
    caveat_sources = _task_sources(data) + _adoption_sources(data)
    for caveat in data.caveats:
        lines.append("- " + fig.emit_prose(
            caveat, label="caveat", origin="score.role_verdict.caveats",
            source_doc_ids=caveat_sources))
    if not data.calibration_is_identifiable:
        lines.append(
            "- **The role-level index carries no external validation in this "
            "run.** See section 1. Per-task reasoning and the adoption lag are "
            "unaffected.")
    lines.append("")
    return "\n".join(lines)


def _section_7_provenance(data: ReportData, fig: FigureRegistry) -> str:
    """Every artefact this run consumed, with the digest that identifies it."""
    lines = [
        _h("7. Provenance appendix"),
        "",
        "Every source below was *consumed* by this run — bound at the moment a "
        "tool returned a row carrying it, not merely available in the "
        "warehouse. Each digest identifies an exact set of bytes, so any "
        "figure above can be walked back to the artefact it came from and that "
        "artefact re-fetched and re-hashed.",
        "",
        "| Source | Publisher | Format | Used as | SHA-256 |",
        "|---|---|---|---|---|",
    ]
    for source in data.sources:
        flag = " ⚠ mirror" if source.needs_spot_check else ""
        usage = ", ".join(source.usage_types) or "—"
        # The publisher string carries citation identifiers ("NBER Working
        # Paper 25148", "arXiv:2303.10130"). They are persisted in
        # ref.source_document.publisher and the artefact is its own source, so
        # they register like any other prose figure rather than being waved
        # through as furniture.
        publisher = fig.emit_prose(
            source.publisher, label=f"publisher {source.doc_id}",
            origin="ref.source_document.publisher",
            source_doc_ids=(source.doc_id,))
        lines.append(
            f"| `{source.doc_id}`{flag} | {publisher} | "
            f"{source.format} | {usage} | `{source.sha256[:16]}…` |")

    if data.claims:
        lines += [
            "",
            _h("Claim evidence (verbatim)", 3),
            "",
            "Claims drawn from prose carry the **verbatim quote and page**, "
            "never a paraphrase, so a reader can check the source says what "
            "the analysis reports it saying.",
            "",
            "*Binding granularity:* `audit.run_source_binding` records which "
            "**artefact** a tool returned a row from, not which individual "
            "quote was read. These are therefore the claims carried by the "
            "artefacts this run consumed as claim evidence — a source-level "
            "trace, stated as such rather than implying a finer one.",
            "",
            "| Topic | Page | Verbatim quote | Source |",
            "|---|---|---|---|",
        ]
        for claim in data.claims:
            # Truncate BEFORE registering. Registering the full quote and
            # rendering a shortened one lets truncation manufacture a figure
            # that is in the document but not in the source.
            quote = fig.emit_prose(
                _shorten(claim.quote, 160), label=f"claim {claim.claim_id}",
                origin="core.extracted_claim.quote",
                source_doc_ids=(claim.source_doc_id,)).replace("|", "\|")
            # The page number is provenance too, and traceable to the column
            # that holds it -- so it is registered rather than waved through
            # as a small structural integer.
            page = fig.emit(claim.page, label=f"page for {claim.claim_id}",
                            origin="core.extracted_claim.page",
                            source_doc_ids=(claim.source_doc_id,), spec="d")
            lines.append(f"| {claim.topic} | {page} | “{quote}” | "
                         f"`{claim.source_doc_id}` |")

    lines += [
        "",
        _h("Run identity", 3),
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Run | `{data.run_id}` |",
        f"| Status | `{data.status}` |",
        f"| Code version | `{data.git_sha[:12]}` |",
        f"| Config hash | `{data.config_hash[:16]}…` |",
        f"| Rubric | `{data.rubric_version}` |",
        f"| Calibration policy | `{data.calibration_policy_version}` |",
        f"| Customer deliverable | `{data.is_customer_deliverable}` |",
        "",
        "The rubric and calibration-policy versions are recorded because both "
        "are engineering bootstraps rather than validated criteria. A figure "
        "from this run is only comparable to a figure from another run that "
        "names the same versions.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Which bound sources justify which class of figure
# ---------------------------------------------------------------------------

def _sources_for(data: ReportData, *usage_types: str) -> tuple[str, ...]:
    """Bound sources consumed under any of the given usage types."""
    return tuple(s.doc_id for s in data.sources
                 if any(u in s.usage_types for u in usage_types))


def _task_sources(data: ReportData) -> tuple[str, ...]:
    found = _sources_for(data, "task_source")
    # Fall back to the source_doc_ids the scores themselves name, so an
    # exposure figure is never rendered unprovenanced merely because the
    # binding table was populated under a different usage label.
    return found or tuple(sorted({t.source_doc_id for t in data.tasks}))


def _adoption_sources(data: ReportData) -> tuple[str, ...]:
    return _sources_for(data, "adoption_evidence", "claim_evidence")


def _benchmark_sources(data: ReportData) -> tuple[str, ...]:
    return _sources_for(data, "exposure_benchmark")


# ---------------------------------------------------------------------------

def render(data: ReportData) -> tuple[str, FigureRegistry]:
    """Render the report and return it with the provenance of every figure."""
    fig = FigureRegistry()

    header = "\n".join([
        f"# Task Exposure & Adoption Lag — {data.occupation_title}",
        "",
        f"SOC {data.soc_code} · generated "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')} · "
        f"`{REPORT_VERSION}`",
        "",
        "> **Customer question.** Which of our cost lines are exposed to agent "
        "substitution, and on what timetable?",
        "",
        "> Exposure and timetable are reported as two separate quantities "
        "below, computed on independent paths. They are not combined into a "
        "single score, because the evidence does not support one.",
        "",
        "---",
        "",
    ])

    body = "\n".join([
        _section_1_standing(data, fig),
        _section_2_exposure(data, fig),
        _section_3_lag(data, fig),
        _section_4_direction(data, fig),
        _section_5_tasks(data, fig),
        _section_6_limitations(data, fig),
        _section_7_provenance(data, fig),
    ])

    markdown = header + body
    LOG.info("rendered run=%s status=%s figures=%s chars=%s",
             data.run_id, data.status, len(fig), len(markdown))
    return markdown, fig
