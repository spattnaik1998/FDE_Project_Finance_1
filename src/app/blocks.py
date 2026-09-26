"""What the UI shows, as data rather than as Streamlit calls.

The page is built as a list of :class:`Block` values, and a thin dispatcher in
``app.streamlit_app`` turns each one into the corresponding ``st.*`` call. The
split exists so the presentation logic is testable without a browser, a server
or Streamlit itself: a test asks for the blocks and inspects them.

It also makes the "renders no figure it did not receive" rule checkable.
Because every number reaches the page as a string inside a block, a test can
walk every block, extract every numeric literal, and assert it appears in the
view model. Nothing is computed here --- there is no arithmetic in this module
at all, which is the property that makes the assertion meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app import copy
from app.view_model import ReportView

# Block kinds the dispatcher knows how to render. A block of any other kind is
# a programming error and the dispatcher raises rather than silently skipping,
# because a silently dropped block is a figure the customer never saw.
KINDS = ("title", "caption", "heading", "markdown", "callout", "metrics",
         "table", "divider", "expander", "download", "request_form",
         "style", "figure", "span", "standing", "masthead", "panel")


@dataclass(frozen=True)
class Block:
    kind: str
    payload: Any = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown block kind {self.kind!r}")


def _b(kind, payload=None, **meta) -> Block:
    return Block(kind=kind, payload=payload, meta=meta)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _figure(label: str, value: str, note: str = "",
            fill_percent: str | None = None) -> Block:
    """A bounded figure: label, large mono value, optional meter.

    Used for exposure, which runs 0 to 1 and therefore has a track to sit in.
    ``fill_percent`` arrives pre-computed as a string -- this module does no
    arithmetic, by rule.
    """
    return _b("figure", {"label": label, "value": value, "note": note,
                         "fill": fill_percent})


def _span(label: str, low: str, mid: str, high: str, note: str = "") -> Block:
    """An unbounded interval: two ticks and a median, deliberately no track.

    Used for the lag. Giving it the same meter as exposure would invite the one
    comparison the architecture refuses to make -- the two are different
    quantities on different scales, and the visual grammar says so.
    """
    return _b("span", {"label": label, "low": low, "mid": mid, "high": high,
                       "note": note})


def _standing(tone: str, tag: str, body: str) -> Block:
    """The run's standing as a stamp: a coloured rule and a line of text.

    Not a filled banner. "Analyst review required" is a finding, and a finding
    rendered as a hazard strip reads as a defect -- a client discounts
    everything printed under it. A hairline rule in dark ochre reads as rigour
    and keeps the fact fully visible, which is the point.
    """
    return _b("standing", {"tone": tone, "tag": tag, "body": body})


def request_form_blocks(occupations, default_question: str,
                        cost) -> list[Block]:
    """The request half of the tier contract, as blocks.

    TDD 1.1 draws a typed request from the presentation tier into orchestration.
    This is where the customer supplies it. The form carries a question and
    nothing else -- no SOC code, no scoring parameters -- because resolving free
    text to an occupation is the Intent & Scope node's job, and a UI that
    pre-resolved it would move a model's judgment into the presentation tier.

    The in-scope list is shown up front. A form that mostly answers "out of
    scope" is a poor way to learn what the system covers, and a refusal still
    costs a model call.
    """
    rows = [[o["title"], o["soc_code"], str(o["tasks"])] for o in occupations]
    return [
        _b("heading", copy.FORM_HEADING),
        _b("markdown", copy.FORM_INTRO),
        _b("request_form", {
            "default_question": default_question,
            "label": copy.FORM_LABEL,
            "submit_label": copy.FORM_SUBMIT,
            "confirm_label": copy.FORM_CONFIRM,
        }),
        _b("expander", [
            _b("markdown",
               "These are the roles we currently hold task data for. Ask about "
               "anything else and the system says so rather than answering "
               "about a role that merely looks similar."),
            _b("table", {"columns": ["Role", "Occupation code", "Tasks held"],
                         "rows": rows}),
            _b("caption", copy.form_cost(cost)),
        ], label=f"What we cover, and what a run costs "
                 f"({len(rows)} roles available)"),
        _b("divider"),
    ]


def refusal_blocks(refusal) -> list[Block]:
    """A refusal rendered as an answer, not as an error.

    "That occupation is not published" is a correct response to a reasonable
    question. Presenting it as a crash would teach the customer to distrust the
    system for behaving properly.
    """
    blocks = [
        _b("heading", copy.REFUSAL_HEADING),
        _b("callout", refusal.message, tone="warn"),
    ]
    if refusal.in_scope_hint:
        blocks.append(_b("markdown", "**Roles we can assess today:** "
                         + ", ".join(refusal.in_scope_hint)))
    # The machine-readable code stays available, but demoted. A client does
    # not need it; whoever they forward the screenshot to does.
    blocks.append(_b("caption", f"Reference: {refusal.code}"))
    blocks.append(_b("divider"))
    return blocks


def header_blocks(view: ReportView) -> list[Block]:
    """A masthead and the bottom line, in that order.

    The bottom line sits above everything, including the standing. That is a
    change of mind worth recording: the standing used to lead, on the principle
    that a reader should know what a figure is worth before they see it. But a
    reader who has not yet seen the figure has nothing to weigh, and a page that
    opens on a caveat reads as an apology. The finding leads; its standing is
    the very next thing on the page, unmissable and one line below.
    """
    return [
        _b("masthead", {
            "eyebrow": copy.MASTHEAD_EYEBROW,
            "title": view.occupation_title,
            "question": copy.MASTHEAD_QUESTION,
            "meta": f"Occupation code {view.soc_code} · "
                    f"{view.tasks_scored} tasks assessed · "
                    f"prepared {view.generated_on}",
        }),
        _b("panel", [
            _b("markdown", copy.bottom_line(view)),
            _b("markdown", copy.bottom_line_action(view)),
        ], label=copy.BOTTOM_LINE_LABEL),
        _b("markdown", copy.MASTHEAD_NOTE),
        _b("divider"),
    ]


def standing_blocks(view: ReportView) -> list[Block]:
    """The standing leads, before any figure. Same rule as the document."""
    standing = view.standing
    blocks = [
        _b("heading", copy.HEADINGS["standing"]),
        # A stamp, not a filled banner. "Analyst review required" is a finding;
        # rendered as a hazard strip it reads as a defect and a client discounts
        # everything printed beneath it. A hairline rule in dark ochre keeps the
        # fact fully visible and reads as rigour.
        _standing(standing.tone, standing.headline, standing.meaning),
    ]
    # The reason moves behind a disclosure. It is three sentences of statistical
    # argument -- essential, and the wrong thing to place between a client and
    # the figure they came for. The standing itself stays on the page.
    if standing.reason or standing.workings:
        inner = []
        if standing.reason:
            inner.append(_b("markdown", standing.reason))
        if standing.workings:
            # Verbatim from the report, not paraphrased. A client who wants the
            # statistics is entitled to the same sentences the technical
            # document carries; a client who does not never opens this.
            inner.append(_b("caption", "The statistical detail behind that:"))
            inner.append(_b("markdown", standing.workings))
        blocks.append(_b("expander", inner,
                         label="Why the independent check was inconclusive"))

    if view.unverified_mirrors:
        names = ", ".join(f"`{s.doc_id}`" for s in view.unverified_mirrors)
        blocks.append(_b(
            "callout",
            f"**Unverified mirror in the evidence chain:** {names}. The "
            f"content is hashed and reproducible, but was obtained from a copy "
            f"rather than the publisher. Spot-check before external use.",
            tone="warn"))

    if not view.trace_complete:
        blocks.append(_b(
            "callout",
            f"**Provenance chain incomplete.** {view.trace_detail} "
            f"Figures on this page cannot all be traced to a hashed artefact.",
            tone="stop"))
    return blocks


def exposure_blocks(view: ReportView) -> list[Block]:
    return [
        _b("heading", copy.HEADINGS["exposure"]),
        # A bounded figure with a track, because the index runs 0 to 1.
        _figure("Share of tasks AI could perform today",
                view.exposure_share_text,
                note=f"Across {view.tasks_scored} tasks in this role",
                fill_percent=view.exposure_percent),
        _b("markdown", copy.exposure_answer(view)),
        _b("callout", copy.EXPOSURE_NOT, tone="info"),
        _b("expander", [
            _b("markdown", copy.EXPOSURE_METHOD),
            _b("caption", f"Index {view.exposure_index} on a 0–1 scale. "
                          f"{view.weighting_note}"),
        ], label=copy.METHOD_LABEL),
    ]


def lag_blocks(view: ReportView) -> list[Block]:
    method = [_b("markdown", copy.LAG_METHOD),
              _b("caption", f"Basis: {view.lag_basis}")]
    if view.lag_grounding:
        method.append(_b("caption",
                         f"Historical grounding: {view.lag_grounding}"))
    return [
        _b("heading", copy.HEADINGS["lag"]),
        # A span with no track, deliberately unlike exposure's meter. The lag is
        # an unbounded interval in years; giving it the same gauge would invite
        # the one comparison this architecture refuses to make.
        _span("Years before the cost line moves", view.lag_p10, view.lag_p50,
              view.lag_p90,
              note="Earliest · most likely · latest — a deliberate range, "
                   "not a forecast"),
        _b("markdown", copy.lag_answer(view)),
        _b("markdown", copy.LAG_WHY),
        _b("expander", method, label=copy.METHOD_LABEL),
    ]


def calibration_blocks(view: ReportView) -> list[Block]:
    """Did an independent source agree? Answered in a word, then in numbers."""
    blocks = [_b("heading", copy.HEADINGS["calibration"])]
    if not view.calibration_is_identifiable:
        blocks.append(_b("markdown", copy.CALIBRATION_NOT_IDENTIFIABLE))
        blocks.append(_b("caption",
                         f"Benchmark measure on file: {view.benchmark_measure}"))
        return blocks

    if view.calibration_outcome == "pass":
        blocks.append(_b("markdown", copy.CALIBRATION_ANSWER_YES))
    else:
        blocks.append(_b("markdown",
                         copy.calibration_answer_inconclusive(view)))
    # The three percentiles stay on the page. A reader who was told the check
    # was inconclusive is owed the numbers it was inconclusive about.
    blocks.append(_b("metrics", [
        {"label": "Our estimate ranks at", "value": view.our_percentile},
        {"label": "Published index ranks it at",
         "value": view.benchmark_percentile},
        {"label": "Difference", "value": view.delta},
    ]))
    blocks.append(_b("caption",
                     f"Compared within a cohort of finance occupations · "
                     f"policy {view.calibration_policy_version}"))
    return blocks


def direction_blocks(view: ReportView) -> list[Block]:
    blocks = [
        _b("heading", copy.HEADINGS["direction"]),
        _b("markdown", copy.direction_answer(view)),
        _b("metrics", [
            {"label": "Assists the person", "value": view.direction_augment},
            {"label": "Could replace the task",
             "value": view.direction_substitute},
            {"label": "Too ambiguous to call", "value": view.direction_unclear},
        ]),
        _b("markdown", copy.DIRECTION_WHY),
    ]
    return blocks


def task_table_blocks(view: ReportView) -> list[Block]:
    cols = copy.TASK_COLUMNS
    return [
        _b("heading", copy.HEADINGS["tasks"]),
        _b("markdown", copy.TASKS_INTRO),
        _b("table", {
            "columns": [cols["statement"], cols["raw"], cols["tacit"],
                        cols["adjusted"], cols["direction"],
                        cols["confidence"]],
            "rows": [[t.statement, t.raw, t.tacit, t.adjusted, t.direction,
                      t.confidence] for t in view.tasks],
        }),
        _b("expander", [_b("markdown", copy.TASKS_METHOD)],
           label=copy.METHOD_LABEL),
    ]


def limitations_blocks(view: ReportView) -> list[Block]:
    blocks = [
        _b("heading", copy.HEADINGS["limits"]),
        _b("markdown", copy.LIMITS_INTRO),
    ]
    for caveat in view.caveats:
        blocks.append(_b("markdown", f"- {caveat}"))
    return blocks


def provenance_blocks(view: ReportView) -> list[Block]:
    """The panel that makes the figures checkable."""
    blocks = [
        _b("heading", copy.HEADINGS["provenance"]),
        _b("markdown", copy.PROVENANCE_INTRO),
        _b("markdown", copy.provenance_summary(view)),
        _b("metrics", [
            {"label": "Figures traced to a source",
             "value": view.trace_figures},
            {"label": "Every figure traced",
             "value": "yes" if view.trace_complete else "no"},
            {"label": "Cleared for external use",
             "value": "yes" if view.trace_customer_deliverable else "no"},
        ]),
        _b("table", {
            "columns": ["Source", "What it is", "Format", "Used for",
                        "Fingerprint"],
            "rows": [[f"{s.doc_id}{' (mirror)' if s.is_unverified_mirror else ''}",
                      s.publisher, s.format, s.used_as, s.short_digest]
                     for s in view.sources],
        }),
    ]

    if view.claims:
        inner = [
            _b("markdown", copy.CLAIMS_INTRO),
            _b("caption", copy.CLAIMS_GRANULARITY),
            _b("table", {
                "columns": ["Subject", "Page", "What the source says",
                            "Document"],
                "rows": [[c.topic, c.page, c.quote, c.source_doc_id]
                         for c in view.claims],
            }),
        ]
        blocks.append(_b("expander", inner,
                         label=f"The exact wording we relied on "
                               f"({len(view.claims)} passages)"))

    blocks += [
        _b("expander", [_b("markdown", copy.PROVENANCE_METHOD)],
           label=copy.METHOD_LABEL),
        _b("divider"),
        _b("caption",
           f"Run `{view.run_id}` · code `{view.git_sha[:12]}` · rubric "
           f"`{view.rubric_version}` · calibration policy "
           f"`{view.calibration_policy_version}` · customer deliverable "
           f"`{view.is_customer_deliverable}`"),
        _b("download", view.markdown,
           label="Download the full technical report (Markdown)",
           file_name=f"exposure_{view.soc_code}_{view.run_id[:8]}.md"),
    ]
    return blocks


def page(view: ReportView) -> list[Block]:
    """The whole page, in order. Standing first, provenance last."""
    blocks: list[Block] = []
    for section in (header_blocks, standing_blocks, exposure_blocks,
                    lag_blocks, calibration_blocks, direction_blocks,
                    task_table_blocks, limitations_blocks, provenance_blocks):
        blocks.extend(section(view))
        blocks.append(_b("divider"))
    return blocks[:-1]


# ---------------------------------------------------------------------------
# For the tests: everything displayed, as flat text
# ---------------------------------------------------------------------------

def displayed_strings(blocks: list[Block]) -> list[str]:
    """Every string a viewer would read, flattened.

    Used by the test that asserts the UI displays no figure the view model did
    not carry. It recurses into expanders and tables, because a number hidden
    in a nested block is still a number on the page.
    """
    out: list[str] = []
    for block in blocks:
        payload = block.payload
        if isinstance(payload, str):
            out.append(payload)
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, Block):
                    out.extend(displayed_strings([item]))
                elif isinstance(item, dict):
                    out.extend(str(v) for v in item.values())
                else:
                    out.append(str(item))
        elif isinstance(payload, dict):
            # Tables first, then EVERY other value in the payload.
            #
            # This used to read only columns and rows, which meant the figure,
            # span and standing blocks -- whose values live under other keys --
            # were invisible to it. That would have made
            # test_the_ui_displays_no_figure_the_view_model_did_not_carry pass
            # vacuously for exactly the blocks that now carry the headline
            # numbers. A traceability check that cannot see the figures is
            # worse than none, because it reports success.
            out.extend(str(c) for c in payload.get("columns", []))
            for row in payload.get("rows", []):
                out.extend(str(cell) for cell in row)
            for key, value in payload.items():
                if key in ("columns", "rows"):
                    continue
                if isinstance(value, (str, int, float)):
                    out.append(str(value))
        for value in block.meta.values():
            out.append(str(value))
    return out
