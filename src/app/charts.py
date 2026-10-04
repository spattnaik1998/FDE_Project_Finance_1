"""Chart primitives: SVG emitted from pre-computed strings.

This module does no arithmetic, by rule and by test. Every coordinate arrives
already formatted from :mod:`app.geometry`, which is the application tier and is
allowed to compute. The reason is the same one that keeps ``blocks.py``
arithmetic-free: a presentation layer that can compute can produce a figure that
is on no source, and the test that walks the rendered page for untraceable
numbers would have nothing to catch it with.

There is no plotting library here for that same reason. A library computes
geometry outside the traced path, and the chain this project maintains runs from
a hashed artefact to a pixel.

Mark specs follow one fixed set rather than per-chart taste: bars at 14px with a
4px rounded data-end and a square baseline, lines at 2px with round joins,
markers at radius 4.5 carrying a 2px surface ring so they stay legible where they
cross, hairline recessive gridlines, and a 2px surface gap doing the separating
between touching marks. Nothing is dashed and nothing carries a border --- the gap
and the ring are the mechanism.

Colour follows the job. Magnitude takes the sequential ramp, because twelve
occupations exceed any categorical palette and identity is not the point;
two-series charts take the two validated categorical slots. The brand red appears
in no chart at all: a bar in the brand's accent reads as an alarm, which would
tell a reader something the number does not say.
"""

from __future__ import annotations

from app.document import esc

# The validated palette, kept here as the record of what was checked. The marks
# themselves now wear CSS classes rather than these literals.
#
# Colour moved into the stylesheet in W14 for three reasons: dark-mode steps need
# somewhere to override, a token defined once cannot drift between three
# primitives, and the "no brand red in any chart" rule becomes checkable in one
# place instead of three.
#
# Checked with the data-viz validator rather than chosen by eye -- the project's
# structural navy FAILED as a series colour (OKLCH L 0.255, outside the
# 0.43-0.77 band; chroma 0.046, reads gray), so it is ink and the series hues are
# lifted versions that pass all six checks.
RAMP = ("#8FB9D1", "#669BBB", "#427AA0", "#215980", "#0C2537")
SERIES = ("#2E7DA8", "#A87A1E")

# The dark-mode steps, validated against the dark surface rather than flipped
# from the light ones. The page itself is pinned light by .streamlit/config.toml
# -- an institutional paper, by deliberate choice -- so these exist so the charts
# do not break if the surface ever changes, not because a toggle ships today.
SERIES_DARK = ("#0E8CD6", "#BC8C1C")

# Sizes that never vary, so no renderer has to decide.
BAR_RADIUS = "4"
LINE_WIDTH = "2"
RING_WIDTH = "2"
HAIRLINE = "1"


def _open(width: str, height: str, label: str, classes: str = "") -> str:
    """An accessible SVG root. Sized by viewBox so it scales to its container."""
    return (f'<svg class="chart {esc(classes)}" role="img" '
            f'aria-label="{esc(label)}" '
            f'viewBox="0 0 {esc(width)} {esc(height)}" '
            f'preserveAspectRatio="xMinYMin meet">')


def bar_rows(geometry, *, label: str) -> str:
    """Horizontal bars: magnitude across many long-named categories.

    A muted row is one that cannot be opened. It takes a hatched fill rather than
    a lighter colour, so the distinction survives greyscale, print and
    forced-colors --- nine of twelve rows are one number each and that has to be
    visible rather than discovered by clicking.
    """
    parts = [_open(geometry.width, geometry.height, label, "chart-bars"),
             _hatch_pattern()]
    for mark in geometry.marks:
        tone = ("c-muted" if mark["muted"]
                else f'c-ramp-{esc(mark["step"])}')
        parts.append(
            f'<text class="c-label" x="0" y="{esc(mark["label_y"])}" '
            f'dominant-baseline="middle">{esc(mark["label"])}</text>'
            f'<rect class="c-bar {tone}" x="{esc(mark["x"])}" '
            f'y="{esc(mark["y"])}" '
            f'width="{esc(mark["length"])}" height="{esc(mark["thickness"])}" '
            f'rx="{BAR_RADIUS}">'
            f'<title>{esc(mark["label"])}: {esc(mark["text"])}</title></rect>'
            f'<text class="c-value" x="{esc(mark["value_x"])}" '
            f'y="{esc(mark["label_y"])}" dominant-baseline="middle">'
            f'{esc(mark["text"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def line_series(geometry, *, label: str, names: tuple[str, ...]) -> str:
    """Two trend lines over a shared x axis, with end labels and a hover layer."""
    parts = [_open(geometry.width, geometry.height, label, "chart-lines")]
    for tick in geometry.axis:
        parts.append(
            f'<line class="c-grid" x1="0" y1="{esc(tick["y"])}" '
            f'x2="{esc(geometry.width)}" y2="{esc(tick["y"])}" '
            f'stroke-width="{HAIRLINE}"/>'
            f'<text class="c-tick" x="0" y="{esc(tick["y"])}" '
            f'dominant-baseline="middle">{esc(tick["value"])}</text>')
    for mark in geometry.marks:
        series = f'c-s{esc(mark["slot"])}'
        parts.append(
            f'<polyline class="c-line {series}" '
            f'points="{esc(mark["points"])}" fill="none" '
            f'stroke-width="{LINE_WIDTH}" '
            f'stroke-linejoin="round" stroke-linecap="round"/>')
        for dot in mark["dots"]:
            parts.append(
                f'<circle class="c-dot {series}" cx="{esc(dot["x"])}" '
                f'cy="{esc(dot["y"])}" r="4.5" '
                f'stroke-width="{RING_WIDTH}">'
                f'<title>{esc(mark["name"])} · {esc(dot["label"])}: '
                f'{esc(dot["text"])}</title></circle>')
        parts.append(
            f'<text class="c-end {series}-ink" x="{esc(mark["end_x"])}" '
            f'y="{esc(mark["end_y"])}" dx="10" dominant-baseline="middle">'
            f'{esc(mark["end_text"])}</text>')
    parts.append(_crosshair_slots(geometry))
    parts.append("</svg>")
    return "".join(parts) + legend(names)


def _crosshair_slots(geometry) -> str:
    """A crosshair and a per-period readout, in CSS alone.

    ``st.html`` does not execute JavaScript, so the usual mousemove crosshair is
    unavailable. This emits one invisible hit band per period with a sibling rule
    and readout, revealed by ``:hover`` on the band. No script, and it works
    under content policies that block one.

    The readout names every series at that period, which is the thing a
    per-mark tooltip cannot do: hovering one dot tells you one value, while the
    question a reader has at a point on a trend is what BOTH lines were doing.

    Keyboard and assistive-technology readers do not get a hover layer at all,
    which is the reason every chart ships a table view rather than treating it as
    an optional extra.
    """
    if not geometry.marks:
        return ""
    first = geometry.marks[0]
    band = geometry.hit_band
    slots = []
    for index, dot in enumerate(first["dots"]):
        readings = " · ".join(
            f'{mark["name"]}: {mark["dots"][index]["text"]}'
            for mark in geometry.marks
            if index < len(mark["dots"]))
        slots.append(
            f'<g class="c-slot">'
            f'<rect class="c-hit" x="{esc(dot["x"])}" y="0" '
            f'width="{esc(band)}" height="{esc(geometry.height)}" '
            f'transform="translate(-{esc(band)},0)"/>'
            f'<line class="c-cross" x1="{esc(dot["x"])}" y1="0" '
            f'x2="{esc(dot["x"])}" y2="{esc(geometry.height)}"/>'
            f'<title>{esc(dot["label"])} — {esc(readings)}</title>'
            f'</g>')
    return "".join(slots)


def dumbbell_rows(geometry, *, label: str, names: tuple[str, ...]) -> str:
    """Two positions per item, joined by a rule. The gap is the finding."""
    parts = [_open(geometry.width, geometry.height, label, "chart-dumbbell")]
    for tick in geometry.axis:
        parts.append(
            f'<line class="c-grid" x1="{esc(tick["x"])}" y1="0" '
            f'x2="{esc(tick["x"])}" y2="{esc(geometry.height)}" '
            f'stroke-width="{HAIRLINE}"/>')
    for mark in geometry.marks:
        parts.append(
            f'<text class="c-label" x="0" y="{esc(mark["y"])}" '
            f'dominant-baseline="middle">{esc(mark["label"])}</text>'
            f'<line class="c-join" x1="{esc(mark["from_x"])}" '
            f'y1="{esc(mark["y"])}" x2="{esc(mark["to_x"])}" '
            f'y2="{esc(mark["y"])}" stroke-width="{LINE_WIDTH}"/>'
            f'<circle class="c-dot c-s0" cx="{esc(mark["left_x"])}" '
            f'cy="{esc(mark["y"])}" r="{esc(mark["radius"])}" '
            f'stroke-width="{RING_WIDTH}">'
            f'<title>{esc(names[0])} Â· {esc(mark["label"])}: '
            f'{esc(mark["left_text"])}</title></circle>'
            f'<circle class="c-dot c-s1" cx="{esc(mark["right_x"])}" '
            f'cy="{esc(mark["y"])}" r="{esc(mark["radius"])}" '
            f'stroke-width="{RING_WIDTH}">'
            f'<title>{esc(names[1])} Â· {esc(mark["label"])}: '
            f'{esc(mark["right_text"])}</title></circle>')
    parts.append("</svg>")
    return "".join(parts) + legend(names)


def legend(names: tuple[str, ...]) -> str:
    """Always present for two or more series; omitted for one.

    Identity must never rest on colour alone. A single series needs no box ---
    there is one colour and the title already names it, so a swatch would restate
    the title and cost space.
    """
    names = tuple(names)
    if len(names) < 2:
        return ""
    items = "".join(
        f'<span class="c-key"><i class="c-s{index}-bg"></i>{esc(name)}</span>'
        for index, name in enumerate(names))
    return f'<div class="c-legend">{items}</div>'


def axis_note(text: str) -> str:
    """A qualifier that belongs on the axis rather than in a footnote.

    The adoption series is NAICS 52, which pools banking and insurance with
    securities, while the cost line is 523. A chart is the thing that gets
    screenshotted, so the caveat travels with it.
    """
    return f'<p class="c-axis-note">{esc(text)}</p>'


def table_view(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...],
               *, label: str) -> str:
    """The same numbers as a table, behind a disclosure.

    Every chart ships one. It is the accessibility floor and it is also the
    honest answer to a reader who wants the values rather than the shape.
    """
    head = "".join(f"<th>{esc(column)}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows)
    return (f'<details class="c-table"><summary>{esc(label)}</summary>'
            f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div></details>')


def _hatch_pattern() -> str:
    """One directional hatch, for the rows that cannot be opened.

    Texture rather than a lighter tint, so the distinction survives greyscale,
    print and forced-colors mode. Used for that one job and never decoratively.
    """
    return ('<defs><pattern id="hatch" width="6" height="6" '
            'patternTransform="rotate(45)" patternUnits="userSpaceOnUse">'
            '<rect class="c-hatch-bg" width="6" height="6"/>'
            '<line class="c-hatch-line" x1="0" y1="0" x2="0" y2="6" '
            'stroke-width="1.5"/></pattern></defs>')

# ---------------------------------------------------------------------------
# Auditing what was drawn
# ---------------------------------------------------------------------------
#
# The traceability chain had two halves and only one was checked. Printed values
# are covered: the rendered-text scan reads every ``<text>`` and ``<title>`` node
# and rejects a number the view model did not carry. Drawn POSITIONS were not --
# a renderer could place a mark at a coordinate nothing computed and no test
# would notice, because a reader cannot read "101.6" off the page and so the text
# scan never sees it.
#
# This closes it. Every coordinate attribute in the markup must come from the
# geometry that produced the chart, or be one of the fixed literals the mark
# specs put there.

# Fixed by the mark specs, not derived from data. Enumerated rather than matched
# by pattern, so adding a magic number to a primitive is a deliberate act.
SPEC_LITERALS = frozenset({
    "0",            # every axis origin, and a zero-length bar
    "1", "1.5", "2",  # hairline, hatch stroke, line and ring widths
    "4", "4.5",     # the bar's corner radius and the marker radius
    "6",            # the hatch tile
    "10",           # the end label's dx offset
})

COORDINATE_ATTRIBUTES = ("x", "y", "cx", "cy", "x1", "x2", "y1", "y2",
                         "width", "height", "r", "rx", "stroke-width", "dx")


def unaccounted_coordinates(markup: str, *geometries) -> set[str]:
    """Coordinates in the markup that no geometry produced.

    A non-empty result means a mark is drawn at a position nothing computed,
    which is the drawn-position equivalent of an untraced figure. Used by the
    tests and by ``verify_stack`` so there is one definition of the rule.
    """
    import re

    produced = set(SPEC_LITERALS)
    for geometry in geometries:
        if geometry is None:
            continue
        produced |= set(geometry.layout) | set(geometry.figures)
        produced.add(geometry.width)
        produced.add(geometry.height)
        produced.add(getattr(geometry, "hit_band", "0"))
        # Polyline point lists carry their own coordinates.
        for mark in geometry.marks:
            for value in str(mark.get("points", "")).replace(",", " ").split():
                produced.add(value)
            produced.update(
                str(mark[key]) for key in
                ("x", "y", "length", "thickness", "label_y", "value_x",
                 "left_x", "right_x", "from_x", "to_x", "radius",
                 "end_x", "end_y")
                if key in mark)
            for dot in mark.get("dots", ()):
                produced.update(str(dot[k]) for k in ("x", "y") if k in dot)
        produced.update(str(tick[k]) for tick in geometry.axis
                        for k in ("x", "y") if k in tick)

    pattern = "|".join(COORDINATE_ATTRIBUTES)
    found = set(re.findall(rf'(?:{pattern})="([\d.]+)"', markup))
    # A percentage width is a share, handled by the figure scan.
    return {value for value in found if value not in produced}

def untraced_figures(markup: str, traced, identifiers=()) -> set[str]:
    """Numbers a reader can read on the page that are not traced.

    Reads element content, which is where a reader's numbers live: ``<text>`` and
    ``<title>`` nodes are content rather than tags, so stripping tags exposes
    them. Attribute coordinates are deliberately NOT in scope --- a reader cannot
    read "101.6" --- and :func:`unaccounted_coordinates` covers those instead.

    ``identifiers`` are strings that name rather than measure: a model name, a
    rubric version, a cohort name. A line containing one is skipped, because
    "gpt-5.4-mini" is not a claim that 5.4 is a quantity. The alternative was to
    add such fragments to the traced set, which would assert exactly that.

    One definition for the suite and for ``verify_stack``, so the two cannot
    drift and report different things about the same page.
    """
    import re

    from nodes.figure_guard import _numbers_in
    from report.provenance import _is_furniture

    text = re.sub(r"<[^>]+>", chr(10), markup)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#x27;", "'")):
        text = text.replace(entity, char)

    unaccounted = set()
    for line in text.splitlines():
        # The identifier is REMOVED from the line, not used to skip it.
        #
        # Skipping the whole line was the first cut and it was a loophole: the
        # masthead reads "12 roles · 231 tasks · cohort finance_13_2", so naming
        # the cohort there excused two real figures on the same line. Stripping
        # the identifier leaves the rest of the line to be checked, which is
        # what was wanted -- "gpt-5.4-mini" excuses 5.4 and nothing else.
        stripped = line
        for name in identifiers:
            stripped = stripped.replace(name, " ")
        for literal, value in _numbers_in(stripped):
            if literal in traced or _is_furniture(literal, value, stripped):
                continue
            unaccounted.add(literal)
    return unaccounted
