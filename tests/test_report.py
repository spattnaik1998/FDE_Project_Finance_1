"""W7: the report, and the traceability walk that decides whether the
architecture achieved its purpose.

The central test here is ``test_every_figure_walks_back_to_a_hashed_artefact``.
Everything the project has built -- append-only sources, content addressing,
consumption binding, the view layer, the split scoring paths -- exists so that
a number in front of a customer can be walked back to a specific set of bytes.
This is where that claim is either demonstrated or exposed as decoration.

The negative tests matter as much as the positive one. A traceability walk that
cannot fail is worthless, so several tests break the chain deliberately and
assert the walk notices.
"""

from __future__ import annotations

import uuid

import pytest

from report import figures, provenance, reader, render
from report.figures import FigureRegistry, UntraceableFigure
from report.reader import ClaimRecord, ReportData, SourceRecord, TaskRow

SOC = "13-2051.00"
DOC = "report_fixture_doc"
DIGEST = "d" * 64


# ===========================================================================
# In-memory fixtures -- the renderer and the walk need no database
# ===========================================================================

def _source(doc_id=DOC, *, sha256=DIGEST, is_mirror=False, verified=True,
            usage=("task_source", "adoption_evidence", "exposure_benchmark",
                   "claim_evidence")):
    return SourceRecord(
        doc_id=doc_id, title="Fixture source", publisher="Fixture publisher",
        url="http://fixture.test", format="pdf", sha256=sha256,
        retrieved_at=None, is_mirror=is_mirror,
        verified_against_publisher=verified, usage_types=usage)


def _task(task_id="t1", *, raw=0.9, tacit=0.25, direction="augment",
          statement="Prepare plans of action for investment."):
    return TaskRow(task_id=task_id, statement=statement, source_doc_id=DOC,
                   exposure_raw=raw, tacitness=tacit,
                   exposure_adjusted=round(raw * (1 - tacit), 3),
                   direction=direction, confidence="medium",
                   rationale="Because.", model="fixture-model")


def _data(**overrides) -> ReportData:
    """A review_required run, which is what production currently produces."""
    base = dict(
        run_id=str(uuid.uuid4()), status="review_required", started_at=None,
        finished_at=None, git_sha="a" * 40, config_hash="b" * 64,
        rubric_version="exposure_v1",
        calibration_policy_version="provisional_v1",
        is_customer_deliverable=False,
        soc_code=SOC, occupation_title="Financial and Investment Analysts",
        exposure_index=0.541, exposure_percentile=None,
        lag_p10=5.0, lag_p50=10.1, lag_p90=30.0,
        lag_basis="Observed trajectory: 29.9% to 36.5% across 21 observations.",
        augmentation_share=0.54, weight_source="equal",
        caveats=["Adoption evidence is NAICS 52 while the cost line is 523.",
                 "The lag interval is not a fitted curve."],
        benchmark_measure="AIOE_language_modeling",
        benchmark_percentile=86.82, our_percentile=None, delta=None,
        within_tolerance=False, calibration_outcome="review_required",
        calibration_explanation="A percentile is a rank and one score has no rank.",
        tasks=[_task("t1", raw=0.9, tacit=0.0),
               _task("t2", raw=0.55, tacit=0.25, direction="unclear"),
               _task("t3", raw=0.55, tacit=0.55,
                     statement="Develop and maintain client relationships.")],
        sources=[_source()],
        claims=[ClaimRecord(
            claim_id="fixture:lag_length:25:0", topic="lag_length",
            quote="The implementation lag for a general purpose technology "
                  "runs to years, not months, and the payoff arrives in 2025.",
            page=25, source_doc_id=DOC)])
    base.update(overrides)
    return ReportData(**base)


def _rendered(data=None):
    data = data or _data()
    markdown, registry = render.render(data)
    return markdown, registry, data


# ===========================================================================
# The traceability walk -- the test the build plan calls decisive
# ===========================================================================

def test_every_figure_walks_back_to_a_hashed_artefact():
    """The whole architecture, asserted in one place.

    Every number in the rendered document must resolve to a persisted row,
    bound to a source this run consumed, whose content is identified by a
    64-character digest. A break anywhere fails the test.
    """
    markdown, registry, data = _rendered()
    trace = provenance.walk(markdown, registry, data)

    assert trace.is_complete, trace.failure_detail()
    assert trace.links, "a report with no traced figures proves nothing"
    for link in trace.links:
        assert link.digests, f"{link.figure.label} reached no digest"
        assert all(len(d) == 64 for d in link.digests)


def test_the_walk_notices_an_unregistered_figure():
    """A number added to the document by hand is caught.

    Without this the walk would only validate figures that had already opted
    in, which is the vacuous version of the test.
    """
    markdown, registry, data = _rendered()
    tampered = markdown + "\n\nExposure will reach 92.4% by 2031.\n"

    trace = provenance.walk(tampered, registry, data)

    assert not trace.is_complete
    literals = {lit for lit, _ in trace.unregistered}
    assert "92.4%" in literals
    assert "2031" in literals


def test_the_walk_notices_a_source_the_run_never_bound():
    """A figure citing an artefact this run did not consume is unsupported."""
    markdown, registry, data = _rendered()
    registry.figures.append(figures.Figure(
        value=0.77, literal="0.770", label="smuggled figure",
        origin="score.role_verdict.exposure_index",
        source_doc_ids=("never_bound_doc",)))

    trace = provenance.walk(markdown, registry, data)

    assert not trace.is_complete
    assert ("smuggled figure", "never_bound_doc") in trace.unbound


def test_the_walk_notices_a_source_without_a_digest():
    """A bound source with no usable hash is not a specific set of bytes."""
    data = _data(sources=[_source(sha256="")])
    markdown, registry = render.render(data)

    trace = provenance.walk(markdown, registry, data)

    assert not trace.is_complete
    assert DOC in trace.unhashed


def test_a_truncated_digest_is_not_accepted():
    """32 hex characters is not a SHA-256, and must not pass as one."""
    data = _data(sources=[_source(sha256="a" * 32)])
    markdown, registry = render.render(data)

    trace = provenance.walk(markdown, registry, data)

    assert not trace.is_complete
    assert DOC in trace.unhashed


def test_an_unverified_mirror_qualifies_but_does_not_break_the_chain():
    """A mirror is a caveat on the chain, not a hole in it."""
    data = _data(sources=[_source(is_mirror=True, verified=False)])
    markdown, registry = render.render(data)

    trace = provenance.walk(markdown, registry, data)

    assert trace.is_complete, trace.failure_detail()
    assert not trace.customer_deliverable
    assert DOC in trace.unverified_mirrors
    assert "mirror" in markdown.lower()


def test_no_code_span_is_purely_numeric():
    """Closes the loophole the code-span exemption would otherwise open.

    Numbers inside `code spans` are skipped by the walk, because code spans
    hold identifiers. If a bare figure could be wrapped in backticks it would
    escape the scan, so a numeric-only code span is forbidden outright.
    """
    markdown, _, _ = _rendered()
    assert provenance.numeric_code_spans(markdown) == []


def test_prose_figures_are_registered_not_exempted():
    """Numbers inside persisted prose are traced, not waved through."""
    markdown, registry, data = _rendered()

    # 29.9 and 36.5 appear only inside lag_basis.
    values = registry.values()
    assert 29.9 in values and 36.5 in values
    prose = [f for f in registry.figures if f.origin.endswith("lag_basis")]
    assert prose, "lag_basis figures were not registered"
    assert all(f.source_doc_ids for f in prose)


# ===========================================================================
# The registry refuses an unprovenanced figure at construction
# ===========================================================================

def test_a_figure_without_a_source_cannot_be_rendered():
    registry = FigureRegistry()
    with pytest.raises(UntraceableFigure, match="no source document"):
        registry.emit(0.5, label="orphan", origin="nowhere")


def test_prose_without_a_source_cannot_be_rendered():
    registry = FigureRegistry()
    with pytest.raises(UntraceableFigure):
        registry.emit_prose("A rate of 12.5% was observed.", label="orphan",
                            origin="nowhere")


def test_an_absent_value_renders_as_words_and_registers_nothing():
    """The null-vs-zero rule, at the rendering boundary.

    An unidentifiable quantity has no figure, so it must not acquire a
    provenance chain -- and must not be rendered as 0.
    """
    registry = FigureRegistry()
    assert registry.emit(None, label="ours", origin="score.calibration",
                         source_doc_ids=(DOC,)) == "not identifiable"
    assert len(registry) == 0


def test_empty_prose_registers_nothing_and_needs_no_source():
    registry = FigureRegistry()
    assert registry.emit_prose("", label="x", origin="y") == ""
    assert len(registry) == 0


# ===========================================================================
# review_required is reported, not suppressed
# ===========================================================================

def test_a_review_required_run_still_produces_a_report():
    """The state production actually reaches must yield a document.

    The TDD withholds the *automatic narrative* on review_required. It does not
    withhold the analysis from the human the run was halted for -- "halts for
    human review" presupposes something to review.
    """
    markdown, registry, data = _rendered()

    assert data.status == "review_required"
    assert "NOT YET CALIBRATED" in markdown
    assert len(markdown) > 2000
    assert provenance.walk(markdown, registry, data).is_complete


def test_the_standing_leads_the_document():
    """A reader must learn the result is uncalibrated before reading a figure."""
    markdown, _, _ = _rendered()

    standing = markdown.index("NOT YET CALIBRATED")
    index_figure = markdown.index("0.541")
    assert standing < index_figure


def test_an_unidentifiable_percentile_is_never_rendered_as_zero():
    """The defect this workstream found, asserted so it cannot return."""
    markdown, registry, data = _rendered()

    assert data.our_percentile is None
    assert "not identifiable" in markdown or "unidentifiable" in markdown
    # No figure may claim to be our percentile.
    assert not registry.by_origin("score.calibration.our_percentile")
    # And the benchmark must not be presented as a delta against nothing.
    assert "delta" not in markdown.lower().split("provenance")[0]


def test_the_reason_calibration_failed_is_explained_in_words():
    """"review_required" is jargon; the customer needs the cause."""
    markdown, _, _ = _rendered()
    lowered = markdown.lower()

    assert "rank" in lowered
    assert "single occupation" in lowered or "one score has no rank" in lowered
    assert "not in disagreement" in lowered


def test_a_gate_rejected_run_is_marked_do_not_use():
    data = _data(status="gate_rejected", calibration_outcome="gate_rejected",
                 calibration_explanation=None)
    markdown, _ = render.render(data)

    assert "DO NOT USE" in markdown
    assert "must not be used for a decision" in markdown


def test_a_passed_run_says_the_figures_may_be_used():
    data = _data(status="passed", our_percentile=80.0, delta=-6.82,
                 within_tolerance=True, calibration_outcome="pass",
                 calibration_explanation=None)
    markdown, registry = render.render(data)

    assert "CALIBRATED" in markdown
    assert "may be used as stated" in markdown
    assert provenance.walk(markdown, registry, data).is_complete


# ===========================================================================
# Exposure and lag stay separate in the document
# ===========================================================================

def test_exposure_and_lag_are_separate_sections():
    markdown, _, _ = _rendered()

    assert "## 2. Exposure" in markdown
    assert "## 3. Adoption lag" in markdown
    assert markdown.index("## 2. Exposure") < markdown.index("## 3. Adoption lag")


def test_the_report_states_that_exposure_is_not_a_timetable():
    """The charter's central distinction, said to the customer in words."""
    markdown, _, _ = _rendered()

    assert "not** a timetable" in markdown or "not a timetable" in markdown
    assert "independently of the exposure index" in markdown


def test_no_combined_risk_score_is_emitted():
    """Exposure and lag must never be multiplied into one number.

    Combining them would discard the property the architecture spent five
    workstreams protecting.
    """
    markdown, registry, data = _rendered()

    product = data.exposure_index * data.lag_p50
    assert not any(abs(f.value - product) < 1e-6 for f in registry.figures)
    for banned in ("risk score", "combined score", "overall risk"):
        assert banned not in markdown.lower()


def test_the_lag_is_reported_as_an_interval_never_a_date():
    markdown, _, _ = _rendered()

    assert "p10" in markdown and "p50" in markdown and "p90" in markdown
    assert "No curve is fitted" in markdown


# ===========================================================================
# The seven sections, the table, and the limitations
# ===========================================================================

@pytest.mark.parametrize("heading", [
    "## 1. Standing of this analysis",
    "## 2. Exposure",
    "## 3. Adoption lag",
    "## 4. Direction: augmentation or substitution",
    "## 5. Per-task detail",
    "## 6. Limitations",
    "## 7. Provenance appendix",
])
def test_all_seven_sections_are_present(heading):
    markdown, _, _ = _rendered()
    assert heading in markdown


def test_every_scored_task_appears_in_the_table():
    data = _data()
    markdown, _ = render.render(data)

    for task in data.tasks:
        head = task.statement[:40]
        assert head in markdown, f"task {task.task_id} missing from the table"


def test_the_task_table_shows_the_tacitness_discount():
    """raw, tacit and adjusted must all be visible, not just the result."""
    markdown, _, _ = _rendered()

    assert "| Task | Raw | Tacit | Adjusted | Direction | Conf. |" in markdown
    assert "0.900" in markdown and "0.413" in markdown


def test_every_persisted_caveat_reaches_the_limitations_section():
    data = _data()
    markdown, _ = render.render(data)

    limitations = markdown.split("## 6. Limitations")[1].split("## 7.")[0]
    for caveat in data.caveats:
        assert caveat[:40] in limitations


def test_the_provenance_appendix_lists_every_consumed_source():
    data = _data(sources=[_source("doc_a"), _source("doc_b", sha256="f" * 64)])
    markdown, _ = render.render(data)

    appendix = markdown.split("## 7. Provenance appendix")[1]
    assert "doc_a" in appendix and "doc_b" in appendix
    assert "d" * 16 in appendix and "f" * 16 in appendix


def test_the_run_identity_block_records_the_versions():
    """A figure is only comparable to one from a run naming the same versions."""
    markdown, _, _ = _rendered()

    for field in ("exposure_v1", "provisional_v1", "Rubric",
                  "Calibration policy", "Code version"):
        assert field in markdown


def test_the_equal_weighting_convention_is_disclosed():
    markdown, _, _ = _rendered()
    assert "weighted equally" in markdown
    assert "endogenous" in markdown


# ===========================================================================
# Direction reporting
# ===========================================================================

def test_zero_substitutions_is_reported_against_the_survey_prior():
    markdown, _, _ = _rendered()
    assert "**0 substituting**" in markdown
    assert "more skilled" in markdown


def test_an_all_unclear_run_is_labelled_the_control():
    data = _data(tasks=[_task("t1", direction="unclear"),
                        _task("t2", direction="unclear")])
    markdown, _ = render.render(data)

    assert "control, not the product" in markdown


def test_direction_counts_match_the_scored_tasks():
    data = _data()
    counts = data.direction_counts()
    assert counts["augment"] + counts["substitute"] + counts["unclear"] == len(data.tasks)


# ===========================================================================
# Degenerate inputs
# ===========================================================================

def test_a_run_with_no_tasks_renders_without_inventing_a_spread():
    data = _data(tasks=[])
    markdown, registry = render.render(data)

    assert "discriminates rather than saturating" not in markdown
    assert provenance.walk(markdown, registry, data).is_complete


def test_a_run_with_no_bound_sources_refuses_to_render_a_figure():
    """No provenance, no document. The refusal is the correct outcome."""
    data = _data(sources=[], tasks=[])
    with pytest.raises(UntraceableFigure):
        render.render(data)


def test_calibration_identifiability_is_distinct_from_tolerance():
    """Unidentifiable is not the same as 'disagrees'."""
    unidentifiable = _data(our_percentile=None, within_tolerance=False)
    disagreeing = _data(our_percentile=40.0, delta=-46.82, within_tolerance=False)

    assert not unidentifiable.calibration_is_identifiable
    assert disagreeing.calibration_is_identifiable
    assert not disagreeing.within_tolerance


# ===========================================================================
# Reading a persisted run from the warehouse
# ===========================================================================

@pytest.fixture(scope="module")
def report_db(test_database):
    """A complete persisted run, written the way the pipeline writes one."""
    from warehouse.session import Principal, connect

    run_id = str(uuid.uuid4())
    with connect(Principal.DEVELOPER, database=test_database,
                 autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.source_document WHERE doc_id = ?)
            INSERT INTO ref.source_document
                (doc_id, title, publisher, url, format, sha256, bytes,
                 retrieved_at, is_mirror, verified_against_publisher)
            VALUES (?, 'Report fixture', 'Fixture publisher', 'http://r.test',
                    'pdf', REPLICATE('d', 64), 10, SYSUTCDATETIME(), 0, 1)""",
            DOC, DOC)
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.occupation WHERE soc_code = ?)
            INSERT INTO ref.occupation (soc_code, title, domain_source,
                                        has_onet_ratings)
            VALUES (?, 'Financial and Investment Analysts', 'Analyst', 0)""",
            SOC, SOC)
        cur.execute("""INSERT INTO core.task (task_id, soc_code, statement,
                                              weight_source, source_doc_id)
                       VALUES ('r1', ?, 'Perform securities valuation.',
                               'equal', ?)""", SOC, DOC)
        cur.execute("""INSERT INTO score.run
                           (run_id, git_sha, config_hash, rubric_version,
                            calibration_policy_version, status)
                       VALUES (?, REPLICATE('a', 40), REPLICATE('b', 64),
                               'exposure_v1', 'provisional_v1',
                               'review_required')""", run_id)
        cur.execute("""INSERT INTO score.task_score
                           (run_id, task_id, source_doc_id, exposure_raw,
                            tacitness, exposure_adjusted, direction, confidence,
                            rationale, model, prompt_version)
                       VALUES (?, 'r1', ?, 0.900, 0.250, 0.675, 'augment',
                               'medium', 'Because.', 'fixture', 'v1')""",
                    run_id, DOC)
        cur.execute("""INSERT INTO score.role_verdict
                           (run_id, soc_code, exposure_index, lag_years_p10,
                            lag_years_p50, lag_years_p90, lag_basis,
                            augmentation_share, weight_source, caveats)
                       VALUES (?, ?, 0.675, 5.0, 10.1, 30.0,
                               'Observed 29.9% to 36.5%.', 1.0, 'equal',
                               'Adoption evidence is NAICS 52.')""", run_id, SOC)
        # our_percentile and delta deliberately NULL: the run is a
        # single-occupation run and the comparison is unidentifiable.
        cur.execute("""INSERT INTO score.calibration
                           (run_id, benchmark_measure, benchmark_percentile,
                            our_percentile, delta, within_tolerance, outcome,
                            explanation)
                       VALUES (?, 'AIOE_language_modeling', 86.82, NULL, NULL,
                               0, 'review_required',
                               'A percentile is a rank; one score has no rank.')""",
                    run_id)
        cur.execute("""INSERT INTO audit.run_source_binding
                           (run_id, source_doc_id, usage_type)
                       VALUES (?, ?, 'task_source')""", run_id, DOC)
        cur.execute("""INSERT INTO audit.run_source_binding
                           (run_id, source_doc_id, usage_type)
                       VALUES (?, ?, 'adoption_evidence')""", run_id, DOC)

    yield test_database, run_id

    with connect(Principal.DEVELOPER, database=test_database,
                 autocommit=True) as conn:
        cur = conn.cursor()
        for sql in ("DELETE FROM audit.run_source_binding WHERE run_id = ?",
                    "DELETE FROM score.calibration WHERE run_id = ?",
                    "DELETE FROM score.role_verdict WHERE run_id = ?",
                    "DELETE FROM score.task_score WHERE run_id = ?",
                    "DELETE FROM score.run WHERE run_id = ?"):
            cur.execute(sql, run_id)
        cur.execute("DELETE FROM core.task WHERE source_doc_id = ?", DOC)
        cur.execute("DELETE FROM ref.source_document WHERE doc_id = ?", DOC)


def test_a_persisted_run_round_trips_into_a_traceable_report(report_db):
    """End to end against the database, not fixtures in memory."""
    database, run_id = report_db
    data = reader.load_run(run_id, database=database)

    assert data.run_id.lower() == run_id.lower()
    assert data.status == "review_required"
    assert len(data.tasks) == 1
    assert len(data.sources) == 1
    assert set(data.sources[0].usage_types) == {"task_source", "adoption_evidence"}

    markdown, registry = render.render(data)
    trace = provenance.walk(markdown, registry, data)
    assert trace.is_complete, trace.failure_detail()


def test_null_percentiles_survive_the_round_trip_as_none(report_db):
    """The fix, asserted against the database rather than in memory.

    Before this workstream the columns were NOT NULL and the writer substituted
    0.0, so a run that could not calibrate came back claiming the 0th
    percentile and a delta of zero.
    """
    database, run_id = report_db
    data = reader.load_run(run_id, database=database)

    assert data.our_percentile is None
    assert data.delta is None
    assert data.benchmark_percentile == pytest.approx(86.82)
    assert not data.calibration_is_identifiable


def test_a_run_without_a_verdict_is_refused_rather_than_rendered_empty(report_db):
    database, _ = report_db
    with pytest.raises(reader.RunNotFound, match="no persisted verdict"):
        reader.load_run(str(uuid.uuid4()), database=database)


def test_latest_run_id_finds_a_run_with_a_verdict(report_db):
    database, run_id = report_db
    found = reader.latest_run_id(database=database, soc_code=SOC)
    assert found is not None
    assert found.lower() == run_id.lower()


def test_the_reader_only_reports_sources_the_run_actually_bound(report_db):
    """Binding is on consumption. An unconsumed source must not appear."""
    from warehouse.session import Principal, connect

    database, run_id = report_db
    with connect(Principal.DEVELOPER, database=database,
                 autocommit=True) as conn:
        conn.cursor().execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.source_document WHERE doc_id = 'unused_doc')
            INSERT INTO ref.source_document
                (doc_id, title, publisher, url, format, sha256, bytes,
                 retrieved_at, is_mirror, verified_against_publisher)
            VALUES ('unused_doc', 'Never consumed', 'Nobody', 'http://x.test',
                    'pdf', REPLICATE('c', 64), 1, SYSUTCDATETIME(), 0, 1)""")

    data = reader.load_run(run_id, database=database)
    assert "unused_doc" not in data.source_ids

    with connect(Principal.DEVELOPER, database=database,
                 autocommit=True) as conn:
        conn.cursor().execute(
            "DELETE FROM ref.source_document WHERE doc_id = 'unused_doc'")


# ===========================================================================
# The null-vs-zero defect, guarded at the real write path
# ===========================================================================

def test_persist_verdict_writes_null_not_zero_for_an_absent_percentile(
        test_database):
    """The regression guard for the defect W7 found.

    ``score.calibration`` had NOT NULL percentile columns, so the writer
    substituted 0.0 for an absent value. A single-occupation run therefore
    persisted "our percentile 0.00, delta 0.00" -- a score at the bottom of the
    distribution in exact agreement with a benchmark the same row records it as
    failing to match. Nothing rendered calibration until this workstream, so it
    sat latent since W2.

    This exercises the real writer, not a hand-written fixture row, because the
    coercion lived in the writer.
    """
    from warehouse.session import Principal, connect
    from scoring import run as scoring_run
    from scoring.schemas import (CalibrationOutcome, CalibrationResult,
                                 LagInterval, RoleVerdict, WeightingBound)

    context = scoring_run.new_run()
    verdict = RoleVerdict(
        soc_code=SOC, exposure_index=0.5,
        primary_weighting=WeightingBound(weight_source="equal", lower=0.5,
                                         upper=0.5, note="equal"),
        sensitivity_weighting=None,
        lag=LagInterval(p10=5.0, p50=10.0, p90=30.0, basis="Fixture basis.",
                        observation_window_years=0.9),
        augmentation_share=0.5, unclear_share=0.5,
        calibration=CalibrationResult(
            benchmark_measure="AIOE_language_modeling",
            benchmark_percentile=86.82, our_percentile=None, delta=None,
            within_tolerance=False,
            outcome=CalibrationOutcome.REVIEW_REQUIRED,
            explanation="A percentile is a rank; one score has no rank."),
        caveats=["Fixture caveat."])

    with connect(Principal.DEVELOPER, database=test_database,
                 autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.occupation WHERE soc_code = ?)
            INSERT INTO ref.occupation (soc_code, title, domain_source,
                                        has_onet_ratings)
            VALUES (?, 'Financial and Investment Analysts', 'Analyst', 0)""",
            SOC, SOC)
        scoring_run.open_run(cur, context)
        scoring_run.persist_verdict(cur, context, verdict)

        row = cur.execute("""SELECT our_percentile, delta, benchmark_percentile
                             FROM score.calibration WHERE run_id = ?""",
                          context.run_id).fetchone()
        try:
            assert row[0] is None, f"our_percentile was coerced to {row[0]}"
            assert row[1] is None, f"delta was coerced to {row[1]}"
            assert float(row[2]) == pytest.approx(86.82)
        finally:
            cur.execute("DELETE FROM score.calibration WHERE run_id = ?",
                        context.run_id)
            cur.execute("DELETE FROM score.role_verdict WHERE run_id = ?",
                        context.run_id)
            cur.execute("DELETE FROM score.run WHERE run_id = ?",
                        context.run_id)


# ===========================================================================
# Claim evidence: verbatim quote and page (build plan 7.2)
# ===========================================================================

def test_the_appendix_carries_the_verbatim_quote_and_page():
    """A prose-derived claim reaches the customer with its quote, not a gloss."""
    data = _data()
    markdown, _ = render.render(data)

    appendix = markdown.split("## 7. Provenance appendix")[1]
    assert "Claim evidence (verbatim)" in appendix
    assert "lag_length" in appendix
    assert "implementation lag for a general purpose technology" in appendix
    assert "| 25 |" in appendix


def test_the_claim_page_is_registered_as_provenance():
    """A page number is part of the trace, not decorative."""
    _, registry, _ = _rendered()
    pages = registry.by_origin("core.extracted_claim.page")
    assert pages and all(p.source_doc_ids for p in pages)


def test_the_appendix_states_its_binding_granularity():
    """Source-level binding must not be presented as claim-level.

    ``audit.run_source_binding`` records the artefact a tool returned a row
    from, not the individual quote read. Implying a finer trace than exists
    would be the subtle version of overclaiming.
    """
    markdown, _, _ = _rendered()
    assert "Binding granularity" in markdown
    assert "not which individual" in markdown


def test_a_run_with_no_claim_evidence_omits_the_section():
    data = _data(claims=[])
    markdown, _ = render.render(data)
    assert "Claim evidence (verbatim)" not in markdown


# ===========================================================================
# Truncation must not manufacture a figure
# ===========================================================================

def test_truncation_never_splits_a_number():
    """Cutting "2025" mid-token would put a bare "25" in the document.

    The walk caught this in a live run: the full quote was registered while a
    shortened one was rendered, so truncation invented a figure that was in
    the document but not in the source.
    """
    long_quote = ("Adoption climbed steadily through the period and the "
                  "measured share reached a new high in the year 2025 before "
                  "levelling off across the remaining quarters of the survey.")
    data = _data(claims=[ClaimRecord(
        claim_id="fixture:trunc:1:0", topic="adoption", quote=long_quote,
        page=7, source_doc_id=DOC)])

    markdown, registry = render.render(data)
    trace = provenance.walk(markdown, registry, data)

    assert trace.is_complete, trace.failure_detail()

    # The precise property: no fragment of a split token survives. If "25"
    # appears as a standalone token in the claim section, "2025" must be there
    # whole -- otherwise truncation manufactured it.
    section = markdown.split("Claim evidence")[1]
    import re as _re
    standalone = _re.findall(r"(?<![\d.])25(?![\d.])", section)
    assert not standalone or "2025" in section


def test_shorten_respects_word_boundaries():
    assert render._shorten("short", 88) == "short"
    out = render._shorten("adoption reached 2025 levels overall", 22)
    assert out.endswith("...")
    # The trim falls back to a whitespace boundary, so no token is halved.
    for token in out.removesuffix("...").split():
        assert "adoption reached 2025 levels overall".find(token) >= 0


def test_what_is_registered_is_what_is_rendered():
    """Every registered prose literal must actually appear in the document."""
    markdown, registry, _ = _rendered()
    body = markdown
    for figure in registry.figures:
        if figure.derivation and figure.derivation.startswith("quoted within"):
            assert figure.literal in body, (
                f"{figure.literal!r} registered from {figure.origin} but is "
                f"not in the rendered document")


# ===========================================================================
# Mirror verification: cleared by evidence, not by a flag
# ===========================================================================

def test_a_digest_match_clears_a_mirror():
    """Identical bytes against the publisher is the strongest claim available.

    Stronger than sampling values and finding they look right, and it needs no
    judgement about which values to sample.
    """
    source = _source(is_mirror=True, verified=False)
    cleared = SourceRecord(**{**source.__dict__, "verified_by_digest": True})

    assert source.needs_spot_check
    assert not cleared.needs_spot_check


def test_an_unverified_mirror_still_blocks_delivery():
    data = _data(sources=[_source(is_mirror=True, verified=False)])
    markdown, registry = render.render(data)
    trace = provenance.walk(markdown, registry, data)

    assert not trace.customer_deliverable
    assert DOC in trace.unverified_mirrors


def test_a_verified_mirror_no_longer_blocks_delivery():
    verified = SourceRecord(
        **{**_source(is_mirror=True, verified=False).__dict__,
           "verified_by_digest": True})
    data = _data(sources=[verified])
    markdown, registry = render.render(data)
    trace = provenance.walk(markdown, registry, data)

    assert trace.is_complete, trace.failure_detail()
    assert trace.customer_deliverable
    assert trace.unverified_mirrors == []


def test_a_non_mirror_never_needs_a_spot_check():
    assert not _source(is_mirror=False, verified=False).needs_spot_check


def test_the_verification_record_is_append_only_in_fact(test_database):
    """A verification that can be edited afterwards proves nothing.

    Same reason ``ref.source_document`` is immutable: if the record of the
    check is mutable, the check is not evidence.
    """
    from warehouse.session import Principal, connect

    with connect(Principal.DEVELOPER, database=test_database,
                 autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.source_document WHERE doc_id = 'ver_doc')
            INSERT INTO ref.source_document
                (doc_id, title, publisher, url, format, sha256, bytes,
                 retrieved_at, is_mirror, verified_against_publisher)
            VALUES ('ver_doc', 'Mirror fixture', 'Somebody', 'http://m.test',
                    'xlsx', REPLICATE('9', 64), 10, SYSUTCDATETIME(), 1, 0)""")
        try:
            # A passing check must name the publisher URL it checked against.
            with pytest.raises(Exception):
                cur.execute("""INSERT INTO audit.source_verification
                                   (source_doc_id, method, publisher_url,
                                    publisher_sha256, matched)
                               VALUES ('ver_doc', 'sha256_match', '',
                                       REPLICATE('9', 64), 1)""")

            # A digest that is not 64 characters is not a SHA-256.
            with pytest.raises(Exception):
                cur.execute("""INSERT INTO audit.source_verification
                                   (source_doc_id, method, publisher_url,
                                    publisher_sha256, matched)
                               VALUES ('ver_doc', 'sha256_match', 'http://p.test',
                                       'tooshort', 1)""")

            # An unrecognised method is refused.
            with pytest.raises(Exception):
                cur.execute("""INSERT INTO audit.source_verification
                                   (source_doc_id, method, publisher_url,
                                    publisher_sha256, matched)
                               VALUES ('ver_doc', 'vibes', 'http://p.test',
                                       REPLICATE('9', 64), 1)""")
        finally:
            cur.execute("DELETE FROM audit.source_verification WHERE source_doc_id='ver_doc'")
            cur.execute("DELETE FROM ref.source_document WHERE doc_id='ver_doc'")


def test_a_mismatched_verification_does_not_clear_the_mirror(test_database):
    """Recording a FAILED check must not look like clearing it.

    The reader only accepts a verification whose publisher digest equals the
    artefact's own, so a mismatch -- or a check recorded against some other
    version -- leaves the mirror blocking.
    """
    from warehouse.session import Principal, connect

    with connect(Principal.DEVELOPER, database=test_database,
                 autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.source_document WHERE doc_id = 'mis_doc')
            INSERT INTO ref.source_document
                (doc_id, title, publisher, url, format, sha256, bytes,
                 retrieved_at, is_mirror, verified_against_publisher)
            VALUES ('mis_doc', 'Mirror fixture', 'Somebody', 'http://m.test',
                    'xlsx', REPLICATE('a', 64), 10, SYSUTCDATETIME(), 1, 0)""")
        try:
            # matched = 0: the publisher's copy differed.
            cur.execute("""INSERT INTO audit.source_verification
                               (source_doc_id, method, publisher_url,
                                publisher_sha256, matched)
                           VALUES ('mis_doc', 'sha256_match', 'http://p.test',
                                   REPLICATE('b', 64), 0)""")
            row = cur.execute("""
                SELECT MAX(CASE WHEN v.matched = 1
                                 AND v.publisher_sha256 = d.sha256
                                THEN 1 ELSE 0 END)
                FROM ref.source_document d
                LEFT JOIN audit.source_verification v
                       ON v.source_doc_id = d.doc_id
                WHERE d.doc_id = 'mis_doc'
                GROUP BY d.sha256""").fetchone()
            assert row[0] == 0, "a failed check must not clear the mirror"

            # A *passing* check recorded against a different digest must also
            # not clear it: that verified some other version of the file.
            cur.execute("""INSERT INTO audit.source_verification
                               (source_doc_id, method, publisher_url,
                                publisher_sha256, matched)
                           VALUES ('mis_doc', 'sha256_match', 'http://p.test',
                                   REPLICATE('c', 64), 1)""")
            row = cur.execute("""
                SELECT MAX(CASE WHEN v.matched = 1
                                 AND v.publisher_sha256 = d.sha256
                                THEN 1 ELSE 0 END)
                FROM ref.source_document d
                LEFT JOIN audit.source_verification v
                       ON v.source_doc_id = d.doc_id
                WHERE d.doc_id = 'mis_doc'
                GROUP BY d.sha256""").fetchone()
            assert row[0] == 0, (
                "a passing check against a different digest verified a "
                "different version and must not clear this one")
        finally:
            cur.execute("DELETE FROM audit.source_verification WHERE source_doc_id='mis_doc'")
            cur.execute("DELETE FROM ref.source_document WHERE doc_id='mis_doc'")


# ===========================================================================
# The caveat path had a blanket exemption from the provenance chain
# ===========================================================================

def test_no_caveat_template_carries_a_figure():
    """The one hole the traceability walk could not see.

    ``report/render.py`` registers every number found in a caveat against the
    run's bound documents wholesale. That is defensible for a figure the run
    *computed* --- the cohort granularity, the spread ratio, a count of tasks ---
    because those are derived from those very sources. It is not defensible for a
    number typed into a Python string, and the renderer cannot tell the two apart
    from the rendered text.

    So the rule is enforced where the difference is visible: a caveat TEMPLATE
    must not contain a figure. A template is written by us, not derived from data,
    so any percentage or decimal in one is by definition unsourced.

    This was live. The workforce caveat read "more skilled workers (47.2% up,
    1.6% down), not fewer workers (12.5% up, 8.4% down)" --- four Census ABS
    figures, from a module that is registered in ``ref.source_document`` and
    carries zero rows in ``core.*``. They were attributed to O*NET, BTOS,
    Brynjolfsson and Eloundou, none of which contain them, and the walk reported
    "0 unregistered figures".

    Integer identifiers are allowed through: NAICS 52 and 523, and the SOC code,
    which the number scanner splits into "13" and "2051". Those name things rather
    than measuring them.
    """
    from nodes.figure_guard import _numbers_in
    from scoring.run import STANDING_CAVEATS

    offenders = []
    for caveat in STANDING_CAVEATS:
        for literal, _ in _numbers_in(caveat):
            # A percentage or a decimal is a measurement. A bare integer in a
            # caveat template is a code (NAICS, SOC) or a small count.
            if "%" in literal or "." in literal:
                offenders.append((literal, caveat[:60]))

    assert not offenders, (
        "caveat templates carry figures that no source in this warehouse "
        f"produces: {offenders}")


def test_a_caveat_figure_is_attributed_to_the_run_sources_not_to_nothing():
    """Guards the other direction: computed caveat figures must stay traceable.

    Removing the blanket attribution entirely would have been the wrong fix. A
    caveat that says "2 of 26 task classifications carry low confidence" is
    reporting this run's own arithmetic over its own bound sources, and it should
    trace to them. This asserts that still holds, so the test above cannot be
    satisfied by simply dropping caveats out of the registry.
    """
    _, registry = render.render(_data())
    caveat_figures = [f for f in registry.figures if "caveat" in f.label]
    assert caveat_figures, "no caveat figure was registered at all"
    for figure in caveat_figures:
        assert figure.source_doc_ids, (
            f"caveat figure {figure.literal!r} is attributed to no document")

