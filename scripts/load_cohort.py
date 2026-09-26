"""Load the finance occupation cohort so calibration becomes identifiable.

    python scripts/load_cohort.py --dry-run
    python scripts/load_cohort.py

Calibration needs a cohort, not one more occupation: a percentile is a rank,
and both our index and the published benchmark have to be ranked within the
*same* reference set. This loads the tasks for every SOC 13-2* occupation that
has both O*NET task statements and an AIOE benchmark value.

Nothing is fetched. The O*NET Task Statements file already in ``data/docs`` is
the full database dump --- 18,796 statements across 923 occupations --- and is
already registered in ``ref.source_document`` with its SHA-256. The cohort was
always available; only 13-2051 had been loaded.

**One detail code per 6-digit SOC.** AIOE keys on the 6-digit code, so two
O*NET detail codes under one SOC (13-2099.01 and 13-2099.04) carry the same
benchmark value. Loading both would put one benchmark observation into the
cohort twice and shift its ranks against a reference set the other side never
saw. The lowest detail code wins, except that 13-2099.01 is preferred because
it is the adjacent-SOC occupation the weighting decision already names.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")

from warehouse.session import Principal, connect

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("load_cohort")

TASK_FILE = Path("data/docs/onet_task_statements.txt")
OCCUPATION_FILE = Path("data/docs/onet_occupation_data.txt")
TASK_DOC_ID = "onet_task_statements"
OCCUPATION_DOC_ID = "onet_occupation_data"
FAMILY = "13-2"
MEASURE = "AIOE_language_modeling"

# Where two detail codes share a 6-digit SOC, this one is kept.
PREFERRED_DETAIL = {"13-2099": "13-2099.01"}


def _six_digit(onet_soc: str) -> str:
    return onet_soc.split(".")[0]


def read_cohort() -> tuple[pd.DataFrame, dict[str, str]]:
    """Task statements for the finance family, one detail code per SOC."""
    tasks = pd.read_csv(TASK_FILE, sep="\t", dtype=str)
    tasks.columns = [c.strip() for c in tasks.columns]
    family = tasks[tasks["O*NET-SOC Code"].str.startswith(FAMILY, na=False)]

    chosen: dict[str, str] = {}
    for onet_soc in sorted(family["O*NET-SOC Code"].unique()):
        base = _six_digit(onet_soc)
        preferred = PREFERRED_DETAIL.get(base)
        if preferred:
            if onet_soc == preferred:
                chosen[base] = onet_soc
        elif base not in chosen:
            chosen[base] = onet_soc

    keep = set(chosen.values())
    return family[family["O*NET-SOC Code"].isin(keep)].copy(), chosen


def read_titles() -> dict[str, str]:
    frame = pd.read_csv(OCCUPATION_FILE, sep="\t", dtype=str)
    frame.columns = [c.strip() for c in frame.columns]
    return dict(zip(frame["O*NET-SOC Code"], frame["Title"]))


def benchmarked_socs(cursor) -> dict[str, float]:
    """Which SOCs have a published benchmark value, read from the fact table.

    Not ``dbo.VW_EXPOSURE_BENCHMARK``. The VW_* layer is the agent's scope
    control and is granted to ``db_fde_ro`` alone; this runs as ``db_fde_load``,
    which holds SELECT on SCHEMA::core because it is the tier that writes facts.
    Reading the agent's view from the ingestion tier worked only while every
    connection fell back to the developer credential, and the fix is to read the
    fact rather than widen the view grants and blur the tiers.

    ``is_current = 1`` reproduces the view's filter: under append-only
    persistence a superseded version is still present, and counting it would
    admit one occupation twice.
    """
    rows = cursor.execute("""
        SELECT soc_code, percentile FROM core.exposure_estimate
        WHERE measure = ? AND is_current = 1 AND soc_code LIKE ?""",
        MEASURE, FAMILY + "%").fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database", default=None)
    args = parser.parse_args()

    if not TASK_FILE.exists():
        print(f"missing {TASK_FILE}; run scripts/fetch_documents.py first")
        return 1

    family, chosen = read_cohort()
    titles = read_titles()

    with connect(Principal.LOAD, database=args.database) as conn:
        cursor = conn.cursor()
        benchmark = benchmarked_socs(cursor)

        # Only occupations the benchmark covers can join the cohort: one we
        # scored but AIOE does not rate cannot contribute to a comparison.
        cohort = {base: onet for base, onet in chosen.items()
                  if base in benchmark}
        excluded = {base: onet for base, onet in chosen.items()
                    if base not in benchmark}

        print(f"\n{'=' * 78}")
        print("FINANCE COHORT (SOC 13-2*)")
        print(f"{'=' * 78}")
        print(f"  detail codes in family        {family['O*NET-SOC Code'].nunique()}")
        print(f"  with an AIOE benchmark        {len(cohort)}")
        print(f"  excluded (no benchmark)       {len(excluded)}"
              f"{': ' + ', '.join(sorted(excluded)) if excluded else ''}")

        selected = family[family["O*NET-SOC Code"].isin(cohort.values())]
        print(f"  task statements to load       {len(selected)}")
        print()
        for base in sorted(cohort):
            onet = cohort[base]
            n = int((selected['O*NET-SOC Code'] == onet).sum())
            print(f"    {onet:12} {n:>3} tasks  AIOE pct {benchmark[base]:>6.2f}  "
                  f"{titles.get(onet, '?')[:44]}")

        if args.dry_run:
            print("\n  dry run: nothing written")
            return 0

        occupations_added = tasks_added = tasks_skipped = 0
        for base, onet in sorted(cohort.items()):
            title = titles.get(onet, onet)
            cursor.execute("SELECT COUNT(*) FROM ref.occupation WHERE soc_code = ?",
                           onet)
            if not cursor.fetchone()[0]:
                cursor.execute("""
                    INSERT INTO ref.occupation
                        (soc_code, title, onet_version, domain_source,
                         has_onet_ratings)
                    VALUES (?, ?, '29.3', 'O*NET Task Statements', 0)""",
                    onet, title[:300])
                occupations_added += 1

            rows = selected[selected["O*NET-SOC Code"] == onet]
            for _, row in rows.iterrows():
                task_id = str(row["Task ID"]).strip()
                cursor.execute("""SELECT COUNT(*) FROM core.task
                                  WHERE task_id = ? AND source_doc_id = ?""",
                               task_id, TASK_DOC_ID)
                if cursor.fetchone()[0]:
                    tasks_skipped += 1
                    continue
                cursor.execute("""
                    INSERT INTO core.task
                        (task_id, soc_code, statement, task_type, importance,
                         relevance_pct, weight_source, source_doc_id)
                    VALUES (?, ?, ?, ?, NULL, NULL, 'equal', ?)""",
                    task_id, onet, str(row["Task"])[:1000],
                    (str(row.get("Task Type")).strip()
                     if pd.notna(row.get("Task Type")) else None),
                    TASK_DOC_ID)
                tasks_added += 1
        conn.commit()

        print(f"\n  occupations inserted          {occupations_added}")
        print(f"  tasks inserted                {tasks_added}")
        print(f"  tasks already present         {tasks_skipped}")

        total = cursor.execute("""
            SELECT COUNT(DISTINCT soc_code), COUNT(*) FROM core.task
            WHERE is_current = 1 AND soc_code LIKE ?""", FAMILY + "%").fetchone()
        print(f"  cohort now in core.task       {total[0]} occupations, "
              f"{total[1]} tasks")

    print("\n  Idempotent: re-running inserts nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
