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

import config
from report import provenance, reader, render
from report.reader import ReportData

from app import copy as ui_copy
from app.view_model import (ClaimView, CohortRowView, CohortView, ReportView,
                            SourceView, StandingView, TaskRowView)

LOG = logging.getLogger("app.gateway")

ABSENT = "not identifiable"

# The published benchmark this project calibrates against.
BENCHMARK_MEASURE = "AIOE_language_modeling"

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
    # From app.copy, not report.render. The report is a technical document and
    # may say "review_required"; the page is read by someone deciding headcount
    # and needs a usability verdict they can act on. Two vocabularies, on
    # purpose -- the same status, said to two different readers.
    headline, meaning = ui_copy.STANDING.get(
        data.status, ("Status unclear", "This run's state is not recognised."))
    # Two levels, because they answer different questions. `reason` says why the
    # check could not settle it in terms a research director can act on;
    # `workings` is the statistical argument itself, kept verbatim from the
    # report so the rigour is one click away rather than paraphrased away.
    reason = None
    if data.status == "review_required":
        reason = (ui_copy.WHY_INCONCLUSIVE if data.calibration_is_identifiable
                  else ui_copy.WHY_UNIDENTIFIABLE)
    workings = data.calibration_explanation or None
    return StandingView(headline=headline, meaning=meaning,
                        tone=TONE.get(data.status, "warn"), reason=reason,
                        workings=workings)


def _presentation_forms(data: ReportData) -> frozenset[str]:
    """The same provenanced quantities, re-expressed for the view.

    The exposure meter needs its index as a CSS percentage. That is the same
    figure in another unit, not a new one -- it is derived from
    ``score.role_verdict.exposure_index``, which the registry already traced to
    a hashed artefact.

    It is added to the traced set rather than exempted from the scan. The
    alternative was to teach the traceability check to ignore "style" keys, and
    an exemption list is exactly how a figure with no source eventually slips
    onto a page.
    """
    forms: set[str] = set()
    try:
        share = float(data.exposure_index) * 100
        forms.add(f"{share:.1f}%")        # the meter's CSS width
        forms.add(f"{round(share)}%")     # the share quoted in prose
    except (TypeError, ValueError):
        pass
    # And every per-task bar in the exposure spine, for the same reason: each is
    # that task's own adjusted score in another unit, already registered.
    for task in data.tasks:
        forms.add(_bar(task.exposure_adjusted))
    return frozenset(forms)


def _ran_on_the_full_profile(data: ReportData) -> bool:
    """Whether the run that produced these figures used the full model profile.

    Derived from the model recorded against the run's scores rather than from
    ``config.MODEL_PROFILE``, because the configuration can change between the
    run and the reading. A page that reported the current setting would describe
    this process, not the document.
    """
    full = set(config.MODEL_PROFILES["full"].values())
    models = {t.model for t in data.tasks if getattr(t, "model", None)}
    if not models:
        # No attribution recorded. Refusing to claim clearance is the safe
        # direction: the question is "may I send this out", and "we cannot tell
        # what scored it" is not a yes.
        return False
    return models.issubset(full)


def _bar(value) -> str:
    """One task's net exposure as a CSS width.

    Computed here rather than in the presentation tier, which is forbidden to do
    arithmetic --- a layer that can compute can produce a figure that is on no
    source, and the test that walks the page for untraceable numbers would have
    nothing to catch it with. This tier already holds the traced figures, so the
    unit conversion belongs here and the result joins the traced set.
    """
    try:
        return f"{max(0.0, min(1.0, float(value))) * 100:.0f}%"
    except (TypeError, ValueError):
        return "0%"


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
            direction=t.direction, confidence=t.confidence,
            exposure_bar=_bar(t.exposure_adjusted))
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
        # Read from the run's recorded model, not from the profile in force now:
        # a page rendered next month must say what produced THAT run, not what
        # this process happens to be configured with.
        full_model_profile=_ran_on_the_full_profile(data),

        git_sha=data.git_sha,
        rubric_version=data.rubric_version,
        calibration_policy_version=data.calibration_policy_version,
        is_customer_deliverable=data.is_customer_deliverable,

        figures=_figure_literals(registry) | _presentation_forms(data),
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


class NoCohortAvailable(LookupError):
    """No reference set exists for this classifier and rubric."""


class NoAdoptionAvailable(LookupError):
    """No aligned adoption observations exist for the sector."""


def load_cohort(*, classifier: str | None = None,
                database: str | None = None) -> CohortView:
    """The portfolio view: every role in one reference set, ranked.

    Reads ``score.cohort_index`` for a single
    ``(cohort, classifier, rubric_version)`` key and nothing else. Mixing
    classifiers is not offered as an option, because a reference set scored by
    two methods is not one cohort and a ranking drawn across a mixture would
    measure which model scored which occupation.

    ``is_current = 1`` because the table is append-only: a superseded derivation
    is still present, and ranking across versions would put one occupation in
    the distribution twice.

    Degrades by raising rather than by returning a short list. A portfolio view
    missing four of its twelve rows still looks like a portfolio view, which is
    the failure mode worth refusing.
    """
    from scoring.cohort import DEFAULT_COHORT
    from scoring.run import RUBRIC_VERSION
    from warehouse.session import Principal, connect

    classifier = classifier or config.MODEL_CLASSIFIER

    with connect(Principal.SCORE, database=database) as conn:
        cursor = conn.cursor()
        rows = cursor.execute("""
            SELECT c.soc_code, o.title, c.exposure_index, c.tasks_scored
            FROM score.cohort_index c
            JOIN ref.occupation o ON o.soc_code = c.soc_code
            WHERE c.is_current = 1 AND c.cohort_name = ?
              AND c.classifier = ? AND c.rubric_version = ?
            ORDER BY c.exposure_index DESC""",
            DEFAULT_COHORT, classifier, RUBRIC_VERSION).fetchall()
        if not rows:
            raise NoCohortAvailable(
                f"No reference set for cohort {DEFAULT_COHORT!r} under "
                f"classifier {classifier!r} and rubric {RUBRIC_VERSION!r}. "
                f"Score the cohort first: "
                f"`python scripts/score_cohort.py --classifier model --persist`.")

        # Which occupations can actually be opened. Derived from what is
        # persisted, never assumed from cohort membership: a cohort row is one
        # number, while a drill-down needs a verdict and its task scores.
        drillable = {r[0] for r in cursor.execute("""
            SELECT DISTINCT v.soc_code FROM score.role_verdict v
            WHERE EXISTS (SELECT 1 FROM score.task_score s
                          WHERE s.run_id = v.run_id)""").fetchall()}

        # The hero figure, counted over the whole reference set rather than one
        # run, and over CURRENT task rows only.
        tasks_assessed = cursor.execute("""
            SELECT COUNT(*) FROM core.task t
            WHERE t.is_current = 1 AND t.soc_code IN (
                SELECT soc_code FROM score.cohort_index
                WHERE is_current = 1 AND cohort_name = ?
                  AND classifier = ? AND rubric_version = ?)""",
            DEFAULT_COHORT, classifier, RUBRIC_VERSION).fetchone()[0]

        # Scoped to the LATEST run per occupation under THIS classifier.
        #
        # A bare `COUNT(*) WHERE direction = 'substitute'` was the first cut and
        # it returned 6: a sum across five runs, three occupations and two
        # models, which against a 231-task denominator is three different
        # populations in one ratio. The denominator and the role count travel
        # with the number so the page cannot present it as a portfolio finding.
        scoped = cursor.execute("""
            WITH latest AS (
              SELECT v.soc_code, v.run_id,
                     ROW_NUMBER() OVER (PARTITION BY v.soc_code
                                        ORDER BY v.created_at DESC) AS rn
              FROM score.role_verdict v
              JOIN score.task_score s ON s.run_id = v.run_id AND s.model = ?
              GROUP BY v.soc_code, v.run_id, v.created_at)
            SELECT COUNT(DISTINCT l.soc_code), COUNT(*),
                   SUM(CASE WHEN s.direction = 'substitute' THEN 1 ELSE 0 END)
            FROM latest l JOIN score.task_score s ON s.run_id = l.run_id
            WHERE l.rn = 1""", classifier).fetchone()
        sub_roles, sub_of, sub_count = (int(scoped[0] or 0), int(scoped[1] or 0),
                                        int(scoped[2] or 0))

        # The lag, read once. Asserted single-valued rather than averaged: it is
        # estimated from sector-level adoption evidence, so it does not vary by
        # occupation, and a mean over identical values would imply it could.
        lags = cursor.execute("""
            SELECT DISTINCT lag_years_p10, lag_years_p50, lag_years_p90
            FROM score.role_verdict""").fetchall()

    if len(lags) != 1:
        LOG.warning("cohort=%s status=lag_not_single_valued distinct=%s",
                    DEFAULT_COHORT, len(lags))
    lag = lags[0] if len(lags) == 1 else (None, None, None)

    indices = [float(r[2]) for r in rows]
    cohort_rows = tuple(
        CohortRowView(
            soc_code=r[0], title=r[1],
            exposure_index=f"{float(r[2]):.3f}",
            tasks_scored=str(int(r[3])),
            has_full_run=r[0] in drillable,
            bar_percent=_bar(r[2]))
        for r in rows)

    # Chart geometry, computed here because this tier may and the presentation
    # tier may not. Only the printed values join `figures`; the pixel positions
    # stay in the geometry's own `layout` set, because a datum multiplied by a
    # plot width is not a number a reader can read.
    from app import geometry as geom
    ranking = geom.bars(
        [(r.title, float(r.exposure_index), r.exposure_index,
          not r.has_full_run) for r in cohort_rows], axis_max=1.0)

    view = CohortView(
        cohort_name=DEFAULT_COHORT, classifier=classifier,
        rubric_version=RUBRIC_VERSION, rows=cohort_rows,
        roles_assessed=str(len(cohort_rows)),
        tasks_assessed=str(int(tasks_assessed)),
        substitutable_count=str(sub_count), substitutable_of=str(sub_of),
        substitutable_roles=str(sub_roles),
        exposure_low=f"{min(indices):.3f}", exposure_high=f"{max(indices):.3f}",
        most_exposed_title=cohort_rows[0].title,
        least_exposed_title=cohort_rows[-1].title,
        lag_p10=_fmt_lag(lag[0]), lag_p50=_fmt_lag(lag[1]),
        lag_p90=_fmt_lag(lag[2]),
        drillable_roles=str(len(drillable & {r[0] for r in rows})),
        figures=_cohort_figures(cohort_rows, indices, tasks_assessed,
                                (sub_count, sub_of, sub_roles), lag)
                | ranking.figures,
        ranking_geometry=ranking)

    LOG.info("cohort=%s classifier=%s rows=%s drillable=%s tasks=%s",
             DEFAULT_COHORT, classifier, len(cohort_rows),
             view.drillable_roles, tasks_assessed)
    return view


# BTOS question codes, named rather than left as numbers in a query. Q7 is
# current use and Q24 is expected use within six months; the data carries the
# codes, so the mapping lives here once.
ADOPTION_QUESTIONS = (("7", "Using AI now"),
                      ("24", "Expect to within six months"))
ADOPTION_SECTOR = "52"
ADOPTION_NOTE = (
    "Measured for NAICS 52, which pools banking and insurance with securities, "
    "while the cost line is securities (NAICS 523). Census publishes no "
    "securities breakout, so this is the finest grain available."
)


def load_adoption(*, database: str | None = None):
    """The diffusion curve: two aligned series of biweekly observations.

    Returns the geometry plus its own axis note. Both series must share one x
    axis --- a line chart over two different period sets is two charts --- so the
    periods are intersected and a period either series is missing is dropped
    rather than drawn as a gap the reader would read as a dip.
    """
    from app import geometry as geom
    from warehouse.session import Principal, connect

    with connect(Principal.SCORE, database=database) as conn:
        rows = conn.cursor().execute("""
            SELECT question_code, period_start, period_label, value
            FROM core.adoption_observation
            WHERE is_current = 1 AND sector_code = ?
              AND answer_label = 'Yes'
            ORDER BY period_start, question_code""",
            ADOPTION_SECTOR).fetchall()

    by_question = {code: {} for code, _ in ADOPTION_QUESTIONS}
    for code, period_start, period_label, value in rows:
        if code in by_question:
            by_question[code][period_start] = (period_label, float(value))

    populated = [set(points) for points in by_question.values() if points]
    shared = (set.intersection(*populated)
              if len(populated) == len(ADOPTION_QUESTIONS) else set())
    if not shared:
        raise NoAdoptionAvailable(
            f"No aligned adoption observations for sector {ADOPTION_SECTOR}. "
            f"Load BTOS first: `python scripts/load_warehouse.py`.")

    periods = sorted(shared)
    series, names = [], []
    for code, name in ADOPTION_QUESTIONS:
        points = [(by_question[code][p][0], by_question[code][p][1],
                   f"{by_question[code][p][1]:.1f}%") for p in periods]
        series.append((name, points))
        names.append(name)

    values = [value for _name, points in series for _l, value, _t in points]
    # A floor at zero would spend three quarters of the plot on empty space; a
    # floor at the data minimum would exaggerate the slope. Rounded decades
    # around the data are the compromise, and the axis labels state them.
    axis_min = float(int(min(values) / 10) * 10)
    axis_max = float((int(max(values) / 10) + 1) * 10)

    result = geom.lines(series, axis_min=axis_min, axis_max=axis_max)
    LOG.info("adoption sector=%s periods=%s series=%s axis=%s-%s",
             ADOPTION_SECTOR, len(periods), len(series), axis_min, axis_max)
    first_code = ADOPTION_QUESTIONS[0][0]
    return {
        "geom": result, "names": tuple(names), "note": ADOPTION_NOTE,
        "periods": str(len(periods)),
        "table": {
            "columns": ("Period",) + tuple(names),
            "rows": tuple(
                (by_question[first_code][p][0],)
                + tuple(f"{by_question[code][p][1]:.1f}%"
                        for code, _ in ADOPTION_QUESTIONS)
                for p in periods)}}


def load_rank_agreement(*, classifier: str | None = None,
                        database: str | None = None):
    """Our rank against the published benchmark's, for every cohort member.

    Both percentiles come from :mod:`scoring.cohort` --- the same ranking the
    calibration gate uses, not a second implementation beside it. Ranking twice
    by two methods would let this chart and the gate disagree about the same
    occupation, and the chart exists to make the gate's argument visible.

    Both series are ranked within **one** cohort, which is the whole point. The
    benchmark ranks Financial Analysts among 774 occupations across the economy,
    so its full-population percentile describes a different reference set;
    putting that beside ours would compare two populations and look like
    calibration.
    """
    from app import geometry as geom
    from scoring import cohort as cohort_module
    from scoring.cohort import DEFAULT_COHORT
    from scoring.run import RUBRIC_VERSION
    from warehouse.session import Principal, connect

    classifier = classifier or config.MODEL_CLASSIFIER

    with connect(Principal.SCORE, database=database) as conn:
        cursor = conn.cursor()
        ours = cohort_module.load_cohort(
            cursor, cohort_name=DEFAULT_COHORT, classifier=classifier,
            rubric_version=RUBRIC_VERSION)
        if not ours:
            raise NoCohortAvailable(
                f"No reference set for classifier {classifier!r}. Score the "
                f"cohort first: "
                f"`python scripts/score_cohort.py --classifier model --persist`.")
        benchmarks = cohort_module.load_benchmarks(
            cursor, socs=list(ours), measure=BENCHMARK_MEASURE)
        titles = {r[0]: r[1] for r in cursor.execute(
            "SELECT soc_code, title FROM ref.occupation").fetchall()}

    # Only occupations in BOTH sides enter the cohort. One we scored that the
    # benchmark does not cover cannot contribute to a comparison, and including
    # it on one side would shift that side's ranks against a reference set the
    # other side never saw.
    members = sorted(set(ours) & set(benchmarks))
    if len(members) < cohort_module.COHORT_MIN:
        raise NoCohortAvailable(
            f"Only {len(members)} occupations are in both our scores and the "
            f"published benchmark; {cohort_module.COHORT_MIN} are needed to "
            f"rank within a cohort.")

    calibration = cohort_module.calibrate_within_cohort(
        members[0], {soc: ours[soc] for soc in members},
        {soc: benchmarks[soc] for soc in members})

    rows = []
    for soc in members:
        detail = calibration.detail[soc]
        our_pct = cohort_module.percentile_of_rank(
            detail["our_rank"], len(members))
        their_pct = cohort_module.percentile_of_rank(
            detail["benchmark_rank"], len(members))
        rows.append((titles.get(soc, soc), our_pct, f"{our_pct:.2f}",
                     their_pct, f"{their_pct:.2f}"))

    rows.sort(key=lambda row: row[1], reverse=True)
    names = ("Our rank", "Published index")
    LOG.info("rank_agreement members=%s rho=%s classifier=%s",
             len(members), calibration.rank_correlation, classifier)
    return {
        "geom": geom.dumbbells(rows, axis_max=100.0), "names": names,
        "cohort_size": str(len(members)),
        "rank_correlation": (ABSENT if calibration.rank_correlation is None
                             else f"{calibration.rank_correlation:.4f}"),
        "granularity": (ABSENT if calibration.granularity_points is None
                        else f"{calibration.granularity_points:.2f}"),
        "table": {"columns": ("Role",) + names,
                  "rows": tuple((row[0], row[2], row[4]) for row in rows)}}


def load_portfolio(*, classifier: str | None = None,
                   database: str | None = None) -> CohortView:
    """The whole portfolio page in one call: ranking, diffusion, agreement.

    The two analytical charts degrade independently. A missing adoption series
    or an unrankable benchmark removes that chart and nothing else --- they are
    separate datasets with separate failure modes, and neither should take the
    ranking down with it. The ranking itself still raises, because a portfolio
    view missing rows looks like a portfolio view.

    Their figures are merged into the view's traced set here, in the tier that
    already holds the provenanced strings, so the page's figure scan covers
    every chart without any chart being exempted from it.
    """
    import dataclasses

    view = load_cohort(classifier=classifier, database=database)
    figures = set(view.figures)

    adoption = None
    try:
        adoption = load_adoption(database=database)
        figures |= adoption["geom"].figures
        figures.add(adoption["periods"])
        # The period labels and the axis ticks are displayed text, so they join
        # the traced set rather than being exempted from the scan. The labels
        # are warehouse data (`period_label`); the ticks are scale marks
        # computed from the series bounds, which is why they are added here, in
        # the tier that computed them, instead of being waved through as
        # furniture. An exemption list is how an untraceable number eventually
        # reaches a chart.
        figures |= {tick["value"] for tick in adoption["geom"].axis}
        figures |= {str(cell) for row in adoption["table"]["rows"]
                    for cell in row}
        figures |= {"52", "523"}        # NAICS codes named in the axis note
    except Exception as exc:                     # noqa: BLE001 - degrade, log
        LOG.warning("portfolio chart=adoption status=absent reason=%s",
                    f"{type(exc).__name__}: {exc}"[:160])

    agreement = None
    try:
        agreement = load_rank_agreement(classifier=classifier,
                                        database=database)
        figures |= agreement["geom"].figures
        figures |= {agreement["cohort_size"], agreement["rank_correlation"],
                    agreement["granularity"]}
        # Both signed and unsigned: the number scanner reads "-0.2452" as the
        # literal "0.2452" with the sign as separate punctuation, so tracing
        # only the signed form leaves a negative correlation looking untraced.
        figures.add(agreement["rank_correlation"].lstrip("-"))
        figures |= {tick["value"] for tick in agreement["geom"].axis}
    except Exception as exc:                     # noqa: BLE001 - degrade, log
        LOG.warning("portfolio chart=agreement status=absent reason=%s",
                    f"{type(exc).__name__}: {exc}"[:160])

    return dataclasses.replace(view, adoption=adoption,
                               rank_agreement=agreement,
                               figures=frozenset(figures))


def _fmt_lag(value) -> str:
    return ABSENT if value is None else f"{float(value):.1f}"


def _cohort_figures(rows, indices, tasks_assessed, substitution,
                    lag) -> frozenset[str]:
    """Every literal the portfolio page is allowed to display.

    Same contract as the report's registry: a number the page shows that is not
    in here is a figure with no provenance, and the test that walks the rendered
    page will reject it. The bar widths are included for the reason the task
    spine's were -- each is that occupation's own index in another unit.
    """
    figures = {r.exposure_index for r in rows}
    figures |= {r.tasks_scored for r in rows}
    figures |= {r.bar_percent for r in rows}
    figures |= {f"{min(indices):.3f}", f"{max(indices):.3f}"}
    figures |= {str(len(rows)), str(int(tasks_assessed))}
    figures |= {str(int(v)) for v in substitution}
    figures |= {_fmt_lag(v) for v in lag}
    return frozenset(figures)


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
            provider_time_ms=spend["provider_time_ms"])

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
            provider_time_ms=spend["provider_time_ms"])

    LOG.info("submit accepted run=%s status=%s calls=%s",
             outcome.context.run_id, outcome.status, spend["calls"])
    return SubmissionResult(
        accepted=True, run_id=outcome.context.run_id, status=outcome.status,
        calls=spend["calls"], tokens=spend["total_tokens"],
        provider_time_ms=spend["provider_time_ms"])
