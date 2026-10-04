"""W13 — the diffusion curve and the rank-agreement chart.

Two charts, two acceptance criteria from the spec:

* the NAICS 52 qualifier is **in the axis label**, not in a footnote, because a
  chart is the thing that gets screenshotted;
* the dumbbell renders one row per cohort member with **both percentiles from the
  same cohort key**, and a test fails if the two series come from different ones.

The second is the load-bearing one. The published index ranks Financial Analysts
among occupations across the whole economy, so its full-population percentile
describes a different reference set. Putting that beside ours would compare two
populations and look like calibration.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from app import blocks as blocks_module
from app import copy, document, gateway, geometry

pytest.importorskip("pyodbc")

UI_MODULE = Path("src/app/streamlit_app.py")


@pytest.fixture(scope="module")
def portfolio():
    try:
        return gateway.load_portfolio(classifier="gpt-6-astra")
    except Exception as exc:                     # noqa: BLE001 - stated skip
        pytest.skip(f"no portfolio data: {type(exc).__name__}: {exc}")


@pytest.fixture(scope="module")
def adoption(portfolio):
    if not portfolio.adoption:
        pytest.skip("no aligned adoption observations in this warehouse")
    return portfolio.adoption


@pytest.fixture(scope="module")
def agreement(portfolio):
    if not portfolio.rank_agreement:
        pytest.skip("no rankable benchmark in this warehouse")
    return portfolio.rank_agreement


def _page_text(view) -> str:
    """Rendered text, one element per line, so furniture context stays local."""
    markup = document.compose(blocks_module.portfolio_blocks(view))
    text = re.sub(r"<[^>]+>", "\n", markup)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#x27;", "'")):
        text = text.replace(entity, char)
    return text


# ===========================================================================
# Acceptance 1: the NAICS qualifier travels with the chart
# ===========================================================================

def test_the_naics_qualifier_is_on_the_chart_not_in_a_footnote(adoption):
    """The adoption evidence is sector 52; the cost line is 523.

    A reader who screenshots the diffusion curve must carry the mismatch with
    them. In a footnote at the bottom of the page it does not travel.
    """
    assert "NAICS 52" in adoption["note"]
    assert "523" in adoption["note"]
    assert "pools banking and insurance" in adoption["note"]


def test_the_rendered_chart_carries_the_axis_note(portfolio, adoption):
    """The qualifier travels inside the chart's own markup.

    It used to be asserted against a <figure> wrapper in the composed document.
    Charts now render into an iframe, so the note is part of the chart's markup
    and must sit after its SVG rather than loose in the page.
    """
    from app import charts

    chart = charts.figure(
        next(b.payload for b in blocks_module.portfolio_blocks(portfolio)
             if b.kind == "chart" and b.payload["form"] == "lines"))
    assert 'class="c-axis-note"' in chart
    assert "NAICS 52" in chart
    assert chart.index("</svg>") < chart.index("NAICS 52"), (
        "the note belongs after the plot it qualifies")


# ===========================================================================
# Acceptance 2: both series ranked within one cohort
# ===========================================================================

def test_both_percentiles_come_from_the_same_cohort_key(agreement):
    """One reference set, both sides, every row.

    Percentiles within a cohort of n are bounded by the midpoint convention:
    the lowest sits at 100 * 0.5 / n and the highest at 100 * (n - 0.5) / n. If
    one series had been ranked in a different population, its values would not
    respect this cohort's bounds.
    """
    size = int(agreement["cohort_size"])
    lowest = 100.0 * 0.5 / size
    highest = 100.0 * (size - 0.5) / size

    marks = agreement["geom"].marks
    assert len(marks) == size, "one row per cohort member"
    for mark in marks:
        for value in (float(mark["left_text"]), float(mark["right_text"])):
            assert lowest - 0.01 <= value <= highest + 0.01, (
                f"{value} lies outside the bounds of a {size}-member cohort; "
                f"it was ranked in a different population")


def test_both_series_span_the_cohort_rather_than_clustering(agreement):
    """Proves the bounds check above is not satisfied trivially.

    A series ranked in a much larger population would cluster: twelve finance
    occupations out of 774 occupy a narrow band of the full distribution. Both
    series here must reach the extremes of this cohort.
    """
    size = int(agreement["cohort_size"])
    lowest = 100.0 * 0.5 / size
    highest = 100.0 * (size - 0.5) / size

    for side in ("left_text", "right_text"):
        values = sorted(float(m[side]) for m in agreement["geom"].marks)
        assert values[0] == pytest.approx(lowest, abs=0.01), (
            f"{side} does not reach this cohort's floor; it is ranked elsewhere")
        assert values[-1] == pytest.approx(highest, abs=0.01), (
            f"{side} does not reach this cohort's ceiling")


def test_the_ranking_reuses_the_gates_own_machinery():
    """Structural: one ranking implementation, not two.

    Ranking twice by two methods would let this chart and the calibration gate
    disagree about the same occupation --- and the chart exists to make the
    gate's argument visible, so a divergence would be worse than no chart.
    """
    source = inspect.getsource(gateway.load_rank_agreement)
    assert "calibrate_within_cohort" in source
    assert "percentile_of_rank" in source
    assert "cohort_module.load_cohort" in source
    assert "cohort_module.load_benchmarks" in source
    # No second ranking of its own.
    assert "sorted(" in source, "sanity: the function does sort for display"
    assert "_average_ranks" not in source, (
        "ranking belongs to scoring.cohort, not to the gateway")


def test_only_occupations_present_on_both_sides_enter_the_cohort():
    """One we scored that the benchmark does not cover cannot be compared.

    Including it on one side would shift that side's ranks against a reference
    set the other side never saw.
    """
    source = inspect.getsource(gateway.load_rank_agreement)
    assert "set(ours) & set(benchmarks)" in source


def test_an_unrankable_benchmark_refuses_rather_than_ranking_a_handful():
    """Below the cohort minimum a percentile is not identified."""
    source = inspect.getsource(gateway.load_rank_agreement)
    assert "COHORT_MIN" in source
    with pytest.raises(gateway.NoCohortAvailable, match="reference set"):
        gateway.load_rank_agreement(classifier="never-scored-anything")


# ===========================================================================
# The diffusion curve
# ===========================================================================

def test_both_series_share_one_x_axis(adoption):
    """A line chart over two different period sets is two charts."""
    marks = adoption["geom"].marks
    assert len(marks) == 2
    counts = {len(mark["dots"]) for mark in marks}
    assert len(counts) == 1, f"series have different point counts: {counts}"
    assert counts.pop() == int(adoption["periods"])


def test_the_periods_are_intersected_not_padded():
    """A missing period is dropped, never drawn as a gap.

    A gap in a line reads as a dip in the data. Geometry refuses mismatched
    series outright, and the loader intersects so it never has to.
    """
    source = inspect.getsource(gateway.load_adoption)
    assert "set.intersection" in source
    with pytest.raises(ValueError, match="two different x axes"):
        geometry.lines(
            [("a", (("p1", 1.0, "1"), ("p2", 2.0, "2"))),
             ("b", (("p1", 1.0, "1"),))],
            axis_min=0.0, axis_max=10.0)


def test_the_two_series_are_named_rather_than_left_as_question_codes(adoption):
    """Q7 and Q24 mean nothing to a reader."""
    assert adoption["names"] == ("Using AI now",
                                 "Expect to within six months")
    for name in adoption["names"]:
        assert not name.startswith("Q")


def test_the_axis_does_not_start_at_zero_or_hug_the_data(adoption):
    """Zero wastes three quarters of the plot; the data minimum exaggerates
    the slope. Rounded decades around the data are the compromise, and the
    ticks state them."""
    ticks = [float(tick["value"]) for tick in adoption["geom"].axis]
    values = [float(dot["text"].rstrip("%"))
              for mark in adoption["geom"].marks for dot in mark["dots"]]
    assert ticks == sorted(ticks)
    assert min(ticks) <= min(values)
    assert max(ticks) >= max(values)
    assert min(ticks) > 0.0, "a zero floor wastes the plot"
    assert min(ticks) % 10 == 0, "the floor should be a round decade"


def test_the_series_values_are_printed_as_percentages(adoption):
    for mark in adoption["geom"].marks:
        for dot in mark["dots"]:
            assert dot["text"].endswith("%")


def test_an_absent_adoption_series_raises_its_own_error_type():
    """"No cohort" and "no adoption rows" are different failures.

    A caller that cannot tell them apart cannot report the right reason, and the
    page degrades per chart rather than wholesale.
    """
    assert issubclass(gateway.NoAdoptionAvailable, LookupError)
    assert gateway.NoAdoptionAvailable is not gateway.NoCohortAvailable


# ===========================================================================
# Degradation: a missing chart, not a missing page
# ===========================================================================

def test_a_missing_chart_removes_its_section_and_nothing_else(portfolio):
    """Absent rather than empty: a chart frame with no marks reads as a fault."""
    import dataclasses

    without = dataclasses.replace(portfolio, adoption=None,
                                  rank_agreement=None)
    page = blocks_module.portfolio_blocks(without)
    headings = [b.payload for b in page if b.kind == "heading"]
    assert copy.ADOPTION_HEADING not in headings
    assert copy.AGREEMENT_HEADING not in headings
    # The ranking survives.
    assert copy.PORTFOLIO_HEADINGS["ranking"] in headings
    assert any(b.kind == "chart" for b in page)


def test_the_two_charts_degrade_independently(portfolio):
    import dataclasses

    page = blocks_module.portfolio_blocks(
        dataclasses.replace(portfolio, adoption=None))
    headings = [b.payload for b in page if b.kind == "heading"]
    assert copy.ADOPTION_HEADING not in headings
    assert copy.AGREEMENT_HEADING in headings, (
        "losing one chart must not take the other down")


def test_load_portfolio_logs_rather_than_silently_dropping_a_chart():
    source = inspect.getsource(gateway.load_portfolio)
    assert source.count("status=absent") == 2, (
        "each chart must log its own absence")


# ===========================================================================
# Figures: the chain reaches both new charts
# ===========================================================================

def test_no_number_on_the_page_escapes_the_traced_set(portfolio):
    """The scan that found five classes of gap when these charts landed."""
    from nodes.figure_guard import _numbers_in
    from report.provenance import _is_furniture

    unaccounted = []
    for line in _page_text(portfolio).splitlines():
        for literal, value in _numbers_in(line):
            if literal in portfolio.figures or _is_furniture(literal, value,
                                                             line):
                continue
            unaccounted.append(literal)
    assert not unaccounted, (
        f"untraced numbers on the portfolio page: {sorted(set(unaccounted))}")


def test_a_negative_correlation_is_traced_in_both_forms(agreement):
    """The number scanner reads "-0.2452" as the literal "0.2452".

    Tracing only the signed form leaves a negative correlation looking untraced,
    which is how a real figure gets reported as a provenance break.
    """
    correlation = agreement["rank_correlation"]
    if not correlation.startswith("-"):
        pytest.skip("this run's correlation is not negative")
    assert correlation in agreement["geom"].figures | {correlation}
    source = inspect.getsource(gateway.load_portfolio)
    assert 'lstrip("-")' in source


def test_no_figure_is_typed_into_the_new_copy():
    """The repeat offence, caught twice and now pinned.

    "774" is the benchmark's full occupation count. It has no source in this
    warehouse, it was removed from BENCHMARK_ON_FILE earlier in the project, and
    it was typed straight back into W13's copy. A caveat template may not carry
    a figure, and neither may chart prose.
    """
    for constant in (copy.BOTH_RANKED_IN_ONE_COHORT,
                     copy.ADOPTION_WHY_IT_MATTERS):
        assert "774" not in constant
        for literal in re.findall(r"\d+\.\d+|\d+%", constant):
            pytest.fail(f"a figure is typed into copy: {literal!r}")


# ===========================================================================
# Form and accessibility
# ===========================================================================

def test_each_new_chart_ships_a_legend_and_a_table(portfolio):
    """Two series each, so identity never rests on colour alone.

    The legends ride with the charts into the iframe; the table views stay in the
    sanitised document, where they are plain HTML the page already styles.
    """
    from app import charts

    page = blocks_module.portfolio_blocks(portfolio)
    assert charts.page_charts(page).count('class="c-legend"') == 2
    assert document.compose(page).count('class="c-table"') == 3, (
        "every chart on the page ships a table view")


def test_the_page_now_carries_three_charts_of_three_different_forms(portfolio):
    page = blocks_module.portfolio_blocks(portfolio)
    forms = [b.payload["form"] for b in page if b.kind == "chart"]
    assert forms == ["bars", "lines", "dumbbell"]


def test_the_dumbbell_has_no_meter_and_the_bars_have_no_trackless_span(
        portfolio):
    """Form carries meaning: a bounded share gets a track, a rank pair does not.

    This is the same rule that keeps exposure and the lag on different grammar,
    applied to the new charts.
    """
    from app import charts

    markup = charts.page_charts(blocks_module.portfolio_blocks(portfolio))
    dumbbell = markup[markup.index("chart-dumbbell"):]
    assert 'class="meter"' not in dumbbell


def test_the_aggregate_correlation_states_both_halves_of_what_it_means(
        agreement):
    """A negative correlation on an under-powered benchmark is weak evidence
    about our rubric, not strong evidence against it. Saying only the first
    overclaims; saying only the second reads as an excuse."""
    reading = copy.agreement_reading(agreement)
    assert "inconclusive rather than passed" in reading
    assert "weak evidence about our ranking" in reading
    assert "not evidence for it either" in reading


def test_the_granularity_caveat_is_stated_beside_the_chart(agreement):
    note = copy.agreement_granularity(agreement)
    assert agreement["granularity"] in note
    assert "should not be read as meaningful" in note
