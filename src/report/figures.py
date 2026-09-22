"""A figure that knows where it came from.

The traceability requirement (TDD 3.3, build plan 7.3) is that any number a
customer reads can be walked back to a hashed artefact. There are two ways to
build that: render prose and then parse the numbers back out, or make a figure
carry its provenance at the moment it is emitted.

Parsing back out is what ``nodes/figure_guard.py`` does, and it is the right
tool *there* -- a model writes the narrative, so the numbers have to be
audited after the fact. Here the renderer is ours. A figure that cannot state
its origin should not be renderable at all, so the registry below is the only
way to put a number into the report.

The distinction matters for what a failure means. A missing provenance chain
here is a bug in the renderer, caught at construction; in the narrative path it
is a model fabricating, caught at inspection.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class UntraceableFigure(RuntimeError):
    """Raised when a figure is registered without a resolvable origin."""


@dataclass(frozen=True)
class Figure:
    """One number in the report, with the chain that justifies it."""

    value: float
    literal: str                 # exactly as it appears in the document
    label: str                   # what it measures, in words
    origin: str                  # 'score.role_verdict.exposure_index'
    source_doc_ids: tuple[str, ...] = ()
    derivation: str | None = None   # set when computed from persisted rows

    @property
    def is_derived(self) -> bool:
        return self.derivation is not None


@dataclass
class FigureRegistry:
    """Every figure the renderer emitted, in order.

    ``emit`` returns the formatted string *and* records it, so the only way to
    get a number into the document is to say where it came from. A figure with
    no source documents is refused rather than rendered, because an
    unprovenanced number is precisely what this project treats as
    unrepresentable.
    """

    figures: list[Figure] = field(default_factory=list)

    def emit(self, value: float | None, *, label: str, origin: str,
             source_doc_ids: tuple[str, ...] | list[str] = (),
             derivation: str | None = None, spec: str = ".3f",
             absent: str = "not identifiable") -> str:
        """Format a value, register its provenance, and return the literal.

        ``None`` renders as ``absent`` and registers nothing. That is the whole
        point of the null-vs-zero fix: an unidentifiable quantity has no
        figure, so it cannot acquire a provenance chain it does not deserve.
        """
        if value is None:
            return absent

        literal = format(value, spec)
        if not source_doc_ids:
            raise UntraceableFigure(
                f"refusing to render {label!r} ({literal}) from {origin!r}: no "
                f"source document. A figure without provenance is not "
                f"renderable.")

        self.figures.append(Figure(
            value=float(value), literal=literal, label=label, origin=origin,
            source_doc_ids=tuple(source_doc_ids), derivation=derivation))
        return literal

    def emit_prose(self, text: str | None, *, label: str, origin: str,
                   source_doc_ids: tuple[str, ...] | list[str] = ()) -> str:
        """Register every number inside a persisted prose field, then return it.

        Prose columns such as ``lag_basis`` and ``caveats`` legitimately carry
        figures -- "29.9% in June 2025 rising to 36.5% in April 2026" is the
        evidence for the lag, written out. Those numbers are traceable: they
        are in the document because a persisted column says so, and that
        column is bound to the same sources as the value it explains.

        The alternative was to exempt prose from the traceability scan, which
        would have made the scan meaningless -- anything could be smuggled in
        by writing it as a sentence.
        """
        if not text:
            return ""
        if not source_doc_ids:
            raise UntraceableFigure(
                f"refusing to render prose {label!r} from {origin!r} without a "
                f"source document; it contains figures.")

        from nodes.figure_guard import _numbers_in
        seen: set[str] = set()
        for literal, value in _numbers_in(text):
            if literal in seen:
                continue
            seen.add(literal)
            self.figures.append(Figure(
                value=float(value), literal=literal,
                label=f"{label} (in prose)", origin=origin,
                source_doc_ids=tuple(source_doc_ids),
                derivation=f"quoted within {origin}"))
        return text

    def literals(self) -> set[str]:
        return {f.literal for f in self.figures}

    def values(self) -> set[float]:
        return {f.value for f in self.figures}

    def by_origin(self, origin: str) -> list[Figure]:
        return [f for f in self.figures if f.origin == origin]

    def __len__(self) -> int:
        return len(self.figures)
