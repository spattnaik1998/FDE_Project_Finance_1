"""Read a persisted run back out of the warehouse.

The report is rendered from the *database*, never from the in-memory state the
graph produced. That is deliberate: a figure is traceable only if it came from
a row that is still there to be checked. Rendering from live state would
produce a document that looks identical and proves nothing.

Read under ``USR_FDE_SCORE``, which holds SELECT on ``score.*``, ``ref.*``,
``core.*`` and ``audit.run_source_binding`` -- exactly the set a report needs,
and no write grant on anything it reads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from warehouse.session import Principal, connect

LOG = logging.getLogger("report.reader")


class RunNotFound(LookupError):
    """No such run, or the run produced no verdict."""


@dataclass
class SourceRecord:
    """One artefact a run consumed, with the digest that identifies it."""

    doc_id: str
    title: str
    publisher: str
    url: str
    format: str
    sha256: str
    retrieved_at: Any
    is_mirror: bool
    verified_against_publisher: bool
    usage_types: tuple[str, ...] = ()

    @property
    def needs_spot_check(self) -> bool:
        """A mirror nobody checked against the publisher."""
        return self.is_mirror and not self.verified_against_publisher


@dataclass
class ClaimRecord:
    """One prose-derived claim, with the verbatim quote that supports it.

    The project's provenance rule is that a claim drawn from prose carries a
    verbatim quote and a page number, never a paraphrase. This is where that
    rule reaches the customer.
    """

    claim_id: str
    topic: str
    quote: str
    page: int
    source_doc_id: str


@dataclass
class TaskRow:
    """One scored task, joined to the statement it scored."""

    task_id: str
    statement: str
    source_doc_id: str
    exposure_raw: float
    tacitness: float
    exposure_adjusted: float
    direction: str
    confidence: str
    rationale: str
    model: str


@dataclass
class ReportData:
    """Everything the renderer is allowed to draw on."""

    run_id: str
    status: str
    started_at: Any
    finished_at: Any
    git_sha: str
    config_hash: str
    rubric_version: str
    calibration_policy_version: str
    is_customer_deliverable: bool

    soc_code: str
    occupation_title: str
    exposure_index: float
    exposure_percentile: float | None
    lag_p10: float
    lag_p50: float
    lag_p90: float
    lag_basis: str
    augmentation_share: float
    weight_source: str
    caveats: list[str]

    benchmark_measure: str
    benchmark_percentile: float | None
    our_percentile: float | None
    delta: float | None
    within_tolerance: bool
    calibration_outcome: str
    calibration_explanation: str | None

    tasks: list[TaskRow] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)

    @property
    def produced_a_narrative(self) -> bool:
        return self.status == "passed"

    @property
    def calibration_is_identifiable(self) -> bool:
        """Whether a percentile comparison could be made at all.

        Distinct from ``within_tolerance``. An unidentifiable comparison is not
        a disagreement -- there is nothing to disagree with.
        """
        return self.our_percentile is not None

    @property
    def source_ids(self) -> set[str]:
        return {s.doc_id for s in self.sources}

    def source(self, doc_id: str) -> SourceRecord | None:
        return next((s for s in self.sources if s.doc_id == doc_id), None)

    def direction_counts(self) -> dict[str, int]:
        counts = {"augment": 0, "substitute": 0, "unclear": 0}
        for task in self.tasks:
            counts[task.direction] = counts.get(task.direction, 0) + 1
        return counts

    def unverified_mirrors(self) -> list[SourceRecord]:
        return [s for s in self.sources if s.needs_spot_check]


def latest_run_id(*, database: str | None = None,
                  soc_code: str | None = None) -> str | None:
    """The most recent run that actually persisted a verdict."""
    sql = """SELECT TOP 1 CONVERT(NVARCHAR(36), r.run_id)
             FROM score.run r
             JOIN score.role_verdict v ON v.run_id = r.run_id
             WHERE (? IS NULL OR v.soc_code = ?)
             ORDER BY r.started_at DESC"""
    with connect(Principal.SCORE, database=database) as conn:
        row = conn.cursor().execute(sql, soc_code, soc_code).fetchone()
    return row[0] if row else None


def load_run(run_id: str, *, database: str | None = None) -> ReportData:
    """Assemble everything the report may cite, from persisted rows only."""
    with connect(Principal.SCORE, database=database) as conn:
        cursor = conn.cursor()

        head = cursor.execute("""
            SELECT CONVERT(NVARCHAR(36), r.run_id), r.status, r.started_at,
                   r.finished_at, r.git_sha, r.config_hash, r.rubric_version,
                   r.calibration_policy_version, r.is_customer_deliverable,
                   v.soc_code, o.title, v.exposure_index, v.exposure_percentile,
                   v.lag_years_p10, v.lag_years_p50, v.lag_years_p90,
                   v.lag_basis, v.augmentation_share, v.weight_source, v.caveats
            FROM score.run r
            JOIN score.role_verdict v ON v.run_id = r.run_id
            JOIN ref.occupation o     ON o.soc_code = v.soc_code
            WHERE r.run_id = ?""", run_id).fetchone()
        if head is None:
            raise RunNotFound(
                f"run {run_id} has no persisted verdict. A run that halted "
                f"before assembly has nothing to report, which is the correct "
                f"outcome rather than an empty document.")

        cal = cursor.execute("""
            SELECT benchmark_measure, benchmark_percentile, our_percentile,
                   delta, within_tolerance, outcome, explanation
            FROM score.calibration WHERE run_id = ?""", run_id).fetchone()
        if cal is None:
            raise RunNotFound(f"run {run_id} persisted a verdict but no "
                              f"calibration row; the run is incomplete.")

        task_rows = cursor.execute("""
            SELECT ts.task_id, t.statement, ts.source_doc_id, ts.exposure_raw,
                   ts.tacitness, ts.exposure_adjusted, ts.direction,
                   ts.confidence, ts.rationale, ts.model
            FROM score.task_score ts
            JOIN core.task t ON t.task_id = ts.task_id
                            AND t.source_doc_id = ts.source_doc_id
            WHERE ts.run_id = ?
            ORDER BY ts.exposure_adjusted DESC, ts.task_id""", run_id).fetchall()

        source_rows = cursor.execute("""
            SELECT d.doc_id, d.title, d.publisher, d.url, d.format, d.sha256,
                   d.retrieved_at, d.is_mirror, d.verified_against_publisher,
                   STRING_AGG(b.usage_type, ',')
            FROM audit.run_source_binding b
            JOIN ref.source_document d ON d.doc_id = b.source_doc_id
            WHERE b.run_id = ?
            GROUP BY d.doc_id, d.title, d.publisher, d.url, d.format, d.sha256,
                     d.retrieved_at, d.is_mirror, d.verified_against_publisher
            ORDER BY d.doc_id""", run_id).fetchall()

        # Claim evidence is bound at SOURCE granularity, not claim granularity:
        # audit.run_source_binding records which artefact a tool returned a row
        # from, not which individual quote was read. So these are the claims
        # carried by the artefacts this run consumed as claim evidence. The
        # appendix says so rather than implying a finer trace than exists.
        claim_rows = cursor.execute("""
            SELECT c.claim_id, c.topic, c.quote, c.page, c.source_doc_id
            FROM core.extracted_claim c
            JOIN audit.run_source_binding b
              ON b.source_doc_id = c.source_doc_id AND b.run_id = ?
            WHERE b.usage_type = 'claim_evidence' AND c.is_current = 1
            ORDER BY c.source_doc_id, c.page, c.claim_id""", run_id).fetchall()

    data = ReportData(
        run_id=head[0], status=head[1], started_at=head[2], finished_at=head[3],
        git_sha=head[4], config_hash=head[5], rubric_version=head[6],
        calibration_policy_version=head[7], is_customer_deliverable=bool(head[8]),
        soc_code=head[9], occupation_title=head[10],
        exposure_index=float(head[11]),
        exposure_percentile=float(head[12]) if head[12] is not None else None,
        lag_p10=float(head[13]), lag_p50=float(head[14]), lag_p90=float(head[15]),
        lag_basis=head[16], augmentation_share=float(head[17]),
        weight_source=head[18],
        caveats=[c.strip() for c in (head[19] or "").split("\n\n") if c.strip()],
        benchmark_measure=cal[0],
        benchmark_percentile=float(cal[1]) if cal[1] is not None else None,
        our_percentile=float(cal[2]) if cal[2] is not None else None,
        delta=float(cal[3]) if cal[3] is not None else None,
        within_tolerance=bool(cal[4]), calibration_outcome=cal[5],
        calibration_explanation=cal[6],
        tasks=[TaskRow(task_id=r[0], statement=r[1], source_doc_id=r[2],
                       exposure_raw=float(r[3]), tacitness=float(r[4]),
                       exposure_adjusted=float(r[5]), direction=r[6],
                       confidence=r[7], rationale=r[8], model=r[9])
               for r in task_rows],
        sources=[SourceRecord(doc_id=r[0], title=r[1], publisher=r[2], url=r[3],
                              format=r[4], sha256=r[5], retrieved_at=r[6],
                              is_mirror=bool(r[7]),
                              verified_against_publisher=bool(r[8]),
                              usage_types=tuple(sorted(
                                  u for u in (r[9] or "").split(",") if u)))
                 for r in source_rows],
        claims=[ClaimRecord(claim_id=r[0], topic=r[1], quote=r[2],
                            page=int(r[3]), source_doc_id=r[4])
                for r in claim_rows])

    LOG.info("run=%s status=%s tasks=%s sources=%s claims=%s identifiable=%s",
             data.run_id, data.status, len(data.tasks), len(data.sources),
             len(data.claims), data.calibration_is_identifiable)
    return data
