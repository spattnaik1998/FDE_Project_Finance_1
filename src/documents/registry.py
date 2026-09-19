"""The document source registry and downloader.

Declaring sources as data rather than as code keeps the "what we pull" decision
separate from the "how we parse it" decision, and makes the provenance notes
impossible to lose: they live next to the URL.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from documents.schemas import DocumentFormat, SourceDocument

LOG = logging.getLogger("documents")

# Some publishers reject the default requests user-agent outright.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 180
CHUNK = 1 << 16


@dataclass(frozen=True)
class DocumentSource:
    """A declared source: where it lives, what it is, and how far to trust it."""

    doc_id: str
    title: str
    publisher: str
    url: str
    format: DocumentFormat
    filename: str
    purpose: str
    provenance_note: str = ""
    headers: dict[str, str] = field(default_factory=dict)


ONET_BASE = "https://www.onetcenter.org/dl_files/database/db_29_3_text"
AIOE_MIRROR = ("https://raw.githubusercontent.com/nikolajtranholmmikkelsen/"
               "AI-exposure-LLM-v-academic/main/data/felten")

SOURCES: list[DocumentSource] = [
    DocumentSource(
        doc_id="onet_task_statements",
        title="O*NET 29.3 Task Statements",
        publisher="O*NET Resource Center / US Department of Labor",
        url=f"{ONET_BASE}/Task%20Statements.txt",
        format=DocumentFormat.TSV,
        filename="onet_task_statements.txt",
        purpose="The task list itself: the unit of analysis for the exposure score.",
        provenance_note="Public domain under the O*NET data licence; "
                        "tab-separated with a header row.",
    ),
    DocumentSource(
        doc_id="onet_task_ratings",
        title="O*NET 29.3 Task Ratings",
        publisher="O*NET Resource Center / US Department of Labor",
        url=f"{ONET_BASE}/Task%20Ratings.txt",
        format=DocumentFormat.TSV,
        filename="onet_task_ratings.txt",
        purpose="Importance and relevance ratings, so tasks can be weighted "
                "rather than counted equally.",
    ),
    DocumentSource(
        doc_id="onet_occupation_data",
        title="O*NET 29.3 Occupation Data",
        publisher="O*NET Resource Center / US Department of Labor",
        url=f"{ONET_BASE}/Occupation%20Data.txt",
        format=DocumentFormat.TSV,
        filename="onet_occupation_data.txt",
        purpose="Occupation titles and descriptions for SOC lookup.",
    ),
    DocumentSource(
        doc_id="eloundou_gpts_are_gpts",
        title="GPTs are GPTs: An Early Look at the Labor Market Impact "
              "Potential of Large Language Models",
        publisher="Eloundou, Manning, Mishkin & Rock (arXiv:2303.10130)",
        url="https://arxiv.org/pdf/2303.10130",
        format=DocumentFormat.PDF,
        filename="eloundou_gpts_are_gpts.pdf",
        purpose="An independent, task-level LLM exposure benchmark to check our "
                "own rubric against before we trust it.",
        provenance_note="arXiv preprint; cite by version. Exposure figures live "
                        "in the body and appendix tables.",
    ),
    DocumentSource(
        doc_id="felten_aioe_language_modeling",
        title="Language Modeling AIOE and AIIE (Felten, Raj & Seamans appendix)",
        publisher="Felten, Raj & Seamans, via third-party research mirror",
        url=f"{AIOE_MIRROR}/Language%20Modeling%20AIOE%20and%20AIIE.xlsx",
        format=DocumentFormat.XLSX,
        filename="felten_aioe_language_modeling.xlsx",
        purpose="Occupation-level exposure specific to language modelling -- the "
                "closest published proxy for LLM exposure by SOC code.",
        provenance_note="MIRROR, not the publisher's own copy. Retrieved from a "
                        "third-party reproducibility repository, so values must "
                        "be spot-checked against the original paper before any "
                        "customer-facing use.",
    ),
    DocumentSource(
        doc_id="felten_aioe_appendix",
        title="AIOE Data Appendix (Felten, Raj & Seamans)",
        publisher="Felten, Raj & Seamans, via third-party research mirror",
        url=f"{AIOE_MIRROR}/AIOE_DataAppendix.xlsx",
        format=DocumentFormat.XLSX,
        filename="felten_aioe_appendix.xlsx",
        purpose="The general AI Occupational Exposure index, as a second and "
                "broader benchmark.",
        provenance_note="MIRROR, not the publisher's own copy -- same caveat as "
                        "the language-modelling file.",
    ),
    DocumentSource(
        doc_id="btos_national",
        title="Business Trends and Outlook Survey - National",
        publisher="US Census Bureau",
        url="https://www.census.gov/hfp/btos/downloads/National.xlsx",
        format=DocumentFormat.XLSX,
        filename="btos_national.xlsx",
        purpose="Current AI-use rates. Closes the gap left by ABS, whose latest "
                "technology vintage is 2020 and therefore pre-LLM.",
        provenance_note="Published as flat files only; not exposed on the "
                        "Census API.",
    ),
    DocumentSource(
        doc_id="btos_sector",
        title="Business Trends and Outlook Survey - by Sector",
        publisher="US Census Bureau",
        url="https://www.census.gov/hfp/btos/downloads/Sector.xlsx",
        format=DocumentFormat.XLSX,
        filename="btos_sector.xlsx",
        purpose="The same AI-use rates split by NAICS sector, so finance can be "
                "read directly.",
    ),
    DocumentSource(
        doc_id="brynjolfsson_productivity_j_curve",
        title="The Productivity J-Curve: How Intangibles Complement General "
              "Purpose Technologies",
        publisher="Brynjolfsson, Rock & Syverson (NBER Working Paper 25148)",
        url="https://www.nber.org/system/files/working_papers/w25148/w25148.pdf",
        format=DocumentFormat.PDF,
        filename="brynjolfsson_productivity_j_curve.pdf",
        purpose="The adoption-lag argument, quantified. Substitutes for David's "
                "electrification paper, which has no open copy, and connects "
                "directly to the BEA intangibles series we already hold.",
        provenance_note="NBER working paper; not peer reviewed at time of issue.",
    ),
]


def _digest_and_write(response: requests.Response, path: Path) -> tuple[str, int]:
    """Stream to disk while hashing, so large files never sit in memory twice."""
    sha = hashlib.sha256()
    total = 0
    with path.open("wb") as handle:
        for chunk in response.iter_content(CHUNK):
            if not chunk:
                continue
            handle.write(chunk)
            sha.update(chunk)
            total += len(chunk)
    return sha.hexdigest(), total


def download(source: DocumentSource, dest_dir: Path,
             force: bool = False) -> SourceDocument:
    """Retrieve one source, returning its :class:`SourceDocument` record.

    Raises on failure rather than returning a partial record: a document we
    could not retrieve must not silently become a document with no content.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / source.filename

    if path.exists() and not force:
        data = path.read_bytes()
        LOG.info("doc=%s status=cached bytes=%s", source.doc_id, len(data))
        return SourceDocument(
            doc_id=source.doc_id, title=source.title, publisher=source.publisher,
            url=source.url, format=source.format, local_path=str(path),
            sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
            retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
            provenance_note=source.provenance_note,
        )

    headers = {"User-Agent": USER_AGENT, **source.headers}
    response = requests.get(source.url, headers=headers, timeout=TIMEOUT, stream=True)
    if response.status_code != 200:
        raise RuntimeError(
            f"{source.doc_id}: HTTP {response.status_code} from {source.url}")

    sha, total = _digest_and_write(response, path)
    LOG.info("doc=%s status=downloaded bytes=%s sha256=%s",
             source.doc_id, total, sha[:12])

    return SourceDocument(
        doc_id=source.doc_id, title=source.title, publisher=source.publisher,
        url=source.url, format=source.format, local_path=str(path),
        sha256=sha, bytes=total, retrieved_at=datetime.now(timezone.utc),
        provenance_note=source.provenance_note,
    )
