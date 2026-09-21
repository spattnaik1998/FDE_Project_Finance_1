"""The agent's entire data surface: six read tools over five views.

Three properties are enforced here rather than assumed:

* **Scope.** Every query targets one of the five published views. The view
  names are a whitelist checked before execution, so a tool cannot be made to
  read a base table even by a caller that wants it to. Of the twenty datasets
  landed from the APIs, only this use case's are reachable.
* **Provenance.** Every row carries ``Source_Doc_ID``, and a row without one
  raises rather than being returned. An unprovenanced row could otherwise
  appear in an output with no traceable origin.
* **Consumption.** Returning rows registers their sources with the tracker, so
  ``audit.run_source_binding`` records what a run drew on rather than what
  happened to be loaded.

Tools return plain dictionaries. The typed contracts belong to the scoring
service; the agent sees evidence, not domain objects it could construct.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import pyodbc

from tools.audit_adapter import AuditAdapter, NullAuditAdapter
from tools.consumption import ConsumptionTracker, UsageType
from warehouse.session import Principal, connect

LOG = logging.getLogger("tools.evidence")

# The only objects a tool may read. Anything else is out of scope by
# construction, not by convention.
ALLOWED_VIEWS = frozenset({
    "dbo.VW_ROLE_TASKS",
    "dbo.VW_EXPOSURE_BENCHMARK",
    "dbo.VW_ADOPTION_CURVE",
    "dbo.VW_CLAIM_EVIDENCE",
    "dbo.VW_INDUSTRY_METRIC",
    # ref.source_document is readable through get_source_document so a citation
    # can be resolved to its digest and publisher. It is reference metadata,
    # not evidence, and carries no facts.
    "ref.source_document",
})

MAX_ROWS = 2000


class ToolScopeViolation(RuntimeError):
    """A tool tried to read outside the published surface."""


class ToolError(RuntimeError):
    """A tool could not answer. Raised rather than returning an empty result."""


@dataclass
class ToolResult:
    """What a tool returns, plus what it cost and where it came from."""

    tool: str
    rows: list[dict]
    duration_ms: int
    sources: set[str]
    truncated: bool = False
    note: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)


class EvidenceTools:
    """The six read tools, bound to a run and a consumption tracker.

    Connects as ``USR_FDE_RO``, which is denied every base table. Until
    mixed-mode authentication is enabled the session layer substitutes the
    developer credential and logs a warning, so the weaker guarantee is visible
    rather than assumed.
    """

    def __init__(self, tracker: ConsumptionTracker | None = None,
                 audit: AuditAdapter | None = None,
                 node: str = "evidence_retrieval",
                 database: str | None = None):
        self.tracker = tracker or ConsumptionTracker()
        self.audit = audit or NullAuditAdapter(run_id=self.tracker.run_id)
        self.node = node
        self._database = database
        self._fulltext: bool | None = None

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _assert_in_scope(*objects: str) -> None:
        outside = [o for o in objects if o not in ALLOWED_VIEWS]
        if outside:
            raise ToolScopeViolation(
                f"Tool queries must target the published surface; "
                f"{', '.join(outside)} is outside it. Allowed: "
                f"{', '.join(sorted(ALLOWED_VIEWS))}")

    def _query(self, sql: str, params: tuple, *, targets: tuple[str, ...]) -> list[dict]:
        self._assert_in_scope(*targets)
        with connect(Principal.READ_ONLY, database=self._database,
                     autocommit=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, *params)
            columns = [c[0] for c in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _finish(self, tool: str, rows: list[dict], usage: UsageType | None,
                started: float, note: str | None = None) -> ToolResult:
        truncated = len(rows) > MAX_ROWS
        if truncated:
            # Say so in the result rather than silently returning a prefix.
            rows = rows[:MAX_ROWS]
            note = ((note + " ") if note else "") + (
                f"Result truncated to {MAX_ROWS} rows; narrow the query.")

        sources: set[str] = set()
        if usage is not None and rows:
            self.tracker.record_rows(usage, rows)
            sources = {row["Source_Doc_ID"] for row in rows}

        duration_ms = int((time.perf_counter() - started) * 1000)
        result = ToolResult(tool=tool, rows=rows, duration_ms=duration_ms,
                            sources=sources, truncated=truncated, note=note)

        self.audit.tool_call(tool=tool, node=self.node, payload=rows,
                             duration_ms=duration_ms, status="ok")
        LOG.info("tool=%s status=ok rows=%s sources=%s duration_ms=%s",
                 tool, len(rows), len(sources), duration_ms)
        return result

    def _has_fulltext(self) -> bool:
        """Whether FULLTEXT is available, cached per instance."""
        if self._fulltext is None:
            rows = self._query(
                "SELECT CAST(SERVERPROPERTY('IsFullTextInstalled') AS int) AS ft",
                (), targets=())
            self._fulltext = bool(rows and rows[0]["ft"])
            if not self._fulltext:
                LOG.warning("tool=search_claims status=fulltext_unavailable "
                            "fallback=LIKE -- adequate at 21 claims, not beyond")
        return self._fulltext

    # -- 1. tasks ----------------------------------------------------------

    def get_tasks(self, soc_code: str) -> ToolResult:
        """Task statements for one occupation, with their weighting convention."""
        started = time.perf_counter()
        rows = self._query("""
            SELECT Task_ID, SOC_Code, Occupation, Statement, Task_Type,
                   Importance, Relevance_Pct, Weight_Source, Source_Doc_ID
            FROM dbo.VW_ROLE_TASKS WHERE SOC_Code = ? ORDER BY Task_ID""",
            (soc_code,), targets=("dbo.VW_ROLE_TASKS",))
        if not rows:
            raise ToolError(
                f"No tasks published for SOC {soc_code!r}. The occupation is "
                f"either out of scope or not loaded; it must not be silently "
                f"substituted with a neighbour.")
        return self._finish("get_tasks", rows, UsageType.TASK_SOURCE, started)

    # -- 2. exposure benchmarks -------------------------------------------

    def get_exposure_benchmarks(self, soc_code: str,
                                measure: str | None = None) -> ToolResult:
        """Published exposure indices. ``Scale_Note`` always travels with them."""
        started = time.perf_counter()
        sql = """SELECT SOC_Code, Measure, Value, Percentile, Scale_Note,
                        Source_Doc_ID
                 FROM dbo.VW_EXPOSURE_BENCHMARK WHERE SOC_Code = ?"""
        params: tuple = (soc_code,)
        if measure:
            sql += " AND Measure = ?"
            params += (measure,)
        rows = self._query(sql + " ORDER BY Measure", params,
                           targets=("dbo.VW_EXPOSURE_BENCHMARK",))
        return self._finish("get_exposure_benchmarks", rows,
                            UsageType.EXPOSURE_BENCHMARK, started,
                            note=None if rows else
                            "No published benchmark for this occupation; the "
                            "result will be uncalibrated.")

    # -- 3. adoption curve -------------------------------------------------

    def get_adoption_curve(self, sector_code: str, question_code: str = "7",
                           answer_label: str = "Yes",
                           include_suppressed: bool = False) -> ToolResult:
        """Survey adoption trajectory for one sector.

        Suppressed cells are excluded by default but never zero-filled. Pass
        ``include_suppressed`` to see where the data is missing.
        """
        started = time.perf_counter()
        sql = """SELECT Survey, Period_Label, Period_Start, Sector_Code,
                        Sector_Label, Question_Code, Answer_Label, Value, Unit,
                        Is_Suppressed, Source_Doc_ID
                 FROM dbo.VW_ADOPTION_CURVE
                 WHERE Sector_Code = ? AND Question_Code = ? AND Answer_Label = ?"""
        if not include_suppressed:
            sql += " AND Value IS NOT NULL"
        rows = self._query(sql + " ORDER BY Period_Start",
                           (sector_code, question_code, answer_label),
                           targets=("dbo.VW_ADOPTION_CURVE",))
        suppressed = sum(1 for r in rows if r.get("Is_Suppressed"))
        note = (f"{suppressed} suppressed observation(s) present; value is NULL, "
                f"never zero." if suppressed else None)
        return self._finish("get_adoption_curve", rows,
                            UsageType.ADOPTION_EVIDENCE, started, note=note)

    # -- 4. claims ----------------------------------------------------------

    def search_claims(self, topic: str | None = None,
                      text: str | None = None,
                      limit: int = 25) -> ToolResult:
        """Retrieve claims by topic or free text, with quote and page.

        This is the structural answer to fabricated citations: the synthesis
        node may cite only what this tool returned, so the model never has to
        recall a source — only select one it was handed.

        Uses FULLTEXT when installed and falls back to ``LIKE`` otherwise. The
        fallback is logged: adequate at this corpus size, and not beyond.
        """
        if not topic and not text:
            raise ToolError("search_claims needs a topic or a text query")

        started = time.perf_counter()
        sql = """SELECT Claim_ID, Topic, Quote, Page, Note, Doc_Title, Publisher,
                        Is_Mirror, Verified_Against_Publisher, Source_Doc_ID
                 FROM dbo.VW_CLAIM_EVIDENCE WHERE 1 = 1"""
        params: tuple = ()
        note = None

        if topic:
            sql += " AND Topic = ?"
            params += (topic,)
        if text:
            if self._has_fulltext():
                sql += " AND CONTAINS(Quote, ?)"
                params += (f'"{text}"',)
            else:
                sql += " AND Quote LIKE ?"
                params += (f"%{text}%",)
                note = ("Full-Text Search is not installed on this instance, so "
                        "retrieval used a literal LIKE match. Lexically "
                        "different phrasings of the same idea will be missed.")

        rows = self._query(f"{sql} ORDER BY Source_Doc_ID, Page", params,
                           targets=("dbo.VW_CLAIM_EVIDENCE",))[:limit]

        mirrors = sum(1 for r in rows
                      if r.get("Is_Mirror") and not r.get("Verified_Against_Publisher"))
        if mirrors:
            note = ((note + " ") if note else "") + (
                f"{mirrors} claim(s) come from an unverified mirror; these block "
                f"the Review Gate on a customer-deliverable run.")

        return self._finish("search_claims", rows, UsageType.CLAIM_EVIDENCE,
                            started, note=note)

    # -- 5. industry metrics ------------------------------------------------

    def get_industry_metric(self, series_id: str,
                            industry_code: str | None = None,
                            start: str | None = None,
                            end: str | None = None) -> ToolResult:
        """One economic series, optionally narrowed by industry and period."""
        started = time.perf_counter()
        sql = """SELECT Provider, Series_ID, Industry_Code, Period, Value, Unit,
                        Source_Doc_ID
                 FROM dbo.VW_INDUSTRY_METRIC WHERE Series_ID = ?"""
        params: tuple = (series_id,)
        if industry_code:
            sql += " AND Industry_Code = ?"
            params += (industry_code,)
        if start:
            sql += " AND Period >= ?"
            params += (start,)
        if end:
            sql += " AND Period <= ?"
            params += (end,)
        rows = self._query(sql + " ORDER BY Period", params,
                           targets=("dbo.VW_INDUSTRY_METRIC",))
        return self._finish("get_industry_metric", rows,
                            UsageType.INDUSTRY_METRIC, started)

    # -- 6. source document -------------------------------------------------

    def get_source_document(self, doc_id: str) -> ToolResult:
        """Resolve a citation to its digest, publisher and mirror status.

        Registers no consumption: this is reference metadata about an artefact
        already bound by whichever tool returned evidence from it. Binding it
        again here would double-count.
        """
        started = time.perf_counter()
        rows = self._query("""
            SELECT doc_id AS Source_Doc_ID, title, publisher, url, format,
                   sha256, bytes, retrieved_at, provenance_note, is_mirror,
                   verified_against_publisher
            FROM ref.source_document WHERE doc_id = ?""",
            (doc_id,), targets=("ref.source_document",))
        if not rows:
            raise ToolError(f"No source document registered as {doc_id!r}")
        return self._finish("get_source_document", rows, None, started)

    # -- surface introspection ---------------------------------------------

    @classmethod
    def tool_names(cls) -> list[str]:
        """The published surface. Six tools, not twenty datasets."""
        return ["get_tasks", "get_exposure_benchmarks", "get_adoption_curve",
                "search_claims", "get_industry_metric", "get_source_document"]
