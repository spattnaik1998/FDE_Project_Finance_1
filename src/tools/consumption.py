"""Consumption tracking: which sources a run actually drew on.

``audit.run_source_binding`` exists to answer *which immutable source versions
produced this figure* relationally, rather than by parsing an audit blob. The
architect's condition was that a source is bound when evidence from it
**actually participates in the result**, not merely because it sat in the
warehouse — otherwise the binding degenerates into a list of everything loaded.

**The operational definition used here:** a source is consumed when a tool
*returns* a row carrying its ``Source_Doc_ID`` to the caller. That is a
judgment call and worth stating plainly. A stricter reading would bind only
what the model demonstrably reasoned over, which is unobservable; a looser one
would bind the whole warehouse. Returned-to-the-caller is the narrowest
boundary that can actually be measured, and a tool returning zero rows binds
nothing.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

LOG = logging.getLogger("tools.consumption")


class UsageType(str, Enum):
    """The ``usage_type`` vocabulary, matching the CHECK constraint on the table."""

    TASK_SOURCE = "task_source"
    EXPOSURE_BENCHMARK = "exposure_benchmark"
    ADOPTION_EVIDENCE = "adoption_evidence"
    CLAIM_EVIDENCE = "claim_evidence"
    INDUSTRY_METRIC = "industry_metric"


@dataclass
class ConsumptionTracker:
    """Accumulates the source versions a run consumed, by usage type.

    Deliberately additive and idempotent: recording the same source twice under
    the same usage type is a no-op, so a tool called repeatedly does not inflate
    the binding.
    """

    run_id: str | None = None
    _consumed: dict[UsageType, set[str]] = field(
        default_factory=lambda: defaultdict(set))

    def record(self, usage: UsageType, doc_ids) -> int:
        """Register source documents as consumed. Returns how many were new."""
        if isinstance(doc_ids, str):
            doc_ids = [doc_ids]
        incoming = {d for d in doc_ids if d}
        before = len(self._consumed[usage])
        self._consumed[usage] |= incoming
        added = len(self._consumed[usage]) - before
        if added:
            LOG.info("run_id=%s usage=%s status=consumed new=%s total=%s",
                     self.run_id, usage.value, added, len(self._consumed[usage]))
        return added

    def record_rows(self, usage: UsageType, rows: list[dict],
                    column: str = "Source_Doc_ID") -> int:
        """Register the sources of rows a tool is about to return.

        Raises if a row lacks the provenance column: a row that cannot say where
        it came from must not reach the caller, because it could then appear in
        an output with no traceable origin.
        """
        missing = [i for i, row in enumerate(rows) if not row.get(column)]
        if missing:
            raise ProvenanceMissing(
                f"{len(missing)} row(s) from a {usage.value} tool carry no "
                f"{column}; an unprovenanced row must not reach the caller")
        return self.record(usage, [row[column] for row in rows])

    # -- reads -------------------------------------------------------------

    def as_dict(self) -> dict[str, set[str]]:
        """Shape expected by ``scoring.run.bind_sources``."""
        return {usage.value: set(docs) for usage, docs in self._consumed.items()
                if docs}

    @property
    def total_sources(self) -> int:
        """Distinct sources across all usage types."""
        return len({doc for docs in self._consumed.values() for doc in docs})

    @property
    def total_bindings(self) -> int:
        """Rows that would be written: one per (source, usage_type) pair."""
        return sum(len(docs) for docs in self._consumed.values())

    def sources_for(self, usage: UsageType) -> set[str]:
        return set(self._consumed[usage])

    def is_empty(self) -> bool:
        return self.total_bindings == 0

    def summary(self) -> dict:
        return {"run_id": self.run_id,
                "distinct_sources": self.total_sources,
                "bindings": self.total_bindings,
                "by_usage": {u.value: len(d) for u, d in self._consumed.items() if d}}


class ProvenanceMissing(RuntimeError):
    """A row reached the tool layer without a resolvable source document."""
