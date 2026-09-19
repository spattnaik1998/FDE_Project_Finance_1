"""Apply the SQL DDL scripts to the local SQL Server instance, in order.

The scripts are idempotent, so this is safe to re-run: it is the way the
environment is rebuilt, not a one-shot migration.  Scripts are split on ``GO``
batch separators, which SQL Server tooling understands but ODBC does not.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")

import pyodbc

from config import PROJECT_ROOT

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("setup_db")

SQL_DIR = PROJECT_ROOT / "sql"
SERVER = "LAPTOP-FO95TROJ"
DATABASE = "FDE_TaskExposure"

# A GO on its own line, case-insensitive, is a batch separator -- not SQL.
GO_SPLIT = re.compile(r"^\s*GO\s*(?:--.*)?$", re.IGNORECASE | re.MULTILINE)


def connect(database: str = "master") -> pyodbc.Connection:
    """Open a trusted connection. Autocommit: DDL such as CREATE DATABASE
    cannot run inside an explicit transaction."""
    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER};"
        f"DATABASE={database};Trusted_Connection=yes;TrustServerCertificate=yes",
        timeout=30, autocommit=True)
    return conn


def _strip_comments(sql: str) -> str:
    """Remove block and line comments so an empty batch can be recognised."""
    without_block = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return "\n".join(
        line for line in without_block.splitlines()
        if line.strip() and not line.strip().startswith("--"))


def run_script(conn: pyodbc.Connection, path: Path) -> tuple[int, int]:
    """Execute one script batch by batch. Returns (executed, failed)."""
    text = path.read_text(encoding="utf-8")
    batches = [b.strip() for b in GO_SPLIT.split(text) if b.strip()]
    executed = failed = 0

    cursor = conn.cursor()
    for i, batch in enumerate(batches, start=1):
        # Skip a batch ONLY when nothing but comments remains. Guessing at
        # batch content by keyword silently drops real statements -- an
        # earlier version of this loop did exactly that to two MERGE batches
        # and still reported success.
        if not _strip_comments(batch).strip():
            continue
        try:
            cursor.execute(batch)
            while cursor.nextset():
                pass
            executed += 1
        except pyodbc.Error as exc:
            failed += 1
            LOG.error("script=%s batch=%s status=failed error=%s",
                      path.name, i, str(exc)[:400])
            LOG.error("  first line: %s", batch.strip().splitlines()[0][:120])
    return executed, failed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Run a single script by filename prefix, e.g. 04")
    parser.add_argument("--include-logins", action="store_true",
                        help="Also run 05_logins_and_users.sql (needs mixed-mode auth)")
    args = parser.parse_args()

    scripts = sorted(SQL_DIR.glob("*.sql"))
    if args.only:
        scripts = [s for s in scripts if s.name.startswith(args.only)]
    elif not args.include_logins:
        # 06 needs mixed-mode auth, 07 needs the Full-Text feature; both are
        # environment prerequisites this machine does not yet meet.
        scripts = [s for s in scripts
                   if "logins" not in s.name and "fulltext" not in s.name]

    if not scripts:
        LOG.error("No scripts matched")
        sys.exit(1)

    # Script 01 creates the database, so the first connection is to master.
    conn = connect("master")
    total_ok = total_fail = 0

    for script in scripts:
        LOG.info("script=%s status=running", script.name)
        ok, fail = run_script(conn, script)
        total_ok += ok
        total_fail += fail
        LOG.info("script=%s status=%s batches_ok=%s batches_failed=%s",
                 script.name, "ok" if fail == 0 else "errors", ok, fail)

    conn.close()

    print(f"\n{'=' * 70}")
    print(f"DDL APPLIED: {total_ok} batches succeeded, {total_fail} failed")
    print(f"{'=' * 70}")
    if total_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
