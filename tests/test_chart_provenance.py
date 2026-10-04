"""W15 — the second half of the traceability chain: drawn positions.

The chain had two halves and only one was checked.

**Printed values** are covered and have been since W11: the rendered-text scan
reads every ``<text>`` and ``<title>`` node and rejects a number the view model
did not carry.

**Drawn positions** were not. A renderer could place a mark at a coordinate
nothing computed and no test would notice, because a reader cannot read "101.6"
off the page and so the text scan never sees it. There are 134 such coordinate
attributes in the portfolio page's markup.

A correction to the spec while building this: it said the tag-stripping regex
*removes* SVG text, so W15 would need to extend the scan to reach it. That was
wrong. ``<text>0.703</text>`` is element content, not a tag, so the existing scan
already reads it --- verified rather than trusted. The real gap was the attributes,
and this module closes it.
"""

from __future__ import annotations

import re

import pytest

from app import blocks as blocks_module
from app import charts, document, gateway, geometry

pytest.importorskip("pyodbc")

BARS = (("Tax Preparers", 0.703, "0.703", False),
        ("Loan Officers", 0.642, "0.642", True))
POINTS = (("2025-06", 29.9, "29.9%"), ("2026-04", 36.5, "36.5%"))
EXPECTED = (("2025-06", 31.8, "31.8%"), ("2026-04", 43.8, "43.8%"))
DUMBBELLS = (("Tax Preparers", 95.83, "95.83", 12.50, "12.50"),)


@pytest.fixture(scope="module")
def page():
    try:
        view = gateway.load_portfolio(classifier="gpt-6-astra")
    except Exception as exc:                     # noqa: BLE001 - stated skip
        pytest.skip(f"no portfolio data: {type(exc).__name__}: {exc}")
    blocks = blocks_module.portfolio_blocks(view)
    return {"view": view, "blocks": blocks,
            # The page a reader receives: the chart markup that goes in the
            # iframes, plus the sanitised document around them.
            "markup": charts.page_charts(blocks) + document.compose(blocks),
            "geometries": [b.payload["geom"] for b in blocks
                           if b.kind == "chart"]}


# ===========================================================================
# Every drawn position came from a geometry
# ===========================================================================

def test_no_mark_is_drawn_at_a_coordinate_nothing_computed(page):
    """The gap this workstream exists to close."""
    unaccounted = charts.unaccounted_coordinates(page["markup"],
                                                 *page["geometries"])
    assert not unaccounted, (
        f"coordinates in the markup that no geometry produced: "
        f"{sorted(unaccounted)}")


def test_the_audit_catches_a_coordinate_from_nowhere():
    """Proves the check above is not decoration.

    Without this, ``unaccounted_coordinates`` returning an empty set would be
    indistinguishable from it looking at nothing. A rect is moved to a position
    no geometry produced, and the audit must report exactly that value.
    """
    result = geometry.bars(BARS)
    markup = charts.bar_rows(result, label="l")
    assert not charts.unaccounted_coordinates(markup, result)

    tampered = markup.replace('x="230"', 'x="987.6"', 1)
    assert tampered != markup, "the fixture did not contain the expected x"
    unaccounted = charts.unaccounted_coordinates(tampered, result)
    assert unaccounted == {"987.6"}


def test_the_audit_is_not_satisfied_by_an_empty_markup():
    """An empty string has no unaccounted coordinates, and that is not a pass.

    The test above would be vacuous if the audit simply found nothing to check,
    so this pins that real markup contains coordinates for it to check.
    """
    result = geometry.bars(BARS)
    markup = charts.bar_rows(result, label="l")
    found = re.findall(r'(?:x|y|width|height)="([\d.]+)"', markup)
    assert len(found) > 4, f"only {len(found)} coordinates to audit"
    assert charts.unaccounted_coordinates("", result) == set()


def test_the_spec_literals_are_enumerated_not_pattern_matched():
    """Adding a magic number to a primitive must be a deliberate act.

    If the audit excused anything short, or anything integral, a mark drawn at
    an invented small coordinate would pass. The allowed literals are the mark
    specs and nothing else.
    """
    assert charts.SPEC_LITERALS == frozenset(
        {"0", "1", "1.5", "2", "4", "4.5", "6", "10"})
    for invented in ("3", "7", "12", "99", "0.5"):
        assert invented not in charts.SPEC_LITERALS


def test_each_chart_form_passes_the_audit_on_its_own():
    """So a failure names the form, rather than the page."""
    bars = geometry.bars(BARS)
    assert not charts.unaccounted_coordinates(
        charts.bar_rows(bars, label="l"), bars)

    lines = geometry.lines([("a", POINTS), ("b", EXPECTED)],
                           axis_min=20.0, axis_max=50.0)
    assert not charts.unaccounted_coordinates(
        charts.line_series(lines, label="l", names=("a", "b")), lines)

    dumbbell = geometry.dumbbells(DUMBBELLS)
    assert not charts.unaccounted_coordinates(
        charts.dumbbell_rows(dumbbell, label="l", names=("a", "b")), dumbbell)


def test_the_polyline_points_are_audited_too():
    """A line's coordinates live in one attribute, not one per point.

    A ``points="x,y x,y"`` list would otherwise slip past an attribute scan
    entirely, which is the shape of hole this check exists to avoid.
    """
    lines = geometry.lines([("a", POINTS)], axis_min=20.0, axis_max=50.0)
    markup = charts.line_series(lines, label="l", names=("a",))
    points = re.search(r'points="([^"]+)"', markup)
    assert points, "no polyline found"
    produced = set(lines.marks[0]["points"].replace(",", " ").split())
    for value in points.group(1).replace(",", " ").split():
        assert value in produced, f"{value} is not in the computed point list"


# ===========================================================================
# The printed-value half, verified rather than assumed
# ===========================================================================

def test_the_text_scan_reads_svg_text_and_title_nodes(page):
    """The correction to the spec.

    It claimed the tag-stripping regex removes SVG text, so W15 would have to
    extend the scan. ``<text>0.703</text>`` is element content rather than a tag,
    so the scan already read it. Asserted here so the claim stays checked.
    """
    text = re.sub(r"<[^>]+>", "\n", page["markup"])
    geometry_values = {mark["text"] for mark in page["geometries"][0].marks}
    assert geometry_values, "no printed values to look for"
    for value in geometry_values:
        assert value in text, (
            f"{value} is printed in an SVG text node and the scan cannot see it")

    # And a title node's combined readout.
    assert any("Tax Preparers:" in line for line in text.splitlines())


def test_every_printed_value_on_the_page_is_traced(page):
    """Both halves together: what is read, and what is drawn."""
    from nodes.figure_guard import _numbers_in
    from report.provenance import _is_furniture

    text = re.sub(r"<[^>]+>", "\n", page["markup"])
    unaccounted = [
        literal
        for line in text.splitlines()
        for literal, value in _numbers_in(line)
        if literal not in page["view"].figures
        and not _is_furniture(literal, value, line)]
    assert not unaccounted, sorted(set(unaccounted))


def test_the_two_halves_check_different_things(page):
    """Neither check subsumes the other, so both are needed.

    The printed set and the drawn set barely overlap: a reader reads "0.703" and
    the renderer draws "246.2". A single check over one of them would leave the
    other unguarded.
    """
    printed = set()
    for mark in page["geometries"][0].marks:
        printed.add(mark["text"])
    drawn = set(page["geometries"][0].layout)
    assert printed and drawn
    assert not printed & drawn, (
        "printed values and drawn positions overlap; one check might then "
        "appear to cover both")


# ===========================================================================
# The identifier exclusion must not become a loophole
# ===========================================================================

def test_the_shared_scan_is_the_one_verify_stack_uses(page):
    """One definition, so the suite and the stack check cannot disagree.

    Both call ``charts.untraced_figures``. Two implementations of "what counts
    as an untraced figure" would eventually report different things about the
    same page, and the one nobody runs would be the wrong one.
    """
    from pathlib import Path

    unaccounted = charts.untraced_figures(
        page["markup"], page["view"].figures, page["view"].identifiers)
    assert not unaccounted, sorted(unaccounted)

    verifier = Path("scripts/verify_stack.py").read_text(encoding="utf-8")
    assert "charts.untraced_figures" in verifier


def test_the_identifier_exclusion_strips_rather_than_skips(page):
    """A line-level skip was a loophole, and this pins the narrower rule.

    The masthead reads "12 roles · 231 tasks · cohort finance_13_2". Skipping any
    line that named an identifier excused two real figures on that line. The
    identifier is now removed from the line and the remainder is still checked,
    so "gpt-5.4-mini" excuses 5.4 and nothing else.
    """
    from pathlib import Path

    source = Path("src/app/charts.py").read_text(encoding="utf-8")
    scan = source[source.index("def untraced_figures"):]
    assert "stripped = stripped.replace(name" in scan
    assert "if any(name in line for name in identifiers):" not in scan, (
        "the blunt line-level skip is back")

    # The masthead's figures are still inside the checked set, not excused.
    assert page["view"].roles_assessed in page["view"].figures
    assert page["view"].tasks_assessed in page["view"].figures

    poisoned = page["markup"].replace(
        f'cohort {page["view"].cohort_name}',
        f'cohort {page["view"].cohort_name} · 88.8% hit rate', 1)
    unaccounted = charts.untraced_figures(
        poisoned, page["view"].figures, page["view"].identifiers)
    assert "88.8%" in unaccounted, (
        "a figure beside an identifier on the same line was excused")


def test_an_invented_figure_is_caught_even_with_identifiers_present(page):
    """Proves the exclusion does not disable the scan."""
    poisoned = page["markup"].replace(
        "</article>", "<p>Fully 73.2% of these roles vanish by 2031.</p></article>")
    unaccounted = charts.untraced_figures(
        poisoned, page["view"].figures, page["view"].identifiers)
    assert "73.2%" in unaccounted
    assert "2031" in unaccounted


def test_the_identifiers_are_declared_by_the_view_not_hardcoded(page):
    """So a classifier change does not need a checker edited."""
    identifiers = page["view"].identifiers
    assert page["view"].classifier in identifiers
    assert page["view"].rubric_version in identifiers
    assert page["view"].cohort_name in identifiers
    # And they are names, not numbers.
    for value in identifiers:
        assert not value.replace(".", "").isdigit()

