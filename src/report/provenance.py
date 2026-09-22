"""The traceability walk: every reported figure back to a hashed artefact.

Build plan 7.3. The chain is:

    figure -> score.* row -> audit.run_source_binding -> ref.source_document
           -> SHA-256

and the walk fails if any link is missing. Four things can break it, and they
are reported separately because they mean different things:

* ``unregistered`` -- a number appears in the document that the renderer never
  registered. The renderer put a figure in by hand instead of through the
  registry, so nothing knows where it came from.
* ``unbound`` -- a figure cites a source the run never bound. The number may be
  right, but this run did not demonstrably consume that artefact, so the claim
  is unsupported *for this run*.
* ``unhashed`` -- a bound source carries no usable digest, so "the artefact" is
  not a specific set of bytes.
* ``unverified_mirror`` -- the chain completes, but it terminates at a copy
  nobody checked against the publisher. Not a break; a qualification, and one
  that blocks a customer-deliverable run rather than the document as a whole.

``unregistered`` is checked against the rendered text rather than the registry,
so it catches a renderer that bypasses :mod:`report.figures` entirely. Without
that check the walk would only ever validate figures that had already opted in,
which is the vacuous version of this test.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from nodes.figure_guard import STRUCTURAL_MAX, _numbers_in
from report.figures import Figure, FigureRegistry
from report.reader import ReportData

LOG = logging.getLogger("report.provenance")

# Tokens that are document furniture rather than findings: section numbering,
# the SOC code, dates, digests. They are excluded by *pattern*, not by value,
# so a real figure can never be waved through by coincidence.
FURNITURE_CONTEXT = ("SOC ", "sha256", "SHA-256", "git ", "run_id",
                     "Section ", "13-2051", "13-2099")

# A `code span` in this document holds an identifier -- a doc_id, a digest, a
# run id, a rubric version -- never a finding. Findings are rendered as bold or
# as table values, never as code. Numbers inside code spans are therefore
# skipped, and `test_no_code_span_is_purely_numeric` closes the loophole that
# would otherwise open: a renderer cannot smuggle a bare figure into the
# document by wrapping it in backticks, because a numeric-only code span fails
# that test.
CODE_SPAN = re.compile(r"`[^`]*`")


@dataclass
class TraceLink:
    """One figure and the artefacts it resolves to."""

    figure: Figure
    documents: tuple[str, ...]
    digests: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return bool(self.digests) and all(len(d) == 64 for d in self.digests)


@dataclass
class TraceReport:
    """The outcome of walking a rendered report."""

    links: list[TraceLink] = field(default_factory=list)
    unregistered: list[tuple[str, float]] = field(default_factory=list)
    unbound: list[tuple[str, str]] = field(default_factory=list)
    unhashed: list[str] = field(default_factory=list)
    unverified_mirrors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Whether every figure walked all the way to a digest.

        A mirror qualification does not break the walk: the chain resolved, it
        simply terminates somewhere that needs a spot check.
        """
        return (not self.unregistered and not self.unbound
                and not self.unhashed
                and all(link.is_complete for link in self.links))

    @property
    def customer_deliverable(self) -> bool:
        """Stricter than completeness: no unverified mirror may contribute."""
        return self.is_complete and not self.unverified_mirrors

    def summary(self) -> dict:
        return {
            "figures_traced": len(self.links),
            "complete": self.is_complete,
            "customer_deliverable": self.customer_deliverable,
            "unregistered": len(self.unregistered),
            "unbound": len(self.unbound),
            "unhashed": len(self.unhashed),
            "unverified_mirrors": len(self.unverified_mirrors),
        }

    def failure_detail(self) -> str:
        """Why the walk broke, in terms a reviewer can act on."""
        parts = []
        if self.unregistered:
            parts.append("figures in the document with no registered origin: "
                         + ", ".join(f"{lit!r}" for lit, _ in self.unregistered[:8]))
        if self.unbound:
            parts.append("figures citing sources this run never bound: "
                         + ", ".join(f"{lab} -> {doc}" for lab, doc in self.unbound[:8]))
        if self.unhashed:
            parts.append("bound sources without a usable digest: "
                         + ", ".join(self.unhashed[:8]))
        return "; ".join(parts) or "no break detected"


def strip_code_spans(text: str) -> str:
    """Remove `code spans`, which hold identifiers rather than findings."""
    return CODE_SPAN.sub(" ", text)


def numeric_code_spans(markdown: str) -> list[str]:
    """Code spans that are nothing but a number.

    Must always be empty. A figure wrapped in backticks would be skipped by
    the traceability scan, so this is the check that keeps the code-span
    exemption from becoming a hole.
    """
    return [span for span in CODE_SPAN.findall(markdown)
            if re.fullmatch(r"`[\d.,%\s]+`", span)]


def _is_furniture(literal: str, value: float, context: str) -> bool:
    """Whether a number in the text is structure rather than a finding."""
    if value <= STRUCTURAL_MAX and "." not in literal:
        return True                      # counts, list lengths, section numbers
    if any(token in context for token in FURNITURE_CONTEXT):
        return True
    return False


def walk(markdown: str, registry: FigureRegistry,
         data: ReportData) -> TraceReport:
    """Walk every figure in ``markdown`` back to a hashed artefact."""
    report = TraceReport()
    bound = data.source_ids

    for figure in registry.figures:
        digests, documents = [], []
        for doc_id in figure.source_doc_ids:
            if doc_id not in bound:
                report.unbound.append((figure.label, doc_id))
                continue
            record = data.source(doc_id)
            documents.append(doc_id)
            if record is None or not record.sha256 or len(record.sha256) != 64:
                report.unhashed.append(doc_id)
                continue
            digests.append(record.sha256)
            if record.needs_spot_check:
                report.unverified_mirrors.append(doc_id)
        report.links.append(TraceLink(figure=figure,
                                      documents=tuple(documents),
                                      digests=tuple(digests)))

    registered = registry.literals()
    for line in markdown.splitlines():
        for literal, value in _numbers_in(strip_code_spans(line)):
            if literal in registered or _is_furniture(literal, value, line):
                continue
            # A figure may be registered under a different literal spelling
            # (0.541 registered, "0.54" written). Match on value too.
            if any(abs(value - known) < 1e-9 for known in registry.values()):
                continue
            report.unregistered.append((literal, value))

    LOG.info("traceability figures=%s complete=%s unregistered=%s unbound=%s",
             len(report.links), report.is_complete, len(report.unregistered),
             len(report.unbound))
    return report
