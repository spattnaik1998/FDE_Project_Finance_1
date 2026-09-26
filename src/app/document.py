"""Blocks composed into one HTML document, rather than one widget each.

The page had a copy problem and a design problem. The copy is fixed; this module
is the design fix, and the reason it exists is worth stating because it is a
judgment about where the tier boundary actually is.

Streamlit's visual identity comes from its *widgets*: ``st.metric`` tiles,
``st.dataframe`` grids, expander chevrons, its default sans. Styling those with
a stylesheet fights the framework and loses --- the result reads as a dashboard
someone has tinted, because every element still carries its own container, its
own margin and its own idea of a heading. A finance research note is a
*document*: one measure, one vertical rhythm, one type scale, real tables.

So this module takes the block list --- unchanged, still the presentation model
--- and composes it into a single HTML document, emitted in one call. Streamlit
is then a loopback host, which is all TDD 4.1 asks of it, and the two things
that genuinely need to be widgets (the request form, the download button) stay
widgets and sit outside the document.

What that buys, concretely: real ``<table>`` markup with right-aligned tabular
numerals instead of a data grid; ``<details>`` for the method disclosures
instead of expanders; a three-card summary band; and a masthead that reads as a
letterhead. What it costs: HTML is assembled here as strings, so this module is
the one place an injection could enter, and every interpolated value passes
through :func:`esc`.

The rules from ``blocks.py`` carry over unchanged. There is no arithmetic in
this module --- every number arrives pre-formatted --- so the test that walks
the rendered document for numeric literals still closes the chain from a hashed
artefact to a pixel.
"""

from __future__ import annotations

from html import escape
from typing import Iterable

from app.blocks import Block

# Section headings get a number in the document even though the copy deliberately
# dropped "1. Standing" from the text. A numbered eyebrow above a question is
# navigation; a number inside the question is jargon. They are different jobs.
_NUMBERED = ("standing", "exposure", "lag", "calibration", "direction",
             "tasks", "limits", "provenance")


def esc(value: object) -> str:
    """Escape anything interpolated into markup. No exceptions."""
    return escape(str(value), quote=True)


def _inline(text: str) -> str:
    """The small subset of Markdown the copy uses, as HTML.

    Only ``**bold**`` and ``*italic*`` and ``code``. Escaping happens first, so
    a source document whose title contains a tag cannot open one here --- the
    emphasis is applied to already-escaped text, which is why this is a
    replacement pass rather than a Markdown library.
    """
    out = esc(text)
    for marker, tag in (("**", "strong"), ("*", "em"), ("`", "code")):
        parts = out.split(marker)
        if len(parts) < 3:
            continue
        rebuilt = [parts[0]]
        for index, part in enumerate(parts[1:], start=1):
            rebuilt.append(f"<{tag}>{part}</{tag}>" if index % 2 else part)
        # An unpaired marker leaves a stray tag, so only commit on an even count.
        out = "".join(rebuilt) if (len(parts) - 1) % 2 == 0 else out
    return out


# ---------------------------------------------------------------------------
# One renderer per block kind
# ---------------------------------------------------------------------------

def _title(payload, meta) -> str:
    return f'<h1 class="doc-title">{_inline(payload)}</h1>'


def _masthead(payload, meta) -> str:
    return (
        '<header class="masthead">'
        f'<p class="eyebrow">{esc(payload["eyebrow"])}</p>'
        f'<h1>{esc(payload["title"])}</h1>'
        f'<p class="lede">{esc(payload["question"])}</p>'
        f'<p class="meta">{esc(payload["meta"])}</p>'
        '</header>')


def _heading(payload, meta) -> str:
    index = meta.get("index")
    number = f'<span class="sec-no">{esc(index)}</span>' if index else ""
    return f'<h2 class="sec">{number}{_inline(payload)}</h2>'


def _caption(payload, meta) -> str:
    return f'<p class="caption">{_inline(payload)}</p>'


def _markdown(payload, meta) -> str:
    # A bullet is the only block-level construct the copy produces.
    if payload.lstrip().startswith("- "):
        return f'<p class="bullet">{_inline(payload.lstrip()[2:])}</p>'
    return f"<p>{_inline(payload)}</p>"


def _callout(payload, meta) -> str:
    tone = esc(meta.get("tone", "info"))
    return f'<aside class="note {tone}">{_inline(payload)}</aside>'


def _divider(payload, meta) -> str:
    return '<hr class="rule">'


def _panel(payload, meta) -> str:
    inner = "".join(render_block(b) for b in payload)
    return (f'<section class="panel">'
            f'<p class="panel-label">{esc(meta.get("label", ""))}</p>'
            f'{inner}</section>')


def _standing(payload, meta) -> str:
    tone = esc(payload["tone"])
    return (f'<div class="standing {tone}">'
            f'<p class="tag">{esc(payload["tag"])}</p>'
            f'<p class="body">{_inline(payload["body"])}</p></div>')


def _figure(payload, meta) -> str:
    """A bounded quantity: label, large numeral, and a track it sits in."""
    fill = payload.get("fill")
    meter = (f'<div class="meter"><i style="width:{esc(fill)}"></i></div>'
             if fill else "")
    note = (f'<p class="fig-note">{_inline(payload["note"])}</p>'
            if payload.get("note") else "")
    return (f'<div class="fig">'
            f'<p class="fig-label">{esc(payload["label"])}</p>'
            f'<p class="fig-value">{esc(payload["value"])}</p>'
            f'{meter}{note}</div>')


def _span(payload, meta) -> str:
    """An unbounded interval: three numerals and deliberately no track.

    The visual difference from ``_figure`` is load-bearing rather than
    decorative. Exposure is bounded 0 to 1 and a meter tells the truth about it;
    the lag is an open-ended interval in years, and giving it the same gauge
    would invite the one comparison the architecture refuses to make.
    """
    note = (f'<p class="fig-note">{_inline(payload["note"])}</p>'
            if payload.get("note") else "")
    return (f'<div class="fig">'
            f'<p class="fig-label">{esc(payload["label"])}</p>'
            f'<div class="span">'
            f'<span class="tick">{esc(payload["low"])}</span>'
            f'<span class="bar"></span>'
            f'<span class="mid">{esc(payload["mid"])}</span>'
            f'<span class="bar"></span>'
            f'<span class="tick">{esc(payload["high"])}</span>'
            f'</div>{note}</div>')


def _cards(payload, meta) -> str:
    """The summary band: the three findings side by side, above the fold.

    Side by side is a considered risk. The architecture refuses to combine
    exposure and lag into one score, and putting them in one row is the mildest
    version of inviting that --- but a reader who has to assemble the answer from
    three sections has not been given the answer. The mitigation is grammatical:
    each card keeps its own form (a meter for the bounded quantity, a trackless
    span for the interval), the label says what it is, and no arithmetic relates
    them. The detailed sections below carry the caveats.
    """
    inner = "".join(f'<div class="card">{render_block(b)}</div>'
                    for b in payload)
    return f'<div class="cards">{inner}</div>'


def _metrics(payload, meta) -> str:
    cells = "".join(
        f'<div class="metric">'
        f'<p class="metric-label">{esc(m["label"])}</p>'
        f'<p class="metric-value">{esc(m["value"])}</p></div>'
        for m in payload)
    return f'<div class="metrics">{cells}</div>'


def _is_numeric(cell: str) -> bool:
    """Whether a cell should be set as a numeral: right-aligned, tabular.

    Deliberately not "does it contain a digit" --- a task statement can, and
    right-aligning prose would look broken. A cell qualifies only when it is
    entirely a number, possibly with a sign, a decimal point or a percent sign.
    """
    stripped = cell.strip().rstrip("%").lstrip("+-")
    return bool(stripped) and stripped.replace(".", "", 1).isdigit()


def _table(payload, meta) -> str:
    """A real table, with each column aligned to the kind of value in it.

    Alignment is decided per column from the data rather than by position. The
    first cut right-aligned every column but the first, which put "Effect" and
    "Confidence" -- words -- hard against the right edge above left-aligned text.
    A header that does not sit over its own column is the detail that makes a
    table look built rather than designed.
    """
    rows = [[str(cell) for cell in row] for row in payload["rows"]]
    columns = list(payload["columns"])
    # A column is numeric when every value in it is. One prose cell in an
    # otherwise numeric column means the column is not a numeric column.
    numeric = [bool(rows) and all(_is_numeric(row[i]) for row in rows)
               for i in range(len(columns))]

    # The exposure spine. `bars` is a parallel list of CSS widths, one per row,
    # and `bar_column` says which cell carries it. Parallel rather than a seventh
    # column because it is not a value -- it is the same value in the cell it sits
    # in, drawn, so the reader sees the shape of the distribution rather than
    # reading 26 decimals and building it in their head. That shape is the claim
    # the rubric exists to support: it discriminates instead of saturating.
    bars = list(meta.get("bars") or [])
    bar_column = meta.get("bar_column")

    head = "".join(
        f'<th class="{"num" if numeric[i] else "txt"}">{esc(c)}</th>'
        for i, c in enumerate(columns))
    body = []
    for index, row in enumerate(rows):
        cells = []
        for i, cell in enumerate(row):
            spine = ""
            if i == bar_column and index < len(bars):
                spine = (f'<span class="spine">'
                         f'<i style="width:{esc(bars[index])}"></i></span>')
            cells.append(f'<td class="{"num" if numeric[i] else "txt"}">'
                         f'{spine}{_inline(cell)}</td>')
        body.append(f'<tr>{"".join(cells)}</tr>')
    return (f'<div class="table-wrap"><table>'
            f"<thead><tr>{head}</tr></thead>"
            f'<tbody>{"".join(body)}</tbody></table></div>')


def _expander(payload, meta) -> str:
    """A disclosure, as <details>. No framework chrome, no rerun."""
    inner = "".join(render_block(b) for b in payload)
    return (f'<details class="disclose"><summary>'
            f'{esc(meta.get("label", "Details"))}</summary>'
            f'<div class="disclose-body">{inner}</div></details>')


RENDERERS = {
    "title": _title, "masthead": _masthead, "heading": _heading,
    "caption": _caption, "markdown": _markdown, "callout": _callout,
    "divider": _divider, "panel": _panel, "standing": _standing,
    "figure": _figure, "span": _span, "cards": _cards, "metrics": _metrics, "table": _table,
    "expander": _expander,
}

# Kinds that are genuinely interactive and stay as Streamlit widgets. They are
# listed rather than ignored: a block kind that is neither rendered here nor
# named here is a programming error, and the composer raises on it.
WIDGET_KINDS = ("request_form", "download", "style")


def render_block(block: Block) -> str:
    renderer = RENDERERS.get(block.kind)
    if renderer is None:
        if block.kind in WIDGET_KINDS:
            return ""
        raise ValueError(f"no document renderer for block kind {block.kind!r}")
    return renderer(block.payload, block.meta)


def compose(blocks: Iterable[Block]) -> str:
    """The whole document, as one string.

    Renders what it is given and numbers nothing. Section numbering belongs to
    ``blocks.page``, which is the only caller that knows its headings are report
    sections --- this composer is also handed the request form and refusals.
    """
    body = "".join(render_block(b) for b in blocks)
    return f'<article class="doc">{body}</article>'


def segments(blocks: Iterable[Block]) -> list[tuple[str, object]]:
    """Split a block list into document runs and the widgets between them.

    Returns ``("html", markup)`` and ``("widget", block)`` in order, so a caller
    emits one ``st.html`` per run of document blocks and one widget where it
    belongs. Composing the whole page and then appending the widgets was the
    first cut, and it put the download button after the provenance table's
    closing rule instead of inside the section that earns it.

    Section numbers arrive already attached, so a widget in the middle of the
    page cannot renumber the sections after it.
    """
    out: list[tuple[str, object]] = []
    run: list[Block] = []
    for block in blocks:
        if block.kind in WIDGET_KINDS:
            if run:
                out.append(("html", compose(run)))
                run = []
            out.append(("widget", block))
        else:
            run.append(block)
    if run:
        out.append(("html", compose(run)))
    return out

