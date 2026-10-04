"""Chart geometry, computed in the application tier.

Every coordinate a chart draws is a figure. That is the whole reason this module
exists separately from :mod:`app.charts`.

The presentation modules are forbidden arithmetic by test --- ``blocks.py`` and
``document.py`` both fail a parse if they contain a ``-``, ``*``, ``/`` or ``%``
operator --- because a layer that can compute can produce a number that is on no
source, and the test that walks the rendered page for untraceable figures would
have nothing to catch it with. A plotting library would compute geometry outside
that path entirely, which is why there is no plotting library here.

So the division of labour is: this module turns values into pixel coordinates and
returns them as **pre-formatted strings** alongside the set of literals it
produced; :mod:`app.charts` emits SVG from those strings and does no sums.

Two conventions, both to keep the traced set small and legible:

**Coordinates are rounded to one decimal.** A full-precision float produces a
different literal for every data point and floods the traced figure set with
numbers nobody can check. One decimal is finer than a pixel at any sensible
display density.

**Only the values a reader can read are traced as figures.** A bar's *length* is
the datum in another unit and belongs in the traced set, which is the precedent
the task spine already set. Its *axis offset* is layout --- the sixth row sits at
the sixth row because it is sixth --- and is reported separately as
:attr:`ChartGeometry.layout` so the page's figure scan can tell the two apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A fixed plotting box, so every chart on the page shares one grid and the
# primitives never have to measure anything.
PLOT_WIDTH = 720.0
ROW_HEIGHT = 26.0
ROW_GAP = 2.0            # the surface gap: white does the separating
BAR_THICKNESS = 14.0     # under the 24px cap, and thin reads as considered
LABEL_GUTTER = 230.0     # room for long occupation titles
VALUE_GUTTER = 58.0      # room for the value at the bar tip
MARKER_RADIUS = 4.5      # >= 4, so the mark clears the 8px minimum
LINE_HEIGHT = 240.0


@dataclass(frozen=True)
class ChartGeometry:
    """Pre-formatted coordinates, plus what of them is a figure.

    ``figures`` are values a reader reads, and must already be traceable.
    ``layout`` are positions that carry no meaning beyond where a mark sits.
    Keeping them apart is what lets the page's traceability scan check the first
    set strictly without being flooded by the second.
    """

    marks: tuple[dict, ...]
    width: str
    height: str
    # Half-gap between x positions, as a crosshair hit-band width. Lives here
    # rather than in app.charts because it is arithmetic, and the rule that the
    # presentation tier computes nothing stays absolute -- the first attempt put
    # this division in charts.py and the parse test caught it immediately. It
    # encodes no datum and joins no traced set: it is a hit target.
    hit_band: str = "0"
    figures: frozenset[str] = field(default_factory=frozenset)
    layout: frozenset[str] = field(default_factory=frozenset)
    axis: tuple[dict, ...] = ()


def _n(value: float) -> str:
    """One decimal, trailing zero dropped. The only formatter in this module."""
    return f"{value:.1f}".rstrip("0").rstrip(".") or "0"


def _share(value: float, maximum: float) -> float:
    """A value as a fraction of the axis maximum, clamped."""
    if maximum <= 0:
        return 0.0
    return max(0.0, min(1.0, value / maximum))


# ---------------------------------------------------------------------------
# Horizontal bars: compare magnitude across many long-named categories
# ---------------------------------------------------------------------------

def bars(rows, *, axis_max: float = 1.0) -> ChartGeometry:
    """One row per item, bar length proportional to its value.

    ``rows`` is a sequence of ``(label, value, text, muted)``. ``text`` is the
    already-provenanced string the view carries for that value, and it is what
    the chart prints --- the float is used for geometry only, so a chart can
    never display a number the view model did not already carry.
    """
    rows = list(rows)
    track = PLOT_WIDTH - LABEL_GUTTER - VALUE_GUTTER
    marks, figures, layout = [], set(), set()

    for index, (label, value, text, muted) in enumerate(rows):
        length = track * _share(float(value), axis_max)
        y = index * (ROW_HEIGHT + ROW_GAP)
        bar_y = y + (ROW_HEIGHT - BAR_THICKNESS) / 2

        marks.append({
            "label": label,
            "text": text,
            "muted": bool(muted),
            "x": _n(LABEL_GUTTER),
            "y": _n(bar_y),
            "length": _n(length),
            "thickness": _n(BAR_THICKNESS),
            "label_y": _n(y + ROW_HEIGHT / 2),
            "value_x": _n(LABEL_GUTTER + length + 8.0),
            # Which ramp step this row takes. Magnitude carries the colour
            # because twelve categories exceed any categorical palette.
            "step": str(min(4, int(_share(float(value), axis_max) * 5))),
        })
        # The PRINTED value is the figure; the bar's pixel length is layout.
        #
        # The first cut had these the other way round, which put values like
        # "246.2" into the traced set -- a datum multiplied by an arbitrary
        # layout constant, which no reader can read off the page and which
        # floods the traced set with numbers nobody can check.
        #
        # This is a real distinction from the task spine's widths, which ARE
        # traced: a spine width is "70%", the datum as a share and readable as
        # one. A pixel length is not the datum in another unit, it is the datum
        # times a plot width.
        figures.add(text)
        layout.update({_n(length), _n(bar_y), _n(y + ROW_HEIGHT / 2),
                       _n(LABEL_GUTTER + length + 8.0)})

    height = len(rows) * (ROW_HEIGHT + ROW_GAP)
    return ChartGeometry(
        marks=tuple(marks), width=_n(PLOT_WIDTH), height=_n(height),
        figures=frozenset(figures), layout=frozenset(layout))


# ---------------------------------------------------------------------------
# Lines: trend over time, two series
# ---------------------------------------------------------------------------

def lines(series, *, axis_min: float, axis_max: float) -> ChartGeometry:
    """One polyline per series over a shared x index.

    ``series`` is a sequence of ``(name, points)`` where ``points`` is a
    sequence of ``(x_label, value, text)``. Every series must share the same
    x labels: a line chart over two different x axes is two charts.
    """
    series = [(name, list(points)) for name, points in series]
    if not series:
        return ChartGeometry(marks=(), width=_n(PLOT_WIDTH), height=_n(LINE_HEIGHT))

    lengths = {len(points) for _, points in series}
    if len(lengths) != 1:
        raise ValueError(
            f"series have different point counts {sorted(lengths)}; a line "
            f"chart over two different x axes is two charts")

    count = lengths.pop()
    span = max(1, count - 1)
    track = PLOT_WIDTH - LABEL_GUTTER
    spread = axis_max - axis_min

    marks, figures, layout = [], set(), set()
    for slot, (name, points) in enumerate(series):
        coordinates, dots = [], []
        for index, (x_label, value, text) in enumerate(points):
            x = LABEL_GUTTER + track * (index / span)
            y = LINE_HEIGHT - LINE_HEIGHT * _share(float(value) - axis_min,
                                                   spread if spread > 0 else 1.0)
            coordinates.append(f"{_n(x)},{_n(y)}")
            dots.append({"x": _n(x), "y": _n(y), "label": x_label, "text": text})
            figures.add(text)
            layout.update({_n(x), _n(y)})
        marks.append({
            "name": name, "slot": str(slot),
            "points": " ".join(coordinates),
            "dots": tuple(dots),
            "end_x": dots[-1]["x"], "end_y": dots[-1]["y"],
            "end_text": dots[-1]["text"],
        })

    axis = tuple({"value": _n(axis_min + spread * (step / 4)),
                  "y": _n(LINE_HEIGHT - LINE_HEIGHT * (step / 4))}
                 for step in range(5))
    layout.update(tick["y"] for tick in axis)
    return ChartGeometry(
        marks=tuple(marks), width=_n(PLOT_WIDTH), height=_n(LINE_HEIGHT),
        figures=frozenset(figures), layout=frozenset(layout), axis=axis,
        hit_band=_n(track / max(1, count)))


# ---------------------------------------------------------------------------
# Dumbbells: two positions per item
# ---------------------------------------------------------------------------

def dumbbells(rows, *, axis_max: float = 100.0) -> ChartGeometry:
    """One row per item, two dots joined by a rule.

    ``rows`` is a sequence of ``(label, left_value, left_text, right_value,
    right_text)``. Used for rank agreement: our percentile against the
    benchmark's, within one cohort. The distance between the dots IS the finding,
    which is why a single delta number cannot replace it.
    """
    rows = list(rows)
    track = PLOT_WIDTH - LABEL_GUTTER - VALUE_GUTTER
    marks, figures, layout = [], set(), set()

    for index, (label, left, left_text, right, right_text) in enumerate(rows):
        y = index * (ROW_HEIGHT + ROW_GAP) + ROW_HEIGHT / 2
        lx = LABEL_GUTTER + track * _share(float(left), axis_max)
        rx = LABEL_GUTTER + track * _share(float(right), axis_max)
        marks.append({
            "label": label, "y": _n(y),
            "left_x": _n(lx), "right_x": _n(rx),
            "left_text": left_text, "right_text": right_text,
            "radius": _n(MARKER_RADIUS),
            # Which dot sits left on screen, so the connector is drawn once in
            # the right direction without the renderer comparing anything.
            "from_x": _n(min(lx, rx)), "to_x": _n(max(lx, rx)),
        })
        figures.update({left_text, right_text})
        layout.update({_n(y), _n(lx), _n(rx)})

    height = len(rows) * (ROW_HEIGHT + ROW_GAP)
    axis = tuple({"value": _n(axis_max * (step / 4)),
                  "x": _n(LABEL_GUTTER + track * (step / 4))}
                 for step in range(5))
    layout.update(tick["x"] for tick in axis)
    return ChartGeometry(
        marks=tuple(marks), width=_n(PLOT_WIDTH), height=_n(height),
        figures=frozenset(figures), layout=frozenset(layout), axis=axis)
