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

# The validated palette. Checked with the data-viz validator rather than chosen
# by eye -- the project's structural navy FAILED as a series colour (OKLCH L
# 0.255, outside the 0.43-0.77 band; chroma 0.046, reads gray), so it is ink here
# and the series hues are lifted versions that pass.
RAMP = ("#8FB9D1", "#669BBB", "#427AA0", "#215980", "#0C2537")
SERIES = ("#2E7DA8", "#A87A1E")

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
        fill = ("url(#hatch)" if mark["muted"]
                else RAMP[int(mark["step"])])
        parts.append(
            f'<text class="c-label" x="0" y="{esc(mark["label_y"])}" '
            f'dominant-baseline="middle">{esc(mark["label"])}</text>'
            f'<rect class="c-bar" x="{esc(mark["x"])}" y="{esc(mark["y"])}" '
            f'width="{esc(mark["length"])}" height="{esc(mark["thickness"])}" '
            f'rx="{BAR_RADIUS}" fill="{fill}">'
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
        colour = SERIES[int(mark["slot"])]
        parts.append(
            f'<polyline class="c-line" points="{esc(mark["points"])}" '
            f'fill="none" stroke="{colour}" stroke-width="{LINE_WIDTH}" '
            f'stroke-linejoin="round" stroke-linecap="round"/>')
        for dot in mark["dots"]:
            parts.append(
                f'<circle class="c-dot" cx="{esc(dot["x"])}" '
                f'cy="{esc(dot["y"])}" r="4.5" fill="{colour}" '
                f'stroke-width="{RING_WIDTH}">'
                f'<title>{esc(mark["name"])} · {esc(dot["label"])}: '
                f'{esc(dot["text"])}</title></circle>')
        parts.append(
            f'<text class="c-end" x="{esc(mark["end_x"])}" '
            f'y="{esc(mark["end_y"])}" dx="10" dominant-baseline="middle">'
            f'{esc(mark["end_text"])}</text>')
    parts.append("</svg>")
    return "".join(parts) + legend(names)


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
            f'<circle class="c-dot" cx="{esc(mark["left_x"])}" '
            f'cy="{esc(mark["y"])}" r="{esc(mark["radius"])}" '
            f'fill="{SERIES[0]}" stroke-width="{RING_WIDTH}">'
            f'<title>{esc(names[0])} · {esc(mark["label"])}: '
            f'{esc(mark["left_text"])}</title></circle>'
            f'<circle class="c-dot" cx="{esc(mark["right_x"])}" '
            f'cy="{esc(mark["y"])}" r="{esc(mark["radius"])}" '
            f'fill="{SERIES[1]}" stroke-width="{RING_WIDTH}">'
            f'<title>{esc(names[1])} · {esc(mark["label"])}: '
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
        f'<span class="c-key"><i style="background:{SERIES[index]}"></i>'
        f'{esc(name)}</span>'
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
            '<rect width="6" height="6" fill="#F1F3F6"/>'
            '<line x1="0" y1="0" x2="0" y2="6" stroke="#8E8B88" '
            'stroke-width="1.5"/></pattern></defs>')
