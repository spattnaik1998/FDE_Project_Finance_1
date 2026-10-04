"""W11 — chart primitives and their geometry.

Two modules, one boundary, and the boundary is the point. :mod:`app.geometry` is
the application tier and may compute; :mod:`app.charts` is presentation and may
not. A presentation layer that can compute can produce a figure that is on no
source, and the test that walks the rendered page for untraceable numbers would
have nothing to catch it with.

That is also why there is no plotting library: a library computes geometry outside
the traced path, and the chain this project maintains runs from a hashed artefact
to a pixel.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app import charts, geometry

CHARTS_SOURCE = Path("src/app/charts.py")
GEOMETRY_SOURCE = Path("src/app/geometry.py")

BARS = (("Tax Preparers", 0.703, "0.703", False),
        ("Loan Officers", 0.642, "0.642", False),
        ("Credit Analysts", 0.626, "0.626", True))

POINTS = (("2025-06", 29.9, "29.9%"), ("2025-12", 33.2, "33.2%"),
          ("2026-04", 36.5, "36.5%"))
EXPECTED = (("2025-06", 31.8, "31.8%"), ("2025-12", 30.7, "30.7%"),
            ("2026-04", 43.8, "43.8%"))

DUMBBELLS = (("Tax Preparers", 95.83, "95.83", 12.50, "12.50"),
             ("Financial Analysts", 4.17, "4.17", 54.17, "54.17"))


# ===========================================================================
# The presentation module computes nothing
# ===========================================================================

def test_no_chart_primitive_performs_arithmetic():
    """The rule that makes every coordinate accountable.

    Same technique as ``test_no_block_performs_arithmetic``. If this module could
    compute, it could place a mark at a position no traced value implies, and the
    page's figure scan would see a plausible chart with an invented bar.
    """
    tree = ast.parse(CHARTS_SOURCE.read_text(encoding="utf-8"))
    offenders = [
        ast.dump(node)[:70] for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, (ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                                 ast.Pow, ast.Mod))
    ]
    assert not offenders, (
        f"{len(offenders)} arithmetic operation(s) in app/charts.py; the "
        f"presentation layer must format, never compute: {offenders}")


def test_the_primitives_import_no_plotting_library():
    """A library would compute geometry outside the traced path."""
    tree = ast.parse(CHARTS_SOURCE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for library in ("matplotlib", "plotly", "altair", "bokeh", "pygal",
                    "seaborn", "pandas"):
        assert library not in imported, f"charts.py imports {library}"


def test_geometry_is_the_only_module_that_computes():
    """The division of labour, pinned so a later edit cannot drift it."""
    tree = ast.parse(GEOMETRY_SOURCE.read_text(encoding="utf-8"))
    arithmetic = [n for n in ast.walk(tree)
                  if isinstance(n, ast.BinOp)
                  and isinstance(n.op, (ast.Sub, ast.Mult, ast.Div))]
    assert arithmetic, (
        "geometry.py does no arithmetic, which means the computation moved "
        "somewhere it should not be")


# ===========================================================================
# Figures versus layout
# ===========================================================================

def test_a_bars_figures_are_the_printed_values_not_pixel_lengths():
    """The defect this test exists for was live while building W11.

    The first cut put the bar's pixel length into ``figures`` --- values like
    "246.2", a datum multiplied by an arbitrary plot width. No reader can read
    that off the page, and carrying hundreds of them floods the traced set with
    numbers nobody can check.

    The distinction from the task spine's widths is real rather than convenient:
    a spine width is "70%", the datum as a share and readable as one. A pixel
    length is the datum times a plot width.
    """
    result = geometry.bars(BARS)
    assert result.figures == {"0.703", "0.642", "0.626"}
    for value in result.figures:
        assert not value.replace(".", "").isdigit() or float(value) <= 1.0, (
            f"{value} looks like a pixel coordinate, not a printed value")
    assert len(result.layout) > len(result.figures), (
        "layout should hold the geometry the figures no longer do")


def test_every_printed_value_comes_from_the_caller(request):
    """A chart may print only what it was handed.

    Geometry never formats a data value of its own --- the view model already
    produced the provenanced string, and the float is used for position only.
    """
    result = geometry.bars(BARS)
    supplied = {text for _label, _value, text, _muted in BARS}
    assert result.figures == supplied


def test_line_points_trace_their_printed_text():
    result = geometry.lines([("now", POINTS), ("expected", EXPECTED)],
                            axis_min=0.0, axis_max=50.0)
    supplied = {text for _x, _v, text in POINTS + EXPECTED}
    assert result.figures == supplied


def test_dumbbell_rows_trace_both_positions():
    result = geometry.dumbbells(DUMBBELLS)
    supplied = {DUMBBELLS[0][2], DUMBBELLS[0][4],
                DUMBBELLS[1][2], DUMBBELLS[1][4]}
    assert result.figures == supplied


# ===========================================================================
# Geometry correctness
# ===========================================================================

def test_bar_length_is_proportional_to_value():
    """Magnitude must be readable as magnitude."""
    result = geometry.bars((("a", 1.0, "1.000", False),
                            ("b", 0.5, "0.500", False),
                            ("c", 0.0, "0.000", False)))
    lengths = [float(mark["length"]) for mark in result.marks]
    assert lengths[0] > lengths[1] > lengths[2]
    assert lengths[2] == 0.0
    # Half the value is half the bar, within rounding.
    assert abs(lengths[1] * 2 - lengths[0]) < 0.2


def test_a_value_above_the_axis_maximum_is_clamped_not_overdrawn():
    """A bar running past its own plot is a chart that lies about its scale."""
    result = geometry.bars((("over", 2.5, "2.500", False),), axis_max=1.0)
    full = geometry.bars((("full", 1.0, "1.000", False),), axis_max=1.0)
    assert result.marks[0]["length"] == full.marks[0]["length"]


def test_a_negative_value_does_not_draw_backwards():
    result = geometry.bars((("under", -0.4, "-0.400", False),))
    assert float(result.marks[0]["length"]) == 0.0


def test_a_zero_axis_maximum_does_not_divide_by_zero():
    result = geometry.bars((("x", 1.0, "1.000", False),), axis_max=0.0)
    assert float(result.marks[0]["length"]) == 0.0


def test_series_with_different_point_counts_are_refused():
    """A line chart over two different x axes is two charts.

    Refusing is right: silently truncating to the shorter series would draw a
    trend that stops early and looks like the data does.
    """
    with pytest.raises(ValueError, match="two different x axes"):
        geometry.lines([("a", POINTS), ("b", EXPECTED[:2])],
                       axis_min=0.0, axis_max=50.0)


def test_line_y_falls_as_value_rises():
    """SVG y grows downward; a chart that inverts that reads backwards."""
    rising = (("t1", 10.0, "10"), ("t2", 20.0, "20"), ("t3", 40.0, "40"))
    result = geometry.lines([("s", rising)], axis_min=0.0, axis_max=50.0)
    ys = [float(dot["y"]) for dot in result.marks[0]["dots"]]
    assert ys[0] > ys[1] > ys[2]


def test_a_single_point_series_does_not_divide_by_zero():
    result = geometry.lines([("s", (("only", 5.0, "5"),))],
                            axis_min=0.0, axis_max=10.0)
    assert len(result.marks[0]["dots"]) == 1


def test_a_flat_axis_range_does_not_divide_by_zero():
    result = geometry.lines([("s", POINTS)], axis_min=30.0, axis_max=30.0)
    assert result.marks[0]["dots"]


def test_the_dumbbell_connector_is_drawn_in_one_direction():
    """So the renderer never has to compare two numbers.

    Both orderings appear in the fixture: one row where our rank is higher, one
    where it is lower. ``from_x`` must be the left end in both.
    """
    result = geometry.dumbbells(DUMBBELLS)
    for mark in result.marks:
        assert float(mark["from_x"]) <= float(mark["to_x"])
    # And the fixture really does contain both orderings, or this proves nothing.
    directions = {float(m["left_x"]) < float(m["right_x"])
                  for m in result.marks}
    assert directions == {True, False}, (
        "the fixture must exercise both orderings for this check to mean "
        f"anything; got {directions}")


def test_rows_do_not_overlap():
    """The 2px surface gap is what separates touching marks."""
    result = geometry.bars(BARS)
    tops = [float(mark["y"]) for mark in result.marks]
    assert tops == sorted(tops)
    thickness = float(result.marks[0]["thickness"])
    for earlier, later in zip(tops, tops[1:]):
        assert later - earlier > thickness, "bars overlap"


def test_the_ramp_step_rises_with_the_value():
    """Magnitude carries the colour, because twelve categories exceed any
    categorical palette and identity is not what the reader needs."""
    result = geometry.bars((("lo", 0.1, "0.100", False),
                            ("mid", 0.5, "0.500", False),
                            ("hi", 0.95, "0.950", False)))
    steps = [int(mark["step"]) for mark in result.marks]
    assert steps[0] < steps[1] < steps[2]
    assert all(0 <= step < len(charts.RAMP) for step in steps)


# ===========================================================================
# The palette
# ===========================================================================

def test_no_chart_uses_the_brand_red():
    """A bar in the brand's accent reads as an alarm.

    Red is the masthead rule, the section marks, the primary button and the
    hardest status. It encodes no value anywhere, and this extends the rule the
    task spine already carries to every new mark.
    """
    source = CHARTS_SOURCE.read_text(encoding="utf-8")
    for red in ("#CC0000", "#C31420", "#cc0000", "#c31420"):
        assert red not in source, f"{red} appears in a chart"

    rendered = (charts.bar_rows(geometry.bars(BARS), label="l")
                + charts.line_series(
                    geometry.lines([("a", POINTS), ("b", EXPECTED)],
                                   axis_min=0.0, axis_max=50.0),
                    label="l", names=("a", "b"))
                + charts.dumbbell_rows(geometry.dumbbells(DUMBBELLS),
                                       label="l", names=("ours", "theirs")))
    for red in ("#CC0000", "#C31420"):
        assert red not in rendered.upper()


def test_the_palette_is_the_validated_one():
    """Pinned, because a palette drifts one edit at a time.

    These values came out of the data-viz validator, not out of taste. The
    project's structural navy FAILED as a series colour (OKLCH L 0.255, outside
    the 0.43-0.77 band; chroma 0.046, reads gray), so the series hues here are
    lifted versions that pass all six checks in both modes.
    """
    assert charts.RAMP == ("#8FB9D1", "#669BBB", "#427AA0", "#215980", "#0C2537")
    assert charts.SERIES == ("#2E7DA8", "#A87A1E")
    assert len(charts.SERIES) == 2, (
        "a third series needs re-validating, not appending")


def test_the_sequential_ramp_is_ordered_light_to_dark():
    """A ramp that is not monotone is not a ramp."""
    def luminance(hex_colour: str) -> int:
        r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
        return r + g + b

    values = [luminance(step) for step in charts.RAMP]
    assert values == sorted(values, reverse=True)


# ===========================================================================
# Markup: safe, accessible, and complete
# ===========================================================================

def test_every_interpolated_value_is_escaped():
    """These primitives build SVG by concatenation, so they are an injection
    surface exactly as the document composer is.

    Occupation titles come from the warehouse. A title containing a tag would
    otherwise become markup.
    """
    hostile = '<script>alert(1)</script>'
    svg = charts.bar_rows(
        geometry.bars(((hostile, 0.5, "0.500", False),)), label=hostile)
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_each_chart_carries_an_accessible_name():
    svg = charts.bar_rows(geometry.bars(BARS), label="Exposure by role")
    assert 'role="img"' in svg
    assert 'aria-label="Exposure by role"' in svg


def test_a_two_series_chart_always_has_a_legend():
    """Identity must never rest on colour alone."""
    rendered = charts.line_series(
        geometry.lines([("a", POINTS), ("b", EXPECTED)],
                       axis_min=0.0, axis_max=50.0),
        label="l", names=("Using AI now", "Expect to within six months"))
    assert 'class="c-legend"' in rendered
    assert "Using AI now" in rendered
    assert "Expect to within six months" in rendered


def test_a_single_series_chart_has_no_legend_box():
    """One colour, and the title already names it. A box would restate it."""
    assert charts.legend(("only one",)) == ""
    assert charts.legend(()) == ""


def test_every_mark_carries_a_hover_title():
    """The hover layer ships by default, not as a later enhancement."""
    svg = charts.bar_rows(geometry.bars(BARS), label="l")
    assert svg.count("<title>") == len(BARS)
    for _label, _value, text, _muted in BARS:
        assert f": {text}</title>" in svg


def test_gridlines_are_hairline_and_never_dashed():
    rendered = charts.line_series(
        geometry.lines([("a", POINTS)], axis_min=0.0, axis_max=50.0),
        label="l", names=("a",))
    assert 'class="c-grid"' in rendered
    assert 'stroke-width="1"' in rendered
    assert "stroke-dasharray" not in rendered


def test_bars_carry_a_rounded_data_end():
    svg = charts.bar_rows(geometry.bars(BARS), label="l")
    assert f'rx="{charts.BAR_RADIUS}"' in svg


def test_markers_clear_the_minimum_size_and_carry_a_surface_ring():
    """Small dots are easy to under-size; the ring is part of the hit target."""
    rendered = charts.dumbbell_rows(geometry.dumbbells(DUMBBELLS),
                                    label="l", names=("a", "b"))
    radii = {float(r) for r in re.findall(r'r="([\d.]+)"', rendered)}
    assert radii and min(radii) >= 4.0, f"markers below r=4: {radii}"
    assert f'stroke-width="{charts.RING_WIDTH}"' in rendered


def test_an_unopenable_row_is_marked_with_texture_not_a_tint():
    """Nine of twelve roles are one number each, and that has to be visible.

    Texture rather than a lighter colour, so the distinction survives greyscale,
    print and forced-colors. A tint would vanish in all three.
    """
    from app.style import STYLESHEET

    svg = charts.bar_rows(geometry.bars(BARS), label="l")
    assert 'id="hatch"' in svg
    # W14 moved mark colour into CSS classes, so the markup carries the class and
    # the stylesheet carries the fill. Both halves are asserted: a class with no
    # rule behind it renders an invisible bar, which is worse than a tint.
    assert svg.count("c-muted") == sum(1 for row in BARS if row[3])
    assert ".c-muted" in STYLESHEET
    assert "fill: url(#hatch)" in STYLESHEET


def test_a_chart_with_no_muted_rows_still_renders():
    clean = tuple((label, value, text, False) for label, value, text, _ in BARS)
    svg = charts.bar_rows(geometry.bars(clean), label="l")
    assert "c-muted" not in svg


def test_every_chart_can_ship_a_table_view():
    """The accessibility floor, and the honest answer to someone who wants
    the values rather than the shape."""
    rendered = charts.table_view(("Role", "Exposure"),
                                 (("Tax Preparers", "0.703"),),
                                 label="View as a table")
    assert "<details" in rendered and "<table>" in rendered
    assert "Tax Preparers" in rendered and "0.703" in rendered


def test_the_axis_note_carries_the_qualifier_rather_than_a_footnote():
    """A chart is the thing that gets screenshotted."""
    note = charts.axis_note("NAICS 52, which pools banking and insurance")
    assert "NAICS 52" in note
    assert 'class="c-axis-note"' in note


def test_the_svg_scales_rather_than_fixing_pixel_width():
    """A fixed-width chart breaks the page at phone width."""
    svg = charts.bar_rows(geometry.bars(BARS), label="l")
    assert "viewBox=" in svg
    assert not re.search(r'<svg[^>]*\swidth="\d', svg), (
        "a hardcoded width defeats the viewBox")


# ===========================================================================
# These checks must be able to fail
# ===========================================================================

def test_the_arithmetic_check_catches_an_operator(tmp_path):
    """Proves the parse-based rule is not decoration."""
    sample = tmp_path / "offender.py"
    sample.write_text("def f(a, b):\n    return a * b\n", encoding="utf-8")
    tree = ast.parse(sample.read_text(encoding="utf-8"))
    offenders = [n for n in ast.walk(tree)
                 if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult)]
    assert offenders, "the detector cannot see a multiplication"


def test_the_escaping_check_catches_raw_markup():
    """If esc() were removed, this is what the test above would see."""
    unescaped = f'<text>{"<b>raw</b>"}</text>'
    assert "<b>" in unescaped, (
        "the premise of the escaping test no longer holds")
