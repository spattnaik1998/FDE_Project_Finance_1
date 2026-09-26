"""The boundary object between the application tier and the UI.

Everything here is a plain value: strings already formatted, numbers already
rounded, booleans already decided. No database handle, no live connection, no
model client. The UI receives one of these and renders it.

That is what makes "the presentation tier does not touch the database"
enforceable rather than aspirational. The tiers are logical and co-located in a
single process (TDD 4.1, "in-process call"), so nothing physically stops a UI
module from opening a cursor. What stops it is that the UI is handed a
:class:`ReportView` and has nothing else to work with --- and
``tests/test_app.py`` parses the UI module and fails if it imports a database
library or contains SQL.

The second rule is that the UI **renders no figure it did not receive**. Every
number a viewer sees is a string on this object, formatted upstream by the
report renderer's figure registry, which already refused to produce any figure
lacking provenance. The UI does no arithmetic, so it cannot invent a quantity
and cannot round one into a different claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskRowView:
    """One row of the per-task table, pre-formatted."""

    statement: str
    raw: str
    tacit: str
    adjusted: str
    direction: str
    confidence: str
    # The net exposure as a CSS width, so the table can show the shape of the
    # distribution without the presentation layer computing anything. Formatted
    # by the gateway, which is the tier that already holds the traced figures.
    exposure_bar: str = "0%"


@dataclass(frozen=True)
class SourceView:
    """One artefact in the provenance panel."""

    doc_id: str
    title: str
    publisher: str
    url: str
    format: str
    sha256: str
    used_as: str
    is_unverified_mirror: bool

    @property
    def short_digest(self) -> str:
        return f"{self.sha256[:16]}…" if self.sha256 else "(no digest)"


@dataclass(frozen=True)
class ClaimView:
    """One prose-derived claim, with the verbatim quote and its page."""

    claim_id: str
    topic: str
    quote: str
    page: str
    source_doc_id: str


@dataclass(frozen=True)
class StandingView:
    """How much weight the document can carry, said plainly."""

    headline: str
    meaning: str
    tone: str                 # 'ok' | 'warn' | 'stop'
    reason: str | None = None       # why, in a business reader's terms
    workings: str | None = None     # the statistical argument, one level down


@dataclass(frozen=True)
class ReportView:
    """Everything the UI is allowed to display.

    ``figures`` is the set of every numeric literal that legitimately appears,
    carried so a test can assert the UI displayed nothing outside it.
    """

    run_id: str
    status: str
    soc_code: str
    occupation_title: str
    generated_on: str

    standing: StandingView

    exposure_index: str
    weight_source: str
    weighting_note: str
    tasks_scored: str

    lag_p10: str
    lag_p50: str
    lag_p90: str
    lag_basis: str
    lag_grounding: str        # raw claim IDs; the join keys, not for a reader
    curve_fitted: bool

    calibration_outcome: str
    calibration_is_identifiable: bool
    benchmark_measure: str
    benchmark_percentile: str
    our_percentile: str
    delta: str

    direction_augment: str
    direction_substitute: str
    direction_unclear: str

    tasks: tuple[TaskRowView, ...] = ()
    sources: tuple[SourceView, ...] = ()
    claims: tuple[ClaimView, ...] = ()
    caveats: tuple[str, ...] = ()

    trace_figures: str = "0"
    trace_complete: bool = False
    trace_customer_deliverable: bool = False
    # Whether this run used the full model profile. Clearance to send a document
    # out is not a provenance property alone: the Review Gate also refuses to
    # release a run made on the development model, and the page has to agree with
    # the gate rather than contradict it.
    #
    # Defaults False, which is the safe direction: the question this answers is
    # "may I send this out", and an unset flag is not a yes.
    full_model_profile: bool = False
    trace_detail: str = ""

    git_sha: str = ""
    rubric_version: str = ""
    calibration_policy_version: str = ""
    is_customer_deliverable: bool = False

    figures: frozenset[str] = field(default_factory=frozenset)
    markdown: str = ""

    @property
    def unverified_mirrors(self) -> tuple[SourceView, ...]:
        return tuple(s for s in self.sources if s.is_unverified_mirror)

    @property
    def exposure_percent(self) -> str:
        """The index as a CSS width, so the view layer does no arithmetic.

        Computed here rather than in blocks.py, which is forbidden from
        arithmetic: a presentation layer that can compute can produce a figure
        that is on no source.
        """
        try:
            return f"{float(self.exposure_index) * 100:.1f}%"
        except (TypeError, ValueError):
            return "0%"

    @property
    def lag_grounding_count(self) -> str:
        """How many historical passages the interval rests on.

        The raw ``lag_grounding`` string is a comma-separated list of claim IDs
        like ``brynjolfsson_productivity_j_curve:lag_length:6:0:v2``. Those are
        join keys. Printing them in a client-facing disclosure --- which is what
        the page did --- is the clearest possible signal that nobody wrote this
        page, so the reader gets the count and the appendix carries the wording.
        """
        if not self.lag_grounding:
            return "0"
        return str(len([part for part in self.lag_grounding.split(",")
                        if part.strip()]))


    @property
    def exposure_share_text(self) -> str:
        """The index as a whole-number share, for prose.

        "roughly 38%" is what a reader can carry out of the room; "0.384" is what
        the arithmetic produced. Both are the same provenanced quantity, and the
        gateway adds this rendering to the traced set so prose cannot introduce a
        figure the report never sourced.
        """
        try:
            return f"{round(float(self.exposure_index) * 100)}%"
        except (TypeError, ValueError):
            return "an unknown share"

    @property
    def lag_interval(self) -> str:
        return f"{self.lag_p10} – {self.lag_p90} years (median {self.lag_p50})"

    @property
    def has_warnings(self) -> bool:
        return bool(self.unverified_mirrors) or not self.trace_complete
