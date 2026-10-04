"""W14 — interaction and accessibility for the dashboard charts.

The spec's acceptance criteria: a table view behind every chart, a legend on both
two-series charts, dark-mode steps under both scopes, reduced motion respected,
texture available for forced-colors and print.

Two constraints shaped the implementation, and both are worth stating because
they are not obvious:

**``st.html`` does not execute JavaScript.** So the crosshair is CSS alone --- one
invisible hit band per period revealing a sibling rule. No script, and it keeps
working under a content policy that blocks one.

**The page is pinned light** by ``.streamlit/config.toml``, deliberately: it reads
as an institutional paper. The dark steps therefore exist so the charts do not
break if the surface ever changes, not because a toggle ships today. They are
validated against the dark surface rather than flipped from the light pair,
because the light hues fail the dark band.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app import blocks as blocks_module
from app import charts, document, gateway, geometry
from app.style import STYLESHEET

pytest.importorskip("pyodbc")

CHARTS_SOURCE = Path("src/app/charts.py")
POINTS = (("2025-06", 29.9, "29.9%"), ("2025-12", 33.2, "33.2%"),
          ("2026-04", 36.5, "36.5%"))
EXPECTED = (("2025-06", 31.8, "31.8%"), ("2025-12", 30.7, "30.7%"),
            ("2026-04", 43.8, "43.8%"))


@pytest.fixture(scope="module")
def portfolio():
    try:
        return gateway.load_portfolio(classifier="gpt-6-astra")
    except Exception as exc:                     # noqa: BLE001 - stated skip
        pytest.skip(f"no portfolio data: {type(exc).__name__}: {exc}")


@pytest.fixture(scope="module")
def markup(portfolio) -> str:
    return document.compose(blocks_module.portfolio_blocks(portfolio))


def _lines():
    return geometry.lines([("Using AI now", POINTS),
                           ("Expect to within six months", EXPECTED)],
                          axis_min=20.0, axis_max=50.0)


# ===========================================================================
# The crosshair, without JavaScript
# ===========================================================================

def test_the_crosshair_needs_no_javascript():
    """``st.html`` executes none, so a script-based crosshair would be dead code.

    Asserted on the rendered markup rather than the source: an inline handler
    attribute would pass a source-level import check and still be inert.
    """
    rendered = charts.line_series(_lines(), label="l",
                                  names=("a", "b"))
    assert "<script" not in rendered
    for handler in ("onmousemove=", "onmouseover=", "onclick=", "onload="):
        assert handler not in rendered, f"{handler} cannot fire in st.html"


def test_one_hit_band_per_period_with_a_sibling_rule():
    result = _lines()
    rendered = charts.line_series(result, label="l", names=("a", "b"))
    periods = len(result.marks[0]["dots"])
    assert rendered.count('class="c-slot"') == periods
    assert rendered.count('class="c-hit"') == periods
    assert rendered.count('class="c-cross"') == periods


def test_the_crosshair_is_revealed_by_hover_in_css_alone():
    assert ".chart .c-cross" in STYLESHEET
    assert "opacity: 0" in STYLESHEET
    assert ".chart .c-slot:hover .c-cross" in STYLESHEET


def test_the_readout_names_every_series_at_that_period():
    """The thing a per-mark tooltip cannot do.

    Hovering one dot tells a reader one value. The question they have at a point
    on a trend is what BOTH lines were doing, which is why the band carries a
    combined readout rather than relying on the dots' own titles.
    """
    rendered = charts.line_series(_lines(), label="l",
                                  names=("Using AI now",
                                         "Expect to within six months"))
    titles = re.findall(r"<title>([^<]*)</title>", rendered)
    combined = [t for t in titles if t.count("·") >= 1 and "—" in t]
    assert combined, "no combined readout found"
    for title in combined:
        assert "Using AI now:" in title
        assert "Expect to within six months:" in title


def test_the_hit_band_is_wider_than_a_dot():
    """Small marks are easy to under-size for hover; the band is the target."""
    result = _lines()
    assert float(result.hit_band) > 9.0, (
        f"hit band {result.hit_band} is no bigger than a marker")


def test_the_hit_band_is_computed_in_the_tier_that_may_compute():
    """The arithmetic rule stays absolute, and this is why.

    The first implementation divided the plot width by the point count inside
    ``app.charts``, and the parse test caught it on the next run. The band is a
    hit target rather than a mark --- it encodes no datum and joins no traced set
    --- but the rule does not admit exceptions, because an exception invites the
    next one.
    """
    tree = ast.parse(CHARTS_SOURCE.read_text(encoding="utf-8"))
    offenders = [n for n in ast.walk(tree)
                 if isinstance(n, ast.BinOp)
                 and isinstance(n.op, (ast.Sub, ast.Mult, ast.Div,
                                       ast.FloorDiv, ast.Pow, ast.Mod))]
    assert not offenders, f"{len(offenders)} arithmetic op(s) in charts.py"
    assert "hit_band" in geometry.ChartGeometry.__dataclass_fields__


def test_the_crosshair_carries_no_figure_into_the_traced_set():
    """A hit band is layout, and a readout only repeats values already traced."""
    result = _lines()
    assert result.hit_band not in result.figures
    supplied = {text for _x, _v, text in POINTS + EXPECTED}
    assert result.figures == supplied


# ===========================================================================
# Colour lives in CSS, so nothing drifts and dark can override
# ===========================================================================

def test_no_mark_carries_an_inline_colour(markup):
    """One token, one place to override, and the no-red rule checkable once."""
    inline = re.findall(r'(?:fill|stroke)="#[0-9A-Fa-f]{3,6}"', markup)
    assert not inline, f"inline colours in chart markup: {set(inline)}"
    assert 'style="background:' not in markup, "a legend swatch is inlined"


def test_every_mark_class_has_a_rule_behind_it(markup):
    """A class with no rule renders an invisible mark, which beats a tint badly."""
    used = set(re.findall(r'class="[^"]*?(c-ramp-\d|c-muted|c-s\d)\b', markup))
    assert used, "no mark classes found; this check would pass vacuously"
    for name in used:
        assert f".{name}" in STYLESHEET, f"{name} has no rule in the stylesheet"


def test_the_hatch_pattern_is_defined_wherever_it_is_referenced(markup):
    if "c-muted" in markup:
        assert 'id="hatch"' in markup
        assert "fill: url(#hatch)" in STYLESHEET


def test_an_end_label_does_not_wear_its_series_colour():
    """A light categorical hue is illegible as text on the surface.

    Marks carry identity; labels, values and legends stay in ink. The coloured
    mark beside the text is what identifies it.
    """
    assert ".chart .c-s0-ink" in STYLESHEET
    assert "fill: var(--ink)" in STYLESHEET
    ink_rule = STYLESHEET[STYLESHEET.index(".chart .c-s0-ink"):]
    assert "var(--series-0)" not in ink_rule[:120]


# ===========================================================================
# Dark steps: selected, validated, and under both scopes
# ===========================================================================

def test_dark_steps_are_declared_under_both_scopes():
    """The media query covers the OS setting; the attribute covers a toggle.

    The ``:not([data-theme="light"])`` guard is what lets an explicit light stamp
    beat OS-dark, which is the case this page relies on.
    """
    assert "@media (prefers-color-scheme: dark)" in STYLESHEET
    assert ':root:where(:not([data-theme="light"]))' in STYLESHEET
    assert ':root[data-theme="dark"]' in STYLESHEET


def test_the_dark_series_are_the_validated_pair_not_a_flip():
    """The light hues FAIL the dark band, so a flip would ship a failing palette.

    Dark requires OKLCH L in 0.48-0.67 with chroma at or above 0.1, and blues
    lose chroma at mid lightness --- the light pair sits outside it. These were
    re-stepped and re-validated against the dark surface.
    """
    assert charts.SERIES_DARK == ("#0E8CD6", "#BC8C1C")
    assert charts.SERIES_DARK != charts.SERIES

    # Checked INSIDE each override block, not merely present somewhere in the
    # file. The first version of this test looked for the values anywhere in the
    # stylesheet and passed when one scope was flipped back to the light pair --
    # because the light hex is in the file legitimately and the dark hex was
    # still in the other scope. A mutation run caught it.
    for scope in ('@media (prefers-color-scheme: dark)',
                  ':root[data-theme="dark"]'):
        start = STYLESHEET.index(scope)
        block = STYLESHEET[start:start + 400]
        for value in charts.SERIES_DARK:
            assert value in block, f"{value} is not set in {scope}"
        for value in charts.SERIES:
            assert value not in block, (
                f"{scope} sets the LIGHT hue {value}; the light pair fails the "
                f"dark band, so a flip ships a failing palette")


def test_each_dark_override_names_every_token_it_overrides():
    """A partial override leaves one series light against a dark surface."""
    for scope in ('@media (prefers-color-scheme: dark)',
                  ':root[data-theme="dark"]'):
        start = STYLESHEET.index(scope)
        block = STYLESHEET[start:start + 400]
        for token in ("--series-0:", "--series-1:", "--hatch-bg:",
                      "--hatch-ink:"):
            assert token in block, f"{token} is not overridden in {scope}"


def test_the_page_is_light_by_choice_and_says_so():
    """Stating it matters: an unexplained light-only page reads as an oversight."""
    config = Path(".streamlit/config.toml").read_text(encoding="utf-8")
    assert 'base = "light"' in config
    assert "deliberate choice" in config


# ===========================================================================
# The accessibility floor
# ===========================================================================

def test_every_chart_ships_a_table_view(portfolio, markup):
    """The keyboard and assistive-technology path, and the honest answer to a
    reader who wants the values rather than the shape.

    A hover layer serves a mouse. The table is what serves everyone else, which
    is why it is not optional on any chart.
    """
    charts_on_page = markup.count("<svg")
    assert charts_on_page >= 3
    assert markup.count('class="c-table"') == charts_on_page


def test_the_table_view_is_keyboard_reachable(markup):
    """``<details>`` is focusable and operable without a pointer."""
    assert markup.count("<details class=\"c-table\"") == markup.count(
        'class="c-table"')
    assert "<summary>" in markup


def test_both_two_series_charts_carry_a_legend(markup):
    """Identity never rests on colour alone."""
    assert markup.count('class="c-legend"') == 2


def test_every_chart_has_an_accessible_name(markup):
    names = re.findall(r'<svg class="chart[^"]*" role="img" aria-label="([^"]+)"',
                       markup)
    assert len(names) == markup.count("<svg")
    assert all(name.strip() for name in names)
    assert len(set(names)) == len(names), "two charts share one accessible name"


def test_reduced_motion_is_respected():
    """The hover transitions on bars and dots must not fire for a reader who
    has asked for less motion."""
    assert "@media (prefers-reduced-motion: reduce)" in STYLESHEET
    block = STYLESHEET[STYLESHEET.index("prefers-reduced-motion"):]
    assert "transition: none !important" in block[:200]
    # And there is motion to suppress, or the rule is decoration.
    assert "transition: opacity" in STYLESHEET


def test_forced_colors_keeps_identity_without_author_fills():
    """Forced colors strips fills, so texture and outlines carry identity."""
    assert "@media (forced-colors: active)" in STYLESHEET
    block = STYLESHEET[STYLESHEET.index("forced-colors: active"):]
    assert "stroke: CanvasText" in block[:400]
    assert "stroke-dasharray" in block[:400], (
        "the unopenable rows need a texture that survives forced colors")


def test_print_opens_the_tables_and_drops_the_hover_layer():
    """A printed page must not be missing its numbers, and a crosshair cannot
    work on paper."""
    assert "@media print" in STYLESHEET
    block = STYLESHEET[STYLESHEET.rindex("@media print"):]
    assert "details.c-table" in block
    assert ".c-cross" in block and "display: none" in block


def test_focus_is_visible():
    assert "*:focus-visible" in STYLESHEET
    assert "outline:" in STYLESHEET


# ===========================================================================
# Executed in Streamlit's runtime
# ===========================================================================

@pytest.fixture(scope="module")
def executed_app():
    pytest.importorskip("streamlit.testing.v1",
                        reason="streamlit AppTest harness unavailable")
    from streamlit.testing.v1 import AppTest

    try:
        gateway.load_portfolio()
    except Exception as exc:                     # noqa: BLE001 - stated skip
        pytest.skip(f"no portfolio to render: {type(exc).__name__}: {exc}")

    app = AppTest.from_file("src/app/streamlit_app.py", default_timeout=240)
    app.run()
    return app


def test_the_rendered_page_carries_the_interaction_layer(executed_app):
    assert not executed_app.exception, [
        str(e.value) for e in executed_app.exception]
    body = " ".join(e.proto.body for e in executed_app.get("html"))
    assert 'class="c-slot"' in body, "the crosshair did not reach the page"
    assert body.count('class="c-table"') == body.count("<svg")
    assert body.count('class="c-legend"') == 2


def test_the_stylesheet_reaches_the_page_with_its_tokens(executed_app):
    """A token with no stylesheet is an invisible chart."""
    emitted = " ".join(m.value for m in executed_app.markdown)
    for token in ("--series-0:", "--ramp-0:", ".c-cross"):
        assert token in emitted, f"{token} did not reach the page"
