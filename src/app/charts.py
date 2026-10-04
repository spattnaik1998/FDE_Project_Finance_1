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
