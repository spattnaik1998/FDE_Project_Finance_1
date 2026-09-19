"""PDF adapter: extract checkable claims, never free-floating assertions.

This module deliberately does *not* summarise or paraphrase.  It locates
sentences matching a topic's search terms and returns them verbatim with the
page they came from, so every downstream claim can be traced to a specific line
on a specific page of a specific document.

Paraphrase is where fabricated citations come from.  Keeping extraction purely
mechanical means an LLM later in the pipeline can reason *over* quotes it did
not invent, rather than generating claims and attributing them after the fact.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from documents.schemas import ExtractedClaim

LOG = logging.getLogger("documents.pdf")

# Sentence splitter that tolerates the abbreviations common in academic prose.
_ABBREV = r"(?<!\b[A-Z])(?<!\bet al)(?<!\bFig)(?<!\bTab)(?<!\bNo)(?<!\bvs)(?<!\bi\.e)(?<!\be\.g)"
SENTENCE_END = re.compile(rf"{_ABBREV}(?<=[.!?])\s+(?=[A-Z(])")

MIN_SENTENCE = 40
MAX_SENTENCE = 700

# pdfplumber's default x_tolerance of 3 merges words together in tightly
# kerned, justified academic typesetting -- "economicimpactwithout..." -- which
# silently corrupts every quote taken from those lines.  1.5 recovers the
# spacing on the papers in this corpus.
X_TOLERANCE = 1.5

# A token this long with no hyphen is almost certainly merged words, not a
# real word, so it is the signal that extraction went wrong on a page.
RUNON_LEN = 28


@dataclass(frozen=True)
class ClaimTopic:
    """A thing we want evidence about, and the terms that would signal it."""

    topic: str
    terms: tuple[str, ...]
    note: str = ""
    require_number: bool = False


def _runon_ratio(text: str) -> float:
    """Share of tokens that look like merged words -- an extraction-quality gauge."""
    tokens = [t for t in text.split() if t]
    if not tokens:
        return 0.0
    bad = sum(1 for t in tokens if len(t) >= RUNON_LEN and "-" not in t)
    return bad / len(tokens)


def extract_pages(path: str | Path, max_pages: int | None = None) -> list[str]:
    """Return per-page text. Index 0 is page 1.

    Warns when a page still looks like it lost its inter-word spacing, so a
    corrupted extraction surfaces as a log line instead of as a plausible but
    wrong quotation downstream.
    """
    pages: list[str] = []
    suspect = 0
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            if max_pages is not None and i >= max_pages:
                break
            text = page.extract_text(x_tolerance=X_TOLERANCE) or ""
            if _runon_ratio(text) > 0.02:
                suspect += 1
            pages.append(text)

    if suspect:
        LOG.warning("source=pdf status=extraction_suspect path=%s pages_affected=%s",
                    Path(path).name, suspect)
    LOG.info("source=pdf status=ok path=%s pages=%s", Path(path).name, len(pages))
    return pages


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"-\n(\w)", r"\1", text)        # rejoin hyphenated line breaks
    flat = re.sub(r"\s+", " ", flat).strip()
    return [s.strip() for s in SENTENCE_END.split(flat) if s.strip()]


def find_claims(path: str | Path, topics: list[ClaimTopic], source_doc_id: str,
                max_per_topic: int = 3,
                max_pages: int | None = None) -> list[ExtractedClaim]:
    """Find verbatim sentences matching each topic, with page numbers.

    ``require_number`` restricts a topic to sentences containing a digit, which
    is how you keep "productivity grew substantially" out of a slot meant for a
    measured magnitude.
    """
    pages = extract_pages(path, max_pages=max_pages)
    claims: list[ExtractedClaim] = []

    for topic in topics:
        found = 0
        seen: set[str] = set()

        for page_no, page_text in enumerate(pages, start=1):
            if found >= max_per_topic:
                break
            for sentence in _sentences(page_text):
                if found >= max_per_topic:
                    break
                if not (MIN_SENTENCE <= len(sentence) <= MAX_SENTENCE):
                    continue
                lowered = sentence.lower()
                if not any(term.lower() in lowered for term in topic.terms):
                    continue
                if topic.require_number and not re.search(r"\d", sentence):
                    continue
                if _runon_ratio(sentence) > 0.0:
                    LOG.warning("source=pdf status=quote_rejected reason=runon page=%s",
                                page_no)
                    continue

                key = lowered[:120]
                if key in seen:
                    continue
                seen.add(key)

                claims.append(ExtractedClaim(
                    claim_id=f"{source_doc_id}:{topic.topic}:{page_no}:{found}",
                    topic=topic.topic,
                    quote=sentence,
                    page=page_no,
                    source_doc_id=source_doc_id,
                    note=topic.note,
                ))
                found += 1

        if found == 0:
            LOG.warning("source=pdf status=no_match topic=%s doc=%s",
                        topic.topic, source_doc_id)

    LOG.info("source=pdf status=ok doc=%s claims=%s", source_doc_id, len(claims))
    return claims


# Topics we want evidence for, stated as search intent rather than conclusions.
ELOUNDOU_TOPICS = [
    ClaimTopic("exposure_definition",
               ("we define exposure", "exposure as a measure", "definition of exposure"),
               "How the paper defines exposure -- needed before borrowing the number."),
    ClaimTopic("exposure_share",
               ("of all workers", "percent of workers", "% of workers", "of the workforce"),
               "Headline magnitude of workforce exposure.", require_number=True),
    ClaimTopic("not_prediction",
               ("do not make predictions", "does not imply", "not a prediction",
                "limitation", "we caution", "should not be interpreted",
                "no claim", "does not predict"),
               "The authors' own limits on the measure -- these must travel with it."),
    ClaimTopic("occupation_level",
               ("financial", "analyst", "occupations with the highest"),
               "Occupation-level findings relevant to our target role."),
]

J_CURVE_TOPICS = [
    ClaimTopic("intangible_complement",
               ("complementary", "intangible", "co-invention", "organizational capital"),
               "The complementary-investment mechanism behind the lag."),
    ClaimTopic("lag_length",
               ("years", "decade", "lag"),
               "How long the lag runs -- the anchor for our timetable.",
               require_number=True),
    ClaimTopic("mismeasurement",
               ("mismeasure", "understate", "productivity growth is"),
               "Why measured productivity understates during the build-out phase."),
    ClaimTopic("j_curve_definition",
               ("j-curve", "j curve"),
               "The shape itself, in the authors' words."),
]
