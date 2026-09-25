"""W8: the presentation tier.

Two acceptance criteria carry the weight, and both are enforced structurally
rather than by inspection:

* **No database access from the presentation tier.**
  ``test_the_ui_module_cannot_reach_the_database`` parses
  ``app/streamlit_app.py`` with ``ast`` and fails if it imports a database
  library or contains SQL. Adding the coupling requires deleting the test.
* **Renders no figure it did not receive.**
  ``test_the_ui_displays_no_figure_the_view_model_did_not_carry`` walks every
  block on the page, extracts every numeric literal, and asserts each one came
  from the view model --- which in turn only carries literals the report's
  figure registry produced, and the registry refuses a figure without
  provenance.

Presentation logic is tested through :mod:`app.blocks`, which is pure data, so
these tests need no browser, no server and no Streamlit process.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import blocks as blocks_module
from app.blocks import Block, displayed_strings, page
from app.view_model import (ClaimView, ReportView, SourceView, StandingView,
                            TaskRowView)
from nodes.figure_guard import _numbers_in
from report.provenance import _is_furniture

UI_MODULE = Path("src/app/streamlit_app.py")
GATEWAY_MODULE = Path("src/app/gateway.py")
BLOCKS_MODULE = Path("src/app/blocks.py")
VIEW_MODULE = Path("src/app/view_model.py")

FORBIDDEN_IN_UI = ("pyodbc", "sqlalchemy", "warehouse", "warehouse.session",
                   "report.reader", "scoring", "providers")
SQL_KEYWORDS = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", " FROM ",
                "JOIN ", "WHERE ")


# ===========================================================================
# Fixtures -- a review_required view, which is what production produces
# ===========================================================================

def _view(**overrides) -> ReportView:
    base = dict(
        run_id="105F0C37-ABCD-4EEE-8888-999999999999",
        status="review_required",
        soc_code="13-2051.00",
        occupation_title="Financial and Investment Analysts",
        generated_on="2026-09-22",
        standing=StandingView(
            headline="NOT YET CALIBRATED — ANALYST REVIEW REQUIRED",
            meaning="The exposure index carries no external validation.",
            tone="warn",
            reason="A percentile is a rank and one score has no rank."),
        exposure_index="0.380",
        weight_source="equal",
        weighting_note="Every task is weighted equally.",
        tasks_scored="26",
        lag_p10="5.0", lag_p50="10.1", lag_p90="30.0",
        lag_basis="Observed trajectory: 29.9% to 36.5% across 21 observations.",
        lag_grounding="claim_a, claim_b",
        curve_fitted=False,
        calibration_outcome="review_required",
        calibration_is_identifiable=False,
        benchmark_measure="AIOE_language_modeling",
        benchmark_percentile="86.82",
        our_percentile="not identifiable",
        delta="not identifiable",
        direction_augment="14", direction_substitute="0",
        direction_unclear="12",
        tasks=(TaskRowView("Create client presentations.", "0.900", "0.250",
                           "0.675", "augment", "medium"),
               TaskRowView("Develop client relationships.", "0.550", "0.550",
                           "0.247", "unclear", "medium")),
        sources=(SourceView("onet_task_statements", "O*NET tasks", "DOL",
                            "http://o.test", "tsv", "a" * 64, "task_source",
                            False),
                 SourceView("felten_aioe", "AIOE", "Felten via mirror",
                            "http://f.test", "xlsx", "b" * 64,
                            "exposure_benchmark", True)),
        claims=(ClaimView("c1", "lag_length",
                          "The implementation lag runs to years, not months.",
                          "25", "nber_j_curve"),),
        caveats=("Adoption evidence is NAICS 52 while the cost line is 523.",),
        trace_figures="164", trace_complete=True,
        trace_customer_deliverable=False, trace_detail="no break detected",
        git_sha="c" * 40, rubric_version="exposure_v1",
        calibration_policy_version="provisional_v1",
        is_customer_deliverable=False,
        figures=frozenset({"0.380", "26", "5.0", "10.1", "30.0", "86.82",
                           "14", "0", "12", "0.900", "0.250", "0.675",
                           "0.550", "0.247", "29.9%", "36.5%", "21", "25",
                           "164", "523", "52"}),
        markdown="# report\n")
    base.update(overrides)
    return ReportView(**base)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ===========================================================================
# The tier boundary, enforced structurally
# ===========================================================================

def test_the_ui_module_exists_where_the_launcher_expects_it():
    assert UI_MODULE.exists(), f"{UI_MODULE} is missing"


def test_the_ui_module_cannot_reach_the_database():
    """The acceptance criterion, as a parse of the module.

    The tiers are logical and co-located in one process, so nothing physically
    stops a UI module opening a cursor. This is what stops it.
    """
    tree = ast.parse(_source(UI_MODULE))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    offenders = [name for name in imported
                 if any(name == bad or name.startswith(bad + ".")
                        for bad in FORBIDDEN_IN_UI)]
    assert not offenders, (
        f"the presentation tier imports {offenders}; it must go through "
        f"app.gateway")


def test_the_ui_module_contains_no_sql():
    """Looks for SQL, not for English words that appear in SQL.

    The first version scanned the whole file for bare keywords and failed on a
    comment containing the word "from". That is the same defect W4 hit, where a
    structural test matched a module docstring because the prose contained
    "FROM " -- so the rule there became "require SELECT and FROM together".
    Applying it here too: real SQL lives in a string literal and names both.

    Parsed with ast so comments are out of scope entirely; a comment cannot
    execute a query.
    """
    tree = ast.parse(_source(UI_MODULE))
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    offenders = [text[:60] for text in literals
                 if "SELECT" in text.upper() and "FROM" in text.upper()]
    assert not offenders, f"SQL in the presentation tier: {offenders}"

    # And no DML verb in a literal, which needs no FROM to do damage.
    dml = [text[:60] for text in literals
           if any(verb in text.upper()
                  for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM",
                               "DROP ", "ALTER "))]
    assert not dml, f"DML in the presentation tier: {dml}"


def test_the_blocks_and_view_model_are_also_database_free():
    """Presentation logic must be renderable without a warehouse."""
    for module in (BLOCKS_MODULE, VIEW_MODULE):
        tree = ast.parse(_source(module))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        bad = [n for n in imported
               if n.startswith(("pyodbc", "sqlalchemy", "warehouse"))]
        assert not bad, f"{module.name} imports {bad}"


def test_the_gateway_is_the_only_module_that_reads_the_warehouse():
    """The facade is allowed to; it is the application tier."""
    source = _source(GATEWAY_MODULE)
    assert "warehouse.session" in source or "from warehouse" in source
    tree = ast.parse(source)
    assert any(isinstance(n, ast.FunctionDef) and n.name == "load_view"
               for n in ast.walk(tree))


def test_the_ui_does_not_score_or_call_a_model():
    """Opening the page must not be able to change a number."""
    source = _source(UI_MODULE)
    for banned in ("build_verdict", "score_exposure", "compute_lag",
                   "for_stage", "structured(", "complete(", "runner.invoke"):
        assert banned not in source, (
            f"the presentation tier references {banned!r}; rendering a run "
            f"must not recompute it")


def test_rendering_a_run_does_not_recompute_it():
    """Scoped to load_view, which is the path that renders.

    This test used to forbid the whole gateway module from naming
    runner.invoke. That premise expired: TDD 1.1 draws a typed request from the
    presentation tier into orchestration, so submit() must invoke the graph.
    What still has to hold is the original intent -- opening a page and
    rendering a persisted run cannot recompute it -- so the assertion now
    covers load_view's body rather than the file.
    """
    source = _source(GATEWAY_MODULE)
    start = source.index("def load_view")
    end = source.index("def _standing")
    body = source[start:end]

    for banned in ("build_verdict", "runner.invoke", "graph_runner.invoke",
                   "for_stage", "persist_verdict", "open_run", "close_run"):
        assert banned not in body, (
            f"load_view references {banned!r}; rendering a persisted run must "
            f"not recompute it")


def test_scoring_is_confined_to_submit():
    """Only the explicit request path may invoke orchestration."""
    source = _source(GATEWAY_MODULE)
    start = source.index("def submit")
    assert "graph_runner.invoke" in source[start:], (
        "submit() is the request half of the tier contract and must invoke "
        "the graph")


# ===========================================================================
# Renders no figure it did not receive
# ===========================================================================

def _identifier_like(text: str) -> bool:
    """Whether a displayed string is an identifier rather than a finding."""
    view = _view()
    for token in (view.run_id, view.run_id[:8], view.git_sha, view.git_sha[:12],
                  "a" * 16, "b" * 16, view.rubric_version,
                  view.calibration_policy_version, view.benchmark_measure):
        if token and token in text:
            return True
    return False


def test_the_ui_displays_no_figure_the_view_model_did_not_carry():
    """The second acceptance criterion.

    Every numeric literal on the page must have come from the view model. The
    view model carries only literals the report's figure registry produced, and
    the registry refuses to produce a figure without a source document --- so
    this closes the chain from a hashed artefact to a pixel.
    """
    view = _view()
    strings = displayed_strings(page(view))

    unaccounted: list[tuple[str, str]] = []
    for text in strings:
        if _identifier_like(text):
            continue
        for literal, value in _numbers_in(text):
            if literal in view.figures:
                continue
            # Reuse the report's own definition of document furniture --
            # section numbers, short counts, "SHA-256" -- rather than
            # inventing a second one that could drift from it.
            if _is_furniture(literal, value, text):
                continue
            unaccounted.append((literal, text[:70]))

    assert not unaccounted, (
        "figures displayed that the view model did not carry: "
        + "; ".join(f"{lit!r} in {ctx!r}" for lit, ctx in unaccounted[:6]))


def test_the_page_actually_displays_the_headline_figures():
    """Guards against the previous test passing because nothing is shown."""
    strings = " ".join(displayed_strings(page(_view())))
    for expected in ("0.380", "5.0", "10.1", "30.0", "26"):
        assert expected in strings, f"{expected} is not on the page"


def test_no_block_performs_arithmetic():
    """``app.blocks`` must not compute; it may only format.

    If the module could do arithmetic it could produce a figure that is on no
    source, and the test above would have nothing to catch it with.
    """
    tree = ast.parse(_source(BLOCKS_MODULE))
    offenders = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, (ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                                 ast.Pow, ast.Mod))
    ]
    assert not offenders, (
        f"{len(offenders)} arithmetic operation(s) in app/blocks.py; the "
        f"presentation layer must format, never compute")


# ===========================================================================
# Standing leads, and says why
# ===========================================================================

def test_the_standing_is_the_first_thing_after_the_header():
    page_blocks = page(_view())
    kinds = [b.kind for b in page_blocks]
    headings = [i for i, b in enumerate(page_blocks) if b.kind == "heading"]
    assert page_blocks[headings[0]].payload.startswith("1. Standing")

    standing_index = headings[0]
    exposure_index = next(i for i, b in enumerate(page_blocks)
                          if b.kind == "heading"
                          and b.payload.startswith("2. Exposure"))
    assert standing_index < exposure_index
    assert "title" in kinds


def test_the_standing_callout_carries_the_tone():
    for status, tone, renderer in (("passed", "ok", "success"),
                                   ("review_required", "warn", "warning"),
                                   ("gate_rejected", "stop", "error")):
        view = _view(standing=StandingView("H", "M", tone))
        callouts = [b for b in page(view) if b.kind == "callout"]
        assert callouts
        assert callouts[0].meta["tone"] == tone
        from app.streamlit_app import TONE_RENDERER
        assert TONE_RENDERER[tone] == renderer


def test_an_uncalibrated_run_explains_why_on_the_page():
    strings = " ".join(displayed_strings(page(_view())))
    assert "NOT YET CALIBRATED" in strings
    assert "rank" in strings


def test_an_unidentifiable_percentile_is_never_shown_as_a_number():
    """The W7 defect, guarded at the UI boundary too."""
    view = _view()
    strings = " ".join(displayed_strings(page(view)))

    assert "not identifiable" in strings
    # No metric may present our percentile as 0.
    metrics = [m for b in page(view) if b.kind == "metrics" for m in b.payload]
    ours = [m for m in metrics if "Our percentile" in m["label"]]
    assert not ours, "an unidentifiable percentile was rendered as a metric"


def test_an_identifiable_run_does_show_the_delta():
    view = _view(calibration_is_identifiable=True, our_percentile="80.00",
                 delta="-6.82", status="passed",
                 figures=frozenset({"80.00", "6.82", "86.82"}))
    metrics = [m for b in page(view) if b.kind == "metrics" for m in b.payload]
    labels = {m["label"] for m in metrics}
    assert "Our percentile" in labels and "Delta" in labels


# ===========================================================================
# Exposure and lag stay separate
# ===========================================================================

def test_exposure_and_lag_are_separate_sections_in_the_ui():
    headings = [b.payload for b in page(_view()) if b.kind == "heading"]
    assert any(h.startswith("2. Exposure") for h in headings)
    assert any(h.startswith("3. Adoption lag") for h in headings)


def test_the_ui_states_that_exposure_is_not_a_timetable():
    strings = " ".join(displayed_strings(page(_view())))
    assert "not** a timetable" in strings or "not a timetable" in strings
    assert "independently of the exposure index" in strings


def test_the_ui_emits_no_combined_risk_score():
    strings = " ".join(displayed_strings(page(_view()))).lower()
    for banned in ("risk score", "combined score", "overall risk"):
        assert banned not in strings


def test_the_lag_says_no_curve_is_fitted():
    strings = " ".join(displayed_strings(page(_view())))
    assert "No curve is fitted" in strings


# ===========================================================================
# Provenance panel, mirrors, caveats
# ===========================================================================

def test_the_provenance_panel_lists_every_source_with_its_digest():
    view = _view()
    tables = [b.payload for b in page(view) if b.kind == "table"]
    flat = " ".join(str(t) for t in tables)
    for source in view.sources:
        assert source.doc_id in flat
        assert source.sha256[:16] in flat


def test_an_unverified_mirror_is_flagged_in_the_ui():
    """Acceptance criterion 8.3."""
    strings = " ".join(displayed_strings(page(_view())))
    assert "Unverified mirror" in strings
    assert "felten_aioe" in strings
    assert "Spot-check" in strings


def test_a_run_with_no_mirror_shows_no_mirror_warning():
    clean = SourceView("onet", "t", "p", "u", "tsv", "a" * 64, "task_source",
                       False)
    strings = " ".join(displayed_strings(page(_view(sources=(clean,)))))
    assert "Unverified mirror" not in strings


def test_every_claim_shows_its_verbatim_quote_and_page():
    """Acceptance criterion 8.2: quote + page visible per claim."""
    view = _view()
    strings = " ".join(displayed_strings(page(view)))
    for claim in view.claims:
        assert claim.quote in strings
        assert claim.page in strings
        assert claim.topic in strings


def test_the_claim_panel_states_its_binding_granularity():
    strings = " ".join(displayed_strings(page(_view())))
    assert "Binding granularity" in strings


def test_every_caveat_reaches_the_page():
    view = _view(caveats=("First caveat here.", "Second caveat here."))
    strings = " ".join(displayed_strings(page(view)))
    for caveat in view.caveats:
        assert caveat in strings


def test_an_incomplete_chain_is_surfaced_as_a_stop():
    view = _view(trace_complete=False, trace_detail="two unregistered figures")
    callouts = [b for b in page(view) if b.kind == "callout"]
    stops = [b for b in callouts if b.meta.get("tone") == "stop"]
    assert stops, "an incomplete provenance chain must be a stop-level callout"
    assert "two unregistered figures" in stops[0].payload


def test_the_report_is_downloadable():
    downloads = [b for b in page(_view()) if b.kind == "download"]
    assert len(downloads) == 1
    assert downloads[0].payload.startswith("# report")
    assert downloads[0].meta["file_name"].endswith(".md")


# ===========================================================================
# Block plumbing
# ===========================================================================

def test_an_unknown_block_kind_is_refused_at_construction():
    with pytest.raises(ValueError, match="unknown block kind"):
        Block(kind="marquee", payload="no")


def test_every_kind_the_blocks_module_emits_has_a_renderer():
    """A block kind with no renderer would be silently dropped.

    Checked by reading the dispatcher's source rather than executing it, so
    the test needs no Streamlit process.
    """
    emitted = {b.kind for b in page(_view())}
    dispatcher = _source(UI_MODULE)
    missing = [kind for kind in emitted if f'== "{kind}"' not in dispatcher]
    assert not missing, f"no renderer for block kinds: {missing}"


def test_the_declared_kinds_cover_everything_emitted():
    emitted = {b.kind for b in page(_view())}
    assert emitted <= set(blocks_module.KINDS)


def test_displayed_strings_recurses_into_expanders():
    """A number hidden in a collapsed panel is still on the page."""
    view = _view()
    expanders = [b for b in page(view) if b.kind == "expander"]
    assert expanders, "expected the claim panel and the lag grounding panel"
    strings = displayed_strings(page(view))
    assert view.claims[0].quote in " ".join(strings)


def test_the_page_is_deterministic_for_one_view():
    """Stateless: the same view must produce the same page."""
    view = _view()
    first = [(b.kind, str(b.payload)) for b in page(view)]
    second = [(b.kind, str(b.payload)) for b in page(view)]
    assert first == second


def test_the_ui_module_holds_no_mutable_module_state():
    """Stateless per the TDD. A module-level dict or list would be shared."""
    tree = ast.parse(_source(UI_MODULE))
    mutable: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(
                        node.value, (ast.List, ast.Dict, ast.Set)):
                    # A constant lookup table is fine; a mutable accumulator
                    # is not. Distinguish by naming convention: SCREAMING_CASE
                    # is a constant by convention in this codebase.
                    if not target.id.isupper():
                        mutable.append(target.id)
    assert not mutable, f"mutable module-level state in the UI: {mutable}"


# ===========================================================================
# Degenerate views
# ===========================================================================

def test_a_view_with_no_tasks_still_renders():
    view = _view(tasks=())
    page_blocks = page(view)
    tables = [b for b in page_blocks if b.kind == "table"]
    assert tables
    assert tables[0].payload["rows"] == []


def test_a_view_with_no_claims_omits_the_claim_panel():
    view = _view(claims=())
    strings = " ".join(displayed_strings(page(view)))
    assert "Claim evidence" not in strings


def test_a_view_with_no_grounding_omits_that_panel():
    view = _view(lag_grounding="")
    labels = [b.meta.get("label", "") for b in page(view)
              if b.kind == "expander"]
    assert not any("Historical grounding" in label for label in labels)


def test_zero_substitutions_is_reported_against_the_prior():
    strings = " ".join(displayed_strings(page(_view())))
    assert "No task was judged to be substituted outright" in strings
    assert "more skilled" in strings


# ===========================================================================
# Loopback binding
# ===========================================================================

def test_the_launcher_binds_loopback_by_default():
    """Acceptance criterion 8.1."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_ui", Path("scripts/run_ui.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.LOOPBACK == "127.0.0.1"
    assert module.PORT == 8501
    assert "--server.address" in _source(Path("scripts/run_ui.py"))


def test_a_non_loopback_host_warns_loudly():
    source = _source(Path("scripts/run_ui.py"))
    assert "WARNING" in source
    assert "no authentication" in source


# ===========================================================================
# The app executed in Streamlit's own runtime
# ===========================================================================
#
# The tests above prove the presentation logic is correct and the tier boundary
# holds, without needing Streamlit. These prove the script actually runs: that
# the blocks reach real st.* calls without raising, which a structural test
# cannot establish. They use Streamlit's AppTest harness, so no browser or
# server is involved, but they do read the production warehouse -- so they skip
# with a stated reason when no run has been scored.

@pytest.fixture(scope="module")
def executed_app():
    """Run the real app once in Streamlit's runtime."""
    pytest.importorskip("streamlit.testing.v1",
                        reason="streamlit AppTest harness unavailable")
    from streamlit.testing.v1 import AppTest

    try:
        from app.gateway import load_view
        load_view()
    except Exception as exc:                     # noqa: BLE001
        pytest.skip(f"no scored run available to render: "
                    f"{type(exc).__name__}: {exc}")

    app = AppTest.from_file(str(UI_MODULE), default_timeout=180)
    app.run()
    return app


def test_the_app_runs_without_raising(executed_app):
    """The strongest statement available without a browser."""
    assert not executed_app.exception, [
        str(e.value) for e in executed_app.exception]
    assert len(executed_app.error) == 0, [e.value for e in executed_app.error]


def test_the_app_renders_all_eight_report_sections(executed_app):
    """The eight report sections, plus the request form above them.

    Asserted by membership rather than by count: the request form adds a ninth
    subheader, and a test pinned to "exactly eight" would fail on a deliberate
    addition while saying nothing about whether the report is complete.
    """
    headings = [s.value for s in executed_app.subheader]
    for expected in ("1. Standing", "2. Exposure", "3. Adoption lag",
                     "4. Calibration", "5. Direction", "6. Per-task detail",
                     "7. Limitations", "8. Provenance"):
        assert any(h.startswith(expected) for h in headings), (
            f"{expected} did not render; got {headings}")


def test_the_app_offers_the_request_form_above_the_report(executed_app):
    """The customer's own question is the entry point, so it comes first."""
    headings = [s.value for s in executed_app.subheader]
    assert "Run a new analysis" in headings
    assert headings.index("Run a new analysis") < next(
        i for i, h in enumerate(headings) if h.startswith("1. Standing"))


def test_the_app_renders_the_headline_metrics(executed_app):
    """Metrics must actually appear, not just be constructed."""
    labels = [m.label for m in executed_app.metric]
    for expected in ("Role exposure index", "Tasks scored", "p10 (years)",
                     "p50 (years)", "p90 (years)", "Figures traced"):
        assert expected in labels, f"{expected} metric missing from {labels}"


def test_the_app_renders_the_tables(executed_app):
    """Per-task table and provenance table, at minimum."""
    assert len(executed_app.dataframe) >= 2


def test_the_app_warns_rather_than_errors_on_an_uncalibrated_run(executed_app):
    """review_required is a warning, not an error: the analysis still stands."""
    warnings = " ".join(w.value for w in executed_app.warning)
    assert warnings, "an uncalibrated run should raise a visible warning"
    assert "NOT YET CALIBRATED" in warnings or "mirror" in warnings.lower()
    assert len(executed_app.error) == 0


def test_the_app_does_not_render_our_percentile_when_unidentifiable(
        executed_app):
    """The W7 defect, checked against the live rendered page."""
    from app.gateway import load_view

    view = load_view()
    if view.calibration_is_identifiable:
        pytest.skip("this run calibrated; the unidentifiable path is not live")
    labels = [m.label for m in executed_app.metric]
    assert "Our percentile" not in labels
    assert "Delta" not in labels


# ===========================================================================
# The request half of the tier contract (TDD 1.1)
# ===========================================================================
#
# The architecture draws "typed request / RoleVerdict response" between the
# presentation and orchestration tiers. Only the response direction existed:
# the UI rendered persisted runs and a CLI script drove the graph, so the
# presentation tier could not initiate anything. These cover the missing half
# and, more importantly, that adding it did not breach the boundary it crosses.

def test_a_request_carries_a_question_not_a_soc_code():
    """The UI must not pre-resolve scope.

    If the request could name the occupation, the Intent & Scope node's
    verification against the published catalogue would be bypassed -- and a
    confident answer about the wrong role is the worst failure available here.
    """
    from app.contract import RunRequest

    assert "soc_code" not in RunRequest.model_fields
    assert "occupation" not in RunRequest.model_fields
    assert set(RunRequest.model_fields) == {"question", "is_customer_deliverable"}


@pytest.mark.parametrize("statement", [
    "SELECT * FROM core.task",
    "drop table score.run",
    "exposure; -- comment",
    "a UNION ALL b",
])
def test_a_request_refuses_a_statement(statement):
    """A request is a question. The UI has no business sending SQL."""
    from app.contract import RunRequest

    with pytest.raises(Exception):
        RunRequest(question=statement + " and what is the exposure?")


def test_a_request_refuses_an_empty_or_enormous_question():
    from app.contract import RunRequest

    with pytest.raises(Exception):
        RunRequest(question="short")
    with pytest.raises(Exception):
        RunRequest(question="x" * 5000)


def test_the_request_is_immutable_once_built():
    """A request that the UI can mutate after validation is not a contract."""
    from app.contract import RunRequest

    request = RunRequest(question="Which cost lines are exposed to agents?")
    with pytest.raises(Exception):
        request.question = "something else"


def test_a_submission_result_carries_values_not_handles():
    """The response must not let the UI reach the warehouse or a provider."""
    from app.contract import SubmissionResult

    result = SubmissionResult(accepted=True, run_id="abc", status="passed")
    for value in result.model_dump().values():
        assert value is None or isinstance(
            value, (str, int, bool, float, dict, list, tuple)), (
            f"{value!r} is not a plain value")


def test_a_refusal_is_a_first_class_outcome_not_an_exception():
    """"Not published" is a correct answer to a reasonable question."""
    from app.contract import RefusalReason, SubmissionResult

    refused = SubmissionResult(
        accepted=False,
        refusal=RefusalReason(code="out_of_scope", message="Not published.",
                              in_scope_hint=("Credit Analysts (13-2041.00)",)))

    assert not refused.produced_a_verdict
    assert refused.run_id is None
    assert refused.refusal.in_scope_hint


def test_the_ui_still_cannot_reach_the_database_after_adding_the_request_path():
    """The whole point: the new capability must not breach the boundary.

    The UI may import app.gateway and app.contract. It may not import the
    orchestration or persistence packages, which is what would make the
    presentation tier a place where reasoning or querying happens.
    """
    tree = ast.parse(_source(UI_MODULE))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    for banned in ("graph", "graph.runner", "nodes", "scoring", "providers",
                   "warehouse", "pyodbc", "report"):
        assert not any(i == banned or i.startswith(banned + ".")
                       for i in imported), (
            f"the presentation tier imports {banned}; it must go through "
            f"app.gateway")


def test_the_gateway_is_where_orchestration_is_invoked():
    """The application tier drives the graph; it is the tier that may."""
    source = _source(GATEWAY_MODULE)
    assert "graph_runner.invoke" in source or "runner.invoke" in source
    assert "def submit" in source


def test_the_request_form_renders_without_arithmetic():
    """The cost figures must arrive pre-formatted.

    blocks.py is forbidden from computing, so the run duration is a string on
    the contract rather than seconds divided in the view. Formatting it upstream
    keeps the rule intact instead of carving an exception into it.
    """
    from app.contract import RunCost
    from app.blocks import request_form_blocks

    occupations = [{"soc_code": "13-2051.00", "title": "Analysts", "tasks": 26}]
    page = request_form_blocks(occupations, "Which cost lines?", RunCost())

    kinds = [b.kind for b in page]
    assert "request_form" in kinds
    assert "callout" in kinds                      # the cost warning
    text = " ".join(displayed_strings(page))
    assert "model calls" in text
    assert "13-2051.00" in text                    # in-scope list is shown


def test_the_in_scope_list_is_shown_before_a_run_is_offered():
    """A form that mostly answers "out of scope" teaches nothing.

    A refusal still costs a model call, so the covered occupations are visible
    up front rather than discovered by paying for a rejection.
    """
    from app.contract import RunCost
    from app.blocks import request_form_blocks

    occupations = [{"soc_code": "13-2041.00", "title": "Credit Analysts",
                    "tasks": 11}]
    page = request_form_blocks(occupations, "q", RunCost())
    labels = [b.meta.get("label", "") for b in page if b.kind == "expander"]
    assert any("In scope" in label for label in labels)


def test_a_refusal_renders_as_an_answer_not_a_crash():
    from app.blocks import refusal_blocks
    from app.contract import RefusalReason

    page = refusal_blocks(RefusalReason(
        code="out_of_scope", message="Not published.",
        in_scope_hint=("Credit Analysts (13-2041.00)",)))

    tones = [b.meta.get("tone") for b in page if b.kind == "callout"]
    assert "warn" in tones, "a correct refusal is a warning, not an error"
    text = " ".join(displayed_strings(page))
    assert "Credit Analysts" in text


def test_every_block_kind_the_form_emits_has_a_renderer():
    from app.contract import RunCost
    from app.blocks import request_form_blocks, refusal_blocks
    from app.contract import RefusalReason

    emitted = {b.kind for b in request_form_blocks(
        [{"soc_code": "x", "title": "y", "tasks": 1}], "q", RunCost())}
    emitted |= {b.kind for b in refusal_blocks(
        RefusalReason(code="c", message="m"))}

    dispatcher = _source(UI_MODULE)
    missing = [k for k in emitted if f'== "{k}"' not in dispatcher]
    assert not missing, f"no renderer for: {missing}"
