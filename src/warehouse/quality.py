"""Load-time quality assertions (TDD 3.3).

These are blocking checks, not warnings. Every result — pass or fail — is
recorded in ``audit.quality_assertion`` so a load that silently degraded can be
distinguished from one that never ran.

The checks exist because several failure modes in this project are *quiet*: a
suppressed survey cell zero-filled, a corrupted PDF quote, a page number past
the end of its document. None of those raise on their own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import pyodbc

LOG = logging.getLogger("warehouse.quality")

RUNON_LEN = 28  # matches the PDF adapter's run-on token threshold


@dataclass
class Assertion:
    """One check: a name, the SQL that counts violations, and why it matters."""

    name: str
    target: str
    sql: str
    rationale: str


ASSERTIONS: list[Assertion] = [
    Assertion(
        "provenance_resolves", "core.*",
        """SELECT (SELECT COUNT(*) FROM core.task t
                   WHERE NOT EXISTS (SELECT 1 FROM ref.source_document d
                                     WHERE d.doc_id = t.source_doc_id))
                + (SELECT COUNT(*) FROM core.extracted_claim c
                   WHERE NOT EXISTS (SELECT 1 FROM ref.source_document d
                                     WHERE d.doc_id = c.source_doc_id))""",
        "An unprovenanced fact must be unrepresentable, not merely rare."),
    Assertion(
        "percentages_in_range", "core.adoption_observation",
        "SELECT COUNT(*) FROM core.adoption_observation "
        "WHERE value IS NOT NULL AND (value < 0 OR value > 100)",
        "A percentage outside [0,100] means a parsing error upstream."),
    Assertion(
        "suppressed_not_zeroed", "core.adoption_observation",
        "SELECT COUNT(*) FROM core.adoption_observation "
        "WHERE is_suppressed = 1 AND value IS NOT NULL",
        "A suppressed cell is missing information; zero-filling it invents data."),
    Assertion(
        "claims_have_page", "core.extracted_claim",
        "SELECT COUNT(*) FROM core.extracted_claim WHERE page < 1",
        "A claim without a checkable page number is not admissible."),
    Assertion(
        "quotes_substantive", "core.extracted_claim",
        "SELECT COUNT(*) FROM core.extracted_claim WHERE LEN(LTRIM(RTRIM(quote))) < 20",
        "Too short to verify is the same as unusable."),
    Assertion(
        "quotes_not_runon", "core.extracted_claim",
        # A very long token with no hyphen or space is the pdfplumber spacing
        # defect surviving into the warehouse.
        f"""SELECT COUNT(*) FROM core.extracted_claim
            WHERE EXISTS (
                SELECT 1 FROM STRING_SPLIT(REPLACE(quote, CHAR(10), ' '), ' ') AS w
                WHERE LEN(w.value) >= {RUNON_LEN} AND w.value NOT LIKE '%-%')""",
        "A corrupted quote is worse than a missing one: it looks citable."),
    Assertion(
        "scale_notes_present", "core.exposure_estimate",
        "SELECT COUNT(*) FROM core.exposure_estimate "
        "WHERE scale_note IS NULL OR LEN(LTRIM(RTRIM(scale_note))) = 0",
        "A standardised index without its scale statement is meaningless."),
    Assertion(
        "tasks_have_weight_source", "core.task",
        "SELECT COUNT(*) FROM core.task "
        "WHERE weight_source NOT IN ('onet','adjacent_soc','equal')",
        "The weighting convention must travel with the data, per decision 1."),
    Assertion(
        "views_expose_provenance", "dbo.VW_*",
        """SELECT 5 - COUNT(DISTINCT c.object_id)
           FROM sys.columns c JOIN sys.views v ON v.object_id = c.object_id
           WHERE c.name = 'Source_Doc_ID' AND v.name LIKE 'VW_%'""",
        "run_source_binding cannot be populated if a view hides its source id."),
    Assertion(
        "no_duplicate_current_tasks", "core.task",
        """SELECT COUNT(*) FROM (
               SELECT task_id FROM core.task WHERE is_current = 1
               GROUP BY task_id HAVING COUNT(*) > 1) AS dupes""",
        "Two current versions of one task would make the view non-deterministic."),
]


def run_assertions(cursor: pyodbc.Cursor, run_id: str | None = None,
                   extra: list[Assertion] | None = None) -> list[tuple[str, bool, int]]:
    """Execute every assertion and record the outcome. Returns (name, passed, count)."""
    results: list[tuple[str, bool, int]] = []

    for assertion in (ASSERTIONS + (extra or [])):
        try:
            cursor.execute(assertion.sql)
            violations = int(cursor.fetchone()[0] or 0)
            passed = violations == 0
            observed = "clean" if passed else f"{violations} violation(s)"
        except pyodbc.Error as exc:
            passed, violations = False, -1
            observed = f"check errored: {str(exc)[:200]}"

        cursor.execute("""
            INSERT INTO audit.quality_assertion
                (run_id, check_name, target, passed, observed)
            VALUES (?, ?, ?, ?, ?)""",
            run_id, assertion.name, assertion.target,
            1 if passed else 0, observed[:500])

        if not passed:
            LOG.error("check=%s status=failed target=%s observed=%s",
                      assertion.name, assertion.target, observed)
        results.append((assertion.name, passed, violations))

    return results


class QualityGateFailed(RuntimeError):
    """One or more blocking assertions failed; the load must not be trusted."""


def enforce(results: list[tuple[str, bool, int]]) -> None:
    """Raise if any assertion failed. Blocking means blocking."""
    failures = [(name, count) for name, passed, count in results if not passed]
    if failures:
        detail = ", ".join(f"{n} ({c})" for n, c in failures)
        raise QualityGateFailed(f"{len(failures)} quality assertion(s) failed: {detail}")
