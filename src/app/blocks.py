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

from app.view_model import ReportView

# Block kinds the dispatcher knows how to render. A block of any other kind is
# a programming error and the dispatcher raises rather than silently skipping,
# because a silently dropped block is a figure the customer never saw.
KINDS = ("title", "caption", "heading", "markdown", "callout", "metrics",
         "table", "divider", "expander", "download", "request_form",
         "style", "figure", "span", "standing")


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
        _b("heading", "Run a new analysis"),
        _b("markdown",
           "Ask in your own words. The orchestration tier resolves the "
           "occupation itself and **halts rather than substituting a similar "
           "one** if the warehouse does not publish it."),
        _b("request_form", {
            "default_question": default_question,
            "label": "Which cost lines do you want assessed?",
            "submit_label": "Run analysis",
        }),
        _b("expander", [
            _b("markdown",
               "These are the occupations currently loaded. Anything else is "
               "correctly refused rather than approximated."),
            _b("table", {"columns": ["Occupation", "SOC", "Tasks"],
                         "rows": rows}),
            _b("caption",
               f"Each run issues about {cost.calls} model calls and "
               f"{cost.tokens:,} tokens, and takes {cost.duration_text}."),
        ], label=f"Coverage and run cost ({len(rows)} occupations in scope)"),
        _b("divider"),
    ]


def refusal_blocks(refusal) -> list[Block]:
    """A refusal rendered as an answer, not as an error.

    "That occupation is not published" is a correct response to a reasonable
    question. Presenting it as a crash would teach the customer to distrust the
    system for behaving properly.
    """
    blocks = [
        _b("heading", "No analysis produced"),
        _b("callout", f"**{refusal.code}**\n\n{refusal.message}", tone="warn"),
    ]
    if refusal.in_scope_hint:
        blocks.append(_b("markdown", "**Currently in scope:** "
                         + ", ".join(refusal.in_scope_hint)))
    blocks.append(_b("divider"))
    return blocks


def header_blocks(view: ReportView) -> list[Block]:
    return [
        _b("title", f"Task Exposure & Adoption Lag — {view.occupation_title}"),
        _b("caption", f"SOC {view.soc_code} · run {view.run_id[:8]} · "
                      f"generated {view.generated_on}"),
        _b("markdown",
           "**Customer question.** Which of our cost lines are exposed to "
           "agent substitution, and on what timetable?"),
        _b("markdown",
           "Exposure and timetable are shown as two separate quantities, "
           "computed on independent paths. They are deliberately not combined "
           "into a single score."),
        _b("divider"),
    ]


def standing_blocks(view: ReportView) -> list[Block]:
    """The standing leads, before any figure. Same rule as the document."""
    standing = view.standing
    blocks = [
        _b("heading", "1. Standing of this analysis"),
        # A stamp, not a filled banner. "Analyst review required" is a finding;
        # rendered as a hazard strip it reads as a defect and a client discounts
        # everything printed beneath it. A hairline rule in dark ochre keeps the
        # fact fully visible and reads as rigour.
        _standing(standing.tone, standing.headline, standing.meaning),
    ]
    # The reason moves behind a disclosure. It is three sentences of statistical
    # argument -- essential, and the wrong thing to place between a client and
    # the figure they came for. The standing itself stays on the page.
    if standing.reason:
        blocks.append(_b("expander", [_b("markdown", standing.reason)],
                         label="Why calibration could not adjudicate this"))

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
        _b("heading", "2. Exposure"),
        # A bounded figure with a track, because the index runs 0 to 1.
        _figure("Role exposure index", view.exposure_index,
                note=f"Bounded 0 to 1 · {view.tasks_scored} tasks · "
                     f"{view.weight_source} weighting",
                fill_percent=view.exposure_percent),
        _b("markdown",
           "Exposure measures how much of the role's task content a language "
           "model could in principle perform. It is **not** a probability of "
           "replacement and **not** a timetable — the timetable is section 3, "
           "computed on a path that never reads this number."),
        _b("markdown", f"**Weighting convention.** {view.weighting_note}"),
    ]


def lag_blocks(view: ReportView) -> list[Block]:
    return [
        _b("heading", "3. Adoption lag"),
        # A span with no track, deliberately unlike exposure's meter. The lag is
        # an unbounded interval in years; giving it the same gauge would invite
        # the one comparison this architecture refuses to make.
        _span("Years to reorganisation", view.lag_p10, view.lag_p50,
              view.lag_p90, note="p10 / median / p90 · no curve fitted"),
        _b("markdown",
           "**Computed independently of the exposure index.** The lag path "
           "reads adoption observations and historical diffusion claims; it "
           "has no access to the exposure score. A capability being available "
           "and a firm being reorganised to use it are different events."),
        _b("markdown",
           "**No curve is fitted.** The observed adoption window is too short "
           "to identify a saturation level, so fitting an S-curve would "
           "manufacture precision the data cannot support. The interval is "
           "wide because the evidence is thin."),
        _b("markdown", f"*Basis:* {view.lag_basis}"),
    ] + ([_b("expander", [_b("markdown", view.lag_grounding)],
             label="Historical grounding (claim IDs)")]
         if view.lag_grounding else [])


def calibration_blocks(view: ReportView) -> list[Block]:
    """Calibration stated as an identifiability question, not a pass/fail."""
    blocks = [_b("heading", "4. Calibration")]
    if view.calibration_is_identifiable:
        blocks.append(_b("metrics", [
            {"label": "Our percentile", "value": view.our_percentile},
            {"label": "Benchmark percentile", "value": view.benchmark_percentile},
            {"label": "Delta", "value": view.delta},
        ]))
    else:
        blocks.append(_b(
            "markdown",
            f"Our percentile is **{view.our_percentile}** for this run, so no "
            f"delta against the published benchmark can be computed. This is "
            f"an unidentifiable comparison, not a numeric disagreement — see "
            f"section 1."))
        blocks.append(_b(
            "markdown",
            f"Benchmark measure on file: `{view.benchmark_measure}`."))
    blocks.append(_b("caption",
                     f"Outcome `{view.calibration_outcome}` under policy "
                     f"`{view.calibration_policy_version}`."))
    return blocks


def direction_blocks(view: ReportView) -> list[Block]:
    blocks = [
        _b("heading", "5. Direction: augmentation or substitution"),
        _b("metrics", [
            {"label": "Augmenting", "value": view.direction_augment},
            {"label": "Substituting", "value": view.direction_substitute},
            {"label": "Unclear", "value": view.direction_unclear},
        ]),
        _b("markdown",
           "Direction is *chosen, not given*: the same capability can automate "
           "a task or make the person doing it more productive, and which one "
           "happens is an organisational decision. `unclear` is a first-class "
           "answer — a classifier that cannot tell should say so."),
    ]
    if view.direction_substitute == "0" and view.direction_augment != "0":
        blocks.append(_b(
            "markdown",
            "**No task was judged to be substituted outright.** That is "
            "consistent with the survey prior: among finance firms that "
            "adopted AI, far more reported their workforce becoming more "
            "skilled than reported it shrinking."))
    return blocks


def task_table_blocks(view: ReportView) -> list[Block]:
    return [
        _b("heading", "6. Per-task detail"),
        _b("markdown",
           "`raw` is the Acemoglu–Autor cell score; `tacit` is the Polanyi "
           "penalty subtracted from it; `adjusted` is what enters the index. "
           "Tacitness is a *discount* on exposure: work whose rules nobody can "
           "articulate is work a model cannot be given."),
        _b("table", {
            "columns": ["Task", "Raw", "Tacit", "Adjusted", "Direction",
                        "Confidence"],
            "rows": [[t.statement, t.raw, t.tacit, t.adjusted, t.direction,
                      t.confidence] for t in view.tasks],
        }),
    ]


def limitations_blocks(view: ReportView) -> list[Block]:
    blocks = [
        _b("heading", "7. Limitations"),
        _b("markdown",
           "Properties of the available evidence, not defects in the pipeline. "
           "They are listed because a customer acting on these figures needs "
           "to know where they stop being load-bearing."),
    ]
    for caveat in view.caveats:
        blocks.append(_b("markdown", f"- {caveat}"))
    return blocks


def provenance_blocks(view: ReportView) -> list[Block]:
    """The panel that makes the figures checkable."""
    blocks = [
        _b("heading", "8. Provenance"),
        _b("markdown",
           "Every source below was *consumed* by this run — bound when a tool "
           "returned a row carrying it, not merely available in the "
           "warehouse. Each digest identifies an exact set of bytes."),
        _b("metrics", [
            {"label": "Figures traced", "value": view.trace_figures},
            {"label": "Chain complete",
             "value": "yes" if view.trace_complete else "no"},
            {"label": "Customer deliverable",
             "value": "yes" if view.trace_customer_deliverable else "no"},
        ]),
        _b("table", {
            "columns": ["Source", "Publisher", "Format", "Used as", "SHA-256"],
            "rows": [[f"{s.doc_id}{' (mirror)' if s.is_unverified_mirror else ''}",
                      s.publisher, s.format, s.used_as, s.short_digest]
                     for s in view.sources],
        }),
    ]

    if view.claims:
        inner = [
            _b("markdown",
               "Claims drawn from prose carry the **verbatim quote and page**, "
               "never a paraphrase, so a reader can check the source says what "
               "the analysis reports it saying."),
            _b("caption",
               "Binding granularity: the binding table records which artefact "
               "a tool returned a row from, not which individual quote was "
               "read. This is a source-level trace, stated as such."),
            _b("table", {
                "columns": ["Topic", "Page", "Verbatim quote", "Source"],
                "rows": [[c.topic, c.page, c.quote, c.source_doc_id]
                         for c in view.claims],
            }),
        ]
        blocks.append(_b("expander", inner,
                         label=f"Claim evidence, verbatim ({len(view.claims)})"))

    blocks += [
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
