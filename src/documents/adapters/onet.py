"""O*NET bulk-file adapter: tab-separated text into :class:`Task` records."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from documents.schemas import Task

LOG = logging.getLogger("documents.onet")

SCALE_IMPORTANCE = "IM"   # mean importance, 1-5
SCALE_RELEVANCE = "RT"    # percent of incumbents reporting the task as relevant


def _read_tsv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)


def load_tasks(statements_path: str | Path, ratings_path: str | Path,
               soc_prefix: str, source_doc_id: str) -> list[Task]:
    """Return the task list for one occupation, weighted by O*NET's own ratings.

    ``soc_prefix`` matches on the O*NET-SOC code's leading characters, so
    ``'13-2051'`` picks up ``13-2051.00`` without the caller needing to know the
    detail suffix.

    Ratings are pivoted from long to wide before joining: O*NET stores one row
    per (task, scale, category), and only the IM and RT scales carry the
    single-valued measures we want.  Frequency (FT) is a distribution across
    seven categories and is deliberately not collapsed into a scalar here.
    """
    statements = _read_tsv(statements_path)
    ratings = _read_tsv(ratings_path)

    mask = statements["O*NET-SOC Code"].str.startswith(soc_prefix)
    statements = statements[mask].copy()
    if statements.empty:
        raise ValueError(f"No O*NET tasks found for SOC prefix {soc_prefix!r}")

    ratings = ratings[ratings["Task ID"].isin(statements["Task ID"])].copy()
    ratings["Data Value"] = pd.to_numeric(ratings["Data Value"], errors="coerce")

    scalar = ratings[ratings["Scale ID"].isin([SCALE_IMPORTANCE, SCALE_RELEVANCE])]
    wide = scalar.pivot_table(index="Task ID", columns="Scale ID",
                              values="Data Value", aggfunc="mean")

    tasks: list[Task] = []
    for _, row in statements.iterrows():
        task_id = row["Task ID"]
        importance = relevance = None
        if task_id in wide.index:
            importance = wide.at[task_id, SCALE_IMPORTANCE] if SCALE_IMPORTANCE in wide.columns else None
            relevance = wide.at[task_id, SCALE_RELEVANCE] if SCALE_RELEVANCE in wide.columns else None

        tasks.append(Task(
            task_id=str(task_id),
            soc_code=row["O*NET-SOC Code"],
            occupation="",  # filled by load_occupation_titles
            statement=row["Task"],
            task_type=row.get("Task Type") or None,
            importance=None if pd.isna(importance) else float(importance),
            relevance_pct=None if pd.isna(relevance) else float(relevance),
            source_doc_id=source_doc_id,
        ))

    rated = sum(1 for t in tasks if t.importance is not None)
    coverage = rated / len(tasks) if tasks else 0.0
    if coverage == 0.0:
        LOG.warning(
            "source=onet status=no_ratings soc=%s tasks=%s -- O*NET publishes no "
            "incumbent ratings for this occupation (domain source is analyst "
            "review), so tasks cannot be weighted by importance from this file",
            soc_prefix, len(tasks))
    elif coverage < 0.9:
        LOG.warning("source=onet status=partial_ratings soc=%s coverage=%.0f%%",
                    soc_prefix, coverage * 100)

    LOG.info("source=onet status=ok soc=%s tasks=%s rated=%s",
             soc_prefix, len(tasks), rated)
    return tasks


def ratings_coverage(ratings_path: str | Path, soc_prefix: str) -> bool:
    """Whether O*NET publishes any ratings for this occupation at all.

    Worth checking before choosing a target occupation: several finance roles,
    including 13-2051, carry analyst-written task lists with no incumbent
    survey behind them and therefore no importance ratings.
    """
    ratings = _read_tsv(ratings_path)
    return bool(ratings["O*NET-SOC Code"].str.startswith(soc_prefix).any())


def occupation_title(occupation_path: str | Path, soc_prefix: str) -> str:
    """Look up the O*NET title for a SOC prefix."""
    occ = _read_tsv(occupation_path)
    hit = occ[occ["O*NET-SOC Code"].str.startswith(soc_prefix)]
    return hit.iloc[0]["Title"] if not hit.empty else ""


def attach_titles(tasks: list[Task], occupation_path: str | Path) -> list[Task]:
    """Fill each task's occupation title from the occupation data file."""
    occ = _read_tsv(occupation_path).set_index("O*NET-SOC Code")["Title"].to_dict()
    for task in tasks:
        task.occupation = occ.get(task.soc_code, "")
    return tasks
