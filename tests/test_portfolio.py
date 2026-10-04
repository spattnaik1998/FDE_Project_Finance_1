"""W12 — the portfolio page.

The first page in this project that puts twelve occupations side by side, which
makes it the first place a reader can compare quantities that were never meant to
be compared. Most of these tests exist to stop that.

Two properties carry the weight, and both come straight from the spec's
acceptance criteria:

* **The lag appears exactly once.** It is identical across every persisted
  verdict because it is estimated from sector-level adoption evidence. A
  per-role column would invent variation that does not exist.
* **No tile shows an average across roles.** The occupations have different
  headcounts, headcount is not in the warehouse, and an unweighted mean across
  twelve of them is a confident number describing nobody.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app import blocks as blocks_module
from app import copy, document, geometry
from app.blocks import displayed_strings, portfolio_blocks
from app.view_model import CohortRowView, CohortView
from nodes.figure_guard import _numbers_in
from report.provenance import _is_furniture

UI_MODULE = Path("src/app/streamlit_app.py")
BLOCKS_SOURCE = Path("src/app/blocks.py")


def _cohort(**overrides) -> CohortView:
    """A cohort shaped like the real one: twelve rows, three of them drillable."""
    titles = ("Tax Preparers", "Loan Officers", "Insurance Underwriters",
              "Credit Analysts", "Tax Examiners", "Credit Counselors",
              "Accountants and Auditors", "Budget Analysts",
              "Personal Financial Advisors", "Financial Examiners",
              "Financial Quantitative Analysts",
              "Financial and Investment Analysts")
    values = ("0.703", "0.642", "0.627", "0.626", "0.612", "0.598",
              "0.570", "0.543", "0.501", "0.404", "0.404", "0.397")
    tasks = ("12", "30", "7", "11", "21", "23", "29", "13", "21", "17", "21", "26")
    full = {0, 1, 11}

    rows = tuple(
        CohortRowView(soc_code=f"13-20{index:02d}.00", title=title,
                      exposure_index=value, tasks_scored=task,
                      has_full_run=index in full,
                      bar_percent=f"{round(float(value) * 100)}%")
        for index, (title, value, task) in enumerate(zip(titles, values, tasks)))

    ranking = geometry.bars(
        [(r.title, float(r.exposure_index), r.exposure_index,
          not r.has_full_run) for r in rows], axis_max=1.0)

    figures = {r.exposure_index for r in rows} | {r.tasks_scored for r in rows}
    figures |= {r.bar_percent for r in rows}
    figures |= {"12", "231", "3", "0", "26", "1", "0.397", "0.703",
                "5.0", "10.1", "30.0"}
    figures |= ranking.figures

    base = dict(
        cohort_name="finance_13_2", classifier="gpt-6-astra",
        rubric_version="exposure_v1", rows=rows,
        roles_assessed="12", tasks_assessed="231",
        substitutable_count="0", substitutable_of="26", substitutable_roles="1",
        exposure_low="0.397", exposure_high="0.703",
        most_exposed_title="Tax Preparers",
        least_exposed_title="Financial and Investment Analysts",
        lag_p10="5.0", lag_p50="10.1", lag_p90="30.0",
        drillable_roles="3", figures=frozenset(figures),
        ranking_geometry=ranking)
    base.update(overrides)
    return CohortView(**base)


def _text(markup: str) -> str:
    """Rendered text content, one element per line.

    Tags become newlines rather than spaces because ``_is_furniture`` takes its
    context argument as a line: collapsing the page to one string lets a single
    furniture token anywhere excuse every number on it. That exact mistake was
    live in this suite once.
    """
    text = re.sub(r"<[^>]+>", "\n", markup)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#x27;", "'")):
        text = text.replace(entity, char)
    return text


# ===========================================================================
# The spec's two acceptance criteria
# ===========================================================================

def test_the_lag_appears_exactly_once_on_the_page():
    """The criterion, counted rather than asserted by inspection.

    Every persisted verdict carries p50 10.1 because the lag is a sector
    quantity. A reader seeing it twice would reasonably wonder which role each
    one belonged to; a reader seeing twelve would conclude it varies.
    """
    cohort = _cohort()
    text = _text(document.compose(portfolio_blocks(cohort)))

    occurrences = sum(line.count(cohort.lag_p50) for line in text.splitlines())
    assert occurrences == 1, (
        f"p50 {cohort.lag_p50} appears {occurrences} times; the lag is one "
        f"page-level figure for the whole finance function")

    for value in (cohort.lag_p10, cohort.lag_p90):
        assert sum(line.count(value) for line in text.splitlines()) == 1


def test_the_page_says_the_timetable_is_shared_rather_than_per_role():
    """Showing it once is not enough; the page has to explain why."""
    strings = " ".join(displayed_strings(portfolio_blocks(_cohort())))
    assert "one timetable for the whole finance function" in strings
    assert "does not vary between" in strings


def test_no_tile_shows_an_average_across_roles():
    """The easiest wrong number this page could produce.

    Twelve occupations of different headcount, and headcount is not in the
    warehouse. The range is offered instead, and the absence is stated.
    """
    cohort = _cohort()
    metrics = [m for b in portfolio_blocks(cohort) if b.kind == "metrics"
               for m in b.payload]
    assert metrics, "no tiles rendered; the check below would be vacuous"
    for metric in metrics:
        label = metric["label"].lower()
        for banned in ("average", "mean", "avg", "typical"):
            assert banned not in label, f"tile {metric['label']!r} is an average"

    strings = " ".join(displayed_strings(portfolio_blocks(cohort)))
    assert "no average exposure figure on this page" in strings


def test_the_nine_roles_without_a_full_run_render_marked():
    """Hatched, not merely absent from a link.

    Nine of twelve rows are one number each. Texture rather than a lighter tint,
    so the distinction survives greyscale, print and forced-colors.
    """
    cohort = _cohort()
    markup = document.compose(portfolio_blocks(cohort))
    expected = sum(1 for r in cohort.rows if not r.has_full_run)
    assert expected == 9, "the fixture must mirror the warehouse's 3-of-12"
    assert markup.count("url(#hatch)") == expected


def test_the_page_states_how_many_roles_were_examined_in_depth():
    """Said before anyone clicks a hatched row, not discovered by clicking."""
    strings = " ".join(displayed_strings(portfolio_blocks(_cohort())))
    assert "3 of 12 roles have been examined task by task" in strings


# ===========================================================================
# Figures: the chain runs to the chart
# ===========================================================================

def test_no_number_on_the_page_escapes_the_traced_set():
    """The chain from a hashed artefact to a pixel, extended to a chart."""
    cohort = _cohort()
    text = _text(document.compose(portfolio_blocks(cohort)))

    unaccounted = []
    for line in text.splitlines():
        for literal, value in _numbers_in(line):
            if literal in cohort.figures or _is_furniture(literal, value, line):
                continue
            unaccounted.append(literal)
    assert not unaccounted, (
        f"untraced numbers on the portfolio page: {sorted(set(unaccounted))}")


def test_the_figure_scan_can_see_a_charts_values():
    """``displayed_strings`` was blind to chart payloads until it was taught.

    A ``ChartGeometry`` falls through the str / list / dict branches and would
    contribute nothing --- the same blind spot that once hid the figure and span
    blocks, and then the task spine's widths. A traceability check that cannot
    see a chart is worse than none, because it reports success.
    """
    cohort = _cohort()
    strings = displayed_strings(portfolio_blocks(cohort))
    chart = next(b for b in portfolio_blocks(cohort) if b.kind == "chart")

    for mark in chart.payload["geom"].marks:
        assert mark["text"] in strings, (
            f"the chart prints {mark['text']} and the scan cannot see it")
        assert mark["label"] in strings


def test_the_figure_scan_catches_an_invented_chart_value(monkeypatch):
    """Proves the scan above is not decoration."""
    cohort = _cohort()
    poisoned = geometry.bars([("Invented role", 0.5, "73.2%", False)])
    strings = displayed_strings(
        [blocks_module._chart("bars", poisoned, label="l")])
    assert "73.2%" in strings
    assert "73.2%" not in cohort.figures


# ===========================================================================
# Structure and tier boundaries
# ===========================================================================

def test_the_page_leads_with_the_finding_then_the_chart():
    kinds = [b.kind for b in portfolio_blocks(_cohort())]
    assert kinds[0] == "masthead"
    assert kinds.index("panel") < kinds.index("chart")
    assert "metrics" in kinds


def test_sections_are_numbered_once_each():
    page = portfolio_blocks(_cohort())
    indices = [b.meta.get("index") for b in page if b.kind == "heading"]
    assert indices == sorted(indices)
    assert len(indices) == len(set(indices)), "a section number repeats"


def test_every_block_kind_the_page_emits_has_a_renderer():
    emitted = {b.kind for b in portfolio_blocks(_cohort())}
    covered = set(document.RENDERERS) | set(document.WIDGET_KINDS)
    assert not emitted - covered, f"no renderer for {sorted(emitted - covered)}"


def test_the_chart_block_carries_geometry_not_markup():
    """Blocks stay a description of what to show.

    If the block held rendered SVG, the presentation model would contain
    presentation output and the figure scan would have to parse markup to find a
    value.
    """
    chart = next(b for b in portfolio_blocks(_cohort()) if b.kind == "chart")
    assert "<svg" not in str(chart.payload.get("form", ""))
    assert hasattr(chart.payload["geom"], "marks")
    assert chart.payload["table"], "every chart ships a table view"


def test_an_unknown_chart_form_is_refused():
    """A silently skipped chart is a finding the customer never saw."""
    bad = blocks_module._chart("sunburst", geometry.bars(()), label="l")
    with pytest.raises(ValueError, match="no chart primitive"):
        document.render_block(bad)


def test_the_page_builder_performs_no_arithmetic():
    """Already enforced for blocks.py; re-asserted because W12 added to it."""
    tree = ast.parse(BLOCKS_SOURCE.read_text(encoding="utf-8"))
    offenders = [n for n in ast.walk(tree)
                 if isinstance(n, ast.BinOp)
                 and isinstance(n.op, (ast.Sub, ast.Mult, ast.Div,
                                       ast.FloorDiv, ast.Pow, ast.Mod))]
    assert not offenders, f"{len(offenders)} arithmetic operation(s) in blocks.py"


def test_the_ui_module_does_not_reach_the_warehouse_for_the_cohort():
    """The portfolio page goes through the gateway like everything else."""
    source = UI_MODULE.read_text(encoding="utf-8")
    assert "load_portfolio" in source, (
        "the page composes through one gateway call, which W13 made "
        "load_portfolio so the two analytical charts can degrade separately")
    for forbidden in ("pyodbc", "score.cohort_index", "connect("):
        assert forbidden not in source, f"the UI module references {forbidden}"


def test_an_absent_cohort_degrades_to_a_stated_reason():
    """An empty page is the failure worth avoiding."""
    source = UI_MODULE.read_text(encoding="utf-8")
    assert "NoCohortAvailable" in source
    assert "st.info" in source


# ===========================================================================
# The page is reachable
# ===========================================================================

def test_the_portfolio_is_the_default_view():
    """It answers the question the customer actually asked, in the plural."""
    source = UI_MODULE.read_text(encoding="utf-8")
    assert 'PAGES = ("Portfolio", "Role report")' in source
    assert "index=0" in source


# ===========================================================================
# Executed in Streamlit's own runtime
# ===========================================================================

@pytest.fixture(scope="module")
def executed_app():
    pytest.importorskip("streamlit.testing.v1",
                        reason="streamlit AppTest harness unavailable")
    from streamlit.testing.v1 import AppTest

    from app.gateway import load_cohort
    try:
        load_cohort()
    except Exception as exc:                     # noqa: BLE001 - stated skip
        pytest.skip(f"no cohort to render: {type(exc).__name__}: {exc}")

    app = AppTest.from_file(str(UI_MODULE), default_timeout=240)
    app.run()
    return app


def test_the_app_renders_the_portfolio_without_raising(executed_app):
    assert not executed_app.exception, [
        str(e.value) for e in executed_app.exception]
    assert len(executed_app.error) == 0, [e.value for e in executed_app.error]


def test_the_rendered_page_contains_a_chart_per_section(executed_app):
    """W13 added the diffusion curve and the rank-agreement dumbbell.

    This asserted exactly one chart and broke the moment the page grew, which is
    the right behaviour: it was a statement about a page with one chart. Counted
    as a floor now, with every chart shipping its table view, so the next
    addition does not require editing a number here.
    """
    markup = " ".join(e.proto.body for e in executed_app.get("html"))
    charts = markup.count("<svg")
    assert charts >= 3, f"expected the ranking, diffusion and agreement charts; got {charts}"
    assert 'class="chart-figure"' in markup
    assert markup.count('class="c-table"') == charts, (
        "every chart ships a table view")


def test_the_rendered_chart_marks_the_rows_that_cannot_be_opened(executed_app):
    markup = " ".join(e.proto.body for e in executed_app.get("html"))
    assert "url(#hatch)" in markup
    assert markup.count("url(#hatch)") >= 1


def test_the_view_selector_offers_both_pages(executed_app):
    radios = executed_app.get("radio")
    assert radios, "no view selector rendered"
    assert list(radios[0].options) == ["Portfolio", "Role report"]
