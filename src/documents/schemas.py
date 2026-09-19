"""Typed contracts for heterogeneous source material.

Six sources arrive as fixed-width text, Excel workbooks and PDFs.  Everything
normalises into the models below, so downstream code -- and eventually the
agent's tools -- never sees "a PDF" or "a spreadsheet", only :class:`Task`,
:class:`ExposureEstimate`, :class:`AdoptionObservation` and
:class:`ExtractedClaim`.

Every record carries ``source_doc_id`` back to a :class:`SourceDocument`, and
every prose-derived claim carries a verbatim quote and page number, so nothing
in the final output has to be asserted without provenance.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DocumentFormat(str, Enum):
    """Wire format a source arrived in."""

    PDF = "pdf"
    XLSX = "xlsx"
    TSV = "tsv"
    CSV = "csv"
    MARKDOWN = "markdown"
    HTML = "html"


class SourceDocument(BaseModel):
    """One retrieved artefact, identified well enough to re-fetch and verify."""

    doc_id: str = Field(description="Stable slug, e.g. 'onet_task_statements'")
    title: str
    publisher: str
    url: str
    format: DocumentFormat
    local_path: str
    sha256: str = Field(description="Digest of the bytes as retrieved")
    bytes: int
    retrieved_at: datetime
    provenance_note: str = Field(
        default="",
        description="Anything a reader needs in order to trust or discount this "
                    "source -- mirrors, third-party republication, licence terms.",
    )


class Task(BaseModel):
    """A single task statement attached to an occupation."""

    task_id: str
    soc_code: str = Field(description="O*NET-SOC code, e.g. '13-2051.00'")
    occupation: str
    statement: str
    task_type: str | None = Field(
        default=None, description="O*NET 'Core' or 'Supplemental'")
    importance: float | None = Field(
        default=None, ge=0, le=5, description="Mean importance rating, 1-5 scale")
    relevance_pct: float | None = Field(
        default=None, ge=0, le=100,
        description="Share of incumbents reporting the task as relevant")
    source_doc_id: str

    @field_validator("statement")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("task statement must not be empty")
        return v.strip()


class ExposureEstimate(BaseModel):
    """A published occupation-level exposure score.

    Kept deliberately generic: these measures use different scales and different
    definitions of "exposure", and forcing them onto a common scale here would
    destroy exactly the information needed to compare them honestly.
    """

    soc_code: str
    occupation: str | None = None
    measure: str = Field(description="e.g. 'AIOE', 'AIOE_language_modeling'")
    value: float
    scale_note: str = Field(
        description="What the number means and its range -- required, because "
                    "these measures are not mutually comparable without it.")
    source_doc_id: str


class AdoptionObservation(BaseModel):
    """A measured technology-adoption rate for a sector and period."""

    period: str = Field(description="Survey reference period as published")
    period_start: date | None = None
    sector_code: str | None = None
    sector_label: str
    measure: str = Field(description="e.g. 'AI use in producing goods/services'")
    value: float
    unit: Literal["percent", "count"] = "percent"
    geography: str = "US"
    source_doc_id: str


class ExtractedClaim(BaseModel):
    """A claim taken from prose, with the evidence needed to check it.

    The quote is stored verbatim and unedited.  A claim without a quote and a
    page number is not admissible downstream -- that is the whole point of the
    model.
    """

    claim_id: str
    topic: str = Field(description="What this claim is evidence about")
    quote: str = Field(description="Verbatim sentence(s) from the document")
    page: int = Field(ge=1)
    source_doc_id: str
    note: str = Field(default="", description="Why this was extracted")

    @field_validator("quote")
    @classmethod
    def _substantive(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("quote too short to be checkable")
        return v.strip()


class Corpus(BaseModel):
    """Everything normalised, in one serialisable object."""

    documents: list[SourceDocument] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    exposure_estimates: list[ExposureEstimate] = Field(default_factory=list)
    adoption_observations: list[AdoptionObservation] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "documents": len(self.documents),
            "tasks": len(self.tasks),
            "exposure_estimates": len(self.exposure_estimates),
            "adoption_observations": len(self.adoption_observations),
            "claims": len(self.claims),
        }
