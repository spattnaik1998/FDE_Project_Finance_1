"""Fact loaders: typed corpus and landed CSVs into ``core.*``.

Every loader obeys the same two rules from TDD B.0:

* **Append-only.** A fact is never updated in place. A revised source artefact
  produces a new ``source_doc_id`` and new rows; prior rows stay exactly as the
  run that consumed them saw.
* **Idempotency on source hash + natural key.** Re-loading identical bytes is a
  no-op because the ``(natural key, source_doc_id)`` uniqueness already holds.

The ``is_current`` flag is what the ``VW_*`` views project. When a revision
arrives, earlier versions of the same natural key are demoted rather than
deleted, so the history remains queryable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyodbc

LOG = logging.getLogger("warehouse.loaders")

# "BTOS Q7 [Yes]: In the last two weeks, did this business use ..."
MEASURE_RE = re.compile(r"^(?P<survey>\w+)\s+Q(?P<question>[\w.]+)\s+\[(?P<answer>[^\]]*)\]")

# pandas writes a literal "n/a" where O*NET has no Task Type; the column is
# nullable precisely because 13-2051 has no Core/Supplemental split.
NULL_TOKENS = {"n/a", "nan", "none", "", "null"}


@dataclass
class LoadResult:
    """What one loader did, for the run summary and the manifest."""

    table: str
    inserted: int
    skipped_existing: int
    demoted: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.skipped_existing


def _clean(value: object) -> object | None:
    """Normalise pandas/JSON null-ish values to a real None."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, str) and value.strip().lower() in NULL_TOKENS:
        return None
    return value


def _demote_superseded(cursor: pyodbc.Cursor, table: str,
                       key_columns: list[str], doc_column: str = "source_doc_id") -> int:
    """Mark older versions of each natural key as no longer current.

    Nothing is deleted: the superseded rows remain, and a historical run still
    resolves to them through ``audit.run_source_binding``.
    """
    keys = ", ".join(key_columns)
    cursor.execute(f"""
        WITH ranked AS (
            SELECT {doc_column}, loaded_at, is_current,
                   ROW_NUMBER() OVER (PARTITION BY {keys}
                                      ORDER BY loaded_at DESC, {doc_column} DESC) AS rn
            FROM {table}
        )
        UPDATE ranked SET is_current = 0 WHERE rn > 1 AND is_current = 1""")
    return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0


# ---------------------------------------------------------------------------
# Corpus facts
# ---------------------------------------------------------------------------

def load_tasks(cursor: pyodbc.Cursor, tasks: list[dict],
               doc_map: dict[str, str], weight_source: str = "equal") -> LoadResult:
    """Load O*NET task statements.

    ``weight_source`` defaults to ``equal`` per the resolved task-weighting
    decision: O*NET publishes no ratings for 13-2051, so equal weighting is an
    aggregation convention and is recorded as one rather than left implicit.
    """
    inserted = skipped = 0
    for task in tasks:
        doc_id = doc_map.get(task["source_doc_id"], task["source_doc_id"])
        cursor.execute(
            "SELECT COUNT(*) FROM core.task WHERE task_id = ? AND source_doc_id = ?",
            task["task_id"], doc_id)
        if cursor.fetchone()[0]:
            skipped += 1
            continue
        cursor.execute("""
            INSERT INTO core.task
                (task_id, soc_code, statement, task_type, importance,
                 relevance_pct, weight_source, source_doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            task["task_id"], task["soc_code"], task["statement"][:1000],
            _clean(task.get("task_type")), _clean(task.get("importance")),
            _clean(task.get("relevance_pct")), weight_source, doc_id)
        inserted += 1

    demoted = _demote_superseded(cursor, "core.task", ["task_id"])
    LOG.info("table=core.task status=ok inserted=%s skipped=%s demoted=%s",
             inserted, skipped, demoted)
    return LoadResult("core.task", inserted, skipped, demoted)


def load_exposure_estimates(cursor: pyodbc.Cursor, estimates: list[dict],
                            doc_map: dict[str, str]) -> LoadResult:
    """Load published exposure benchmarks, with percentile computed on load.

    The raw index is not interpretable alone -- a percentile is what a customer
    can act on, and what the calibration gate compares against.
    """
    values = sorted(e["value"] for e in estimates)
    total = len(values)

    def percentile(value: float) -> float | None:
        if not total:
            return None
        below = sum(1 for v in values if v < value)
        return round(100.0 * below / total, 2)

    inserted = skipped = 0
    for est in estimates:
        doc_id = doc_map.get(est["source_doc_id"], est["source_doc_id"])
        cursor.execute("""SELECT COUNT(*) FROM core.exposure_estimate
                          WHERE soc_code = ? AND measure = ? AND source_doc_id = ?""",
                       est["soc_code"], est["measure"], doc_id)
        if cursor.fetchone()[0]:
            skipped += 1
            continue
        cursor.execute("""
            INSERT INTO core.exposure_estimate
                (soc_code, measure, value, percentile, scale_note, source_doc_id)
            VALUES (?, ?, ?, ?, ?, ?)""",
            est["soc_code"], est["measure"], est["value"],
            percentile(est["value"]), est["scale_note"], doc_id)
        inserted += 1

    demoted = _demote_superseded(cursor, "core.exposure_estimate",
                                 ["soc_code", "measure"])
    LOG.info("table=core.exposure_estimate status=ok inserted=%s skipped=%s",
             inserted, skipped)
    return LoadResult("core.exposure_estimate", inserted, skipped, demoted)


def load_adoption_observations(cursor: pyodbc.Cursor, observations: list[dict],
                               doc_map: dict[str, str]) -> LoadResult:
    """Load survey adoption rates.

    The corpus packs survey, question and answer into one ``measure`` string;
    the warehouse stores them as separate columns so the adoption curve can be
    queried without string matching. A suppressed cell keeps ``value IS NULL``
    and ``is_suppressed = 1`` -- it is missing information, never zero.
    """
    inserted = skipped = 0
    for obs in observations:
        doc_id = doc_map.get(obs["source_doc_id"], obs["source_doc_id"])
        match = MEASURE_RE.match(obs["measure"])
        survey = match.group("survey") if match else "UNKNOWN"
        question = match.group("question") if match else "?"
        answer = match.group("answer") if match else obs["measure"][:200]

        value = _clean(obs.get("value"))
        suppressed = 1 if value is None else 0

        cursor.execute("""SELECT COUNT(*) FROM core.adoption_observation
                          WHERE survey = ? AND period_label = ?
                            AND ISNULL(sector_code,'') = ISNULL(?,'')
                            AND question_code = ? AND answer_label = ?
                            AND source_doc_id = ?""",
                       survey, obs["period"], obs.get("sector_code"),
                       question, answer, doc_id)
        if cursor.fetchone()[0]:
            skipped += 1
            continue

        cursor.execute("""
            INSERT INTO core.adoption_observation
                (survey, period_label, period_start, sector_code, question_code,
                 answer_label, value, unit, is_suppressed, source_doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            survey, obs["period"], _clean(obs.get("period_start")),
            _clean(obs.get("sector_code")), question, answer[:200],
            value, obs.get("unit", "percent"), suppressed, doc_id)
        inserted += 1

    demoted = _demote_superseded(
        cursor, "core.adoption_observation",
        ["survey", "period_label", "sector_code", "question_code", "answer_label"])
    LOG.info("table=core.adoption_observation status=ok inserted=%s skipped=%s",
             inserted, skipped)
    return LoadResult("core.adoption_observation", inserted, skipped, demoted)


def load_claims(cursor: pyodbc.Cursor, claims: list[dict],
                doc_map: dict[str, str]) -> LoadResult:
    """Load prose claims. ``claim_id`` is already version-scoped by construction.

    The corpus builds it as ``<source_doc_id>:<topic>:<page>:<index>``, so a
    re-extraction under a revised artefact is a new claim rather than an edit
    to an existing one -- which is what append-only requires.
    """
    inserted = skipped = 0
    for claim in claims:
        doc_id = doc_map.get(claim["source_doc_id"], claim["source_doc_id"])
        claim_id = claim["claim_id"]
        if doc_id != claim["source_doc_id"]:
            claim_id = claim_id.replace(claim["source_doc_id"], doc_id, 1)

        cursor.execute("SELECT COUNT(*) FROM core.extracted_claim WHERE claim_id = ?",
                       claim_id)
        if cursor.fetchone()[0]:
            skipped += 1
            continue
        cursor.execute("""
            INSERT INTO core.extracted_claim
                (claim_id, topic, quote, page, note, source_doc_id)
            VALUES (?, ?, ?, ?, ?, ?)""",
            claim_id[:200], claim["topic"], claim["quote"], claim["page"],
            _clean(claim.get("note")), doc_id)
        inserted += 1

    LOG.info("table=core.extracted_claim status=ok inserted=%s skipped=%s",
             inserted, skipped)
    return LoadResult("core.extracted_claim", inserted, skipped)


# ---------------------------------------------------------------------------
# Industry metrics from landed CSVs
# ---------------------------------------------------------------------------

def _insert_metrics(cursor: pyodbc.Cursor, rows: list[tuple]) -> tuple[int, int]:
    inserted = skipped = 0
    for provider, series_id, industry, period, value, unit, doc_id in rows:
        cursor.execute("""SELECT COUNT(*) FROM core.industry_metric
                          WHERE provider = ? AND series_id = ?
                            AND ISNULL(industry_code,'') = ISNULL(?,'')
                            AND period = ? AND source_doc_id = ?""",
                       provider, series_id, industry, period, doc_id)
        if cursor.fetchone()[0]:
            skipped += 1
            continue
        cursor.execute("""
            INSERT INTO core.industry_metric
                (provider, series_id, industry_code, period, value, unit, source_doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            provider, series_id, industry, period, value, unit, doc_id)
        inserted += 1
    return inserted, skipped


def load_industry_metrics(cursor: pyodbc.Cursor, raw_dir: Path,
                          doc_map: dict[str, str]) -> LoadResult:
    """Load FRED, BLS and BEA series into one tidy fact table."""
    rows: list[tuple] = []

    fred = raw_dir / "fred_observations.csv"
    if fred.exists() and "fred_observations" in doc_map:
        doc = doc_map["fred_observations"]
        df = pd.read_csv(fred)
        rows += [("FRED", r.series_id, None, pd.to_datetime(r.date).date(),
                  None if pd.isna(r.value) else float(r.value), None, doc)
                 for r in df.itertuples()]

    bls = raw_dir / "bls_industry_series.csv"
    if bls.exists() and "bls_industry_series" in doc_map:
        doc = doc_map["bls_industry_series"]
        df = pd.read_csv(bls)
        df = df[df["date"].notna()]
        rows += [("BLS", r.series_id, None, pd.to_datetime(r.date).date(),
                  None if pd.isna(r.value) else float(r.value), None, doc)
                 for r in df.itertuples()]

    bea = raw_dir / "bea_value_added_shares.csv"
    if bea.exists() and "bea_value_added_shares" in doc_map:
        doc = doc_map["bea_value_added_shares"]
        df = pd.read_csv(bea)
        df = df[df["DataValue"].notna()]
        for r in df.itertuples():
            # Series identity is table + line, industry is a separate dimension.
            series = f"T{r.TableID}:{str(r.IndustrYDescription)[:40]}"
            rows.append(("BEA", series, str(r.Industry),
                         pd.Timestamp(year=int(r.Year), month=1, day=1).date(),
                         float(r.DataValue), "percent_of_value_added", doc))

    inserted, skipped = _insert_metrics(cursor, rows)
    demoted = _demote_superseded(cursor, "core.industry_metric",
                                 ["provider", "series_id", "industry_code", "period"])
    LOG.info("table=core.industry_metric status=ok inserted=%s skipped=%s",
             inserted, skipped)
    return LoadResult("core.industry_metric", inserted, skipped, demoted)


def load_corpus(cursor: pyodbc.Cursor, corpus_path: Path,
                doc_map: dict[str, str]) -> list[LoadResult]:
    """Load every fact type in the typed corpus."""
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    return [
        load_tasks(cursor, corpus["tasks"], doc_map),
        load_exposure_estimates(cursor, corpus["exposure_estimates"], doc_map),
        load_adoption_observations(cursor, corpus["adoption_observations"], doc_map),
        load_claims(cursor, corpus["claims"], doc_map),
    ]
