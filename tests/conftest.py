"""Test fixtures: an isolated database built from the real DDL.

Tests run against ``FDE_TaskExposure_Test``, rebuilt from ``sql/*.sql`` at the
start of the session. Using the production DDL rather than a hand-written test
schema is deliberate: a test schema that drifts from the real one proves
nothing about the real one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pyodbc
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

TEST_DB = "FDE_TaskExposure_Test"
PROD_DB = "FDE_TaskExposure"
SERVER = "LAPTOP-FO95TROJ"
DRIVER = "ODBC Driver 17 for SQL Server"

GO_SPLIT = re.compile(r"^\s*GO\s*(?:--.*)?$", re.IGNORECASE | re.MULTILINE)
# Scripts that need environment prerequisites this machine does not meet.
DEFERRED = ("06_logins", "07_fulltext")


def _connect(database: str, autocommit: bool = True) -> pyodbc.Connection:
    return pyodbc.connect(
        f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={database};"
        f"Trusted_Connection=yes;TrustServerCertificate=yes",
        timeout=30, autocommit=autocommit)


def _strip_comments(sql: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return "\n".join(line for line in without_block.splitlines()
                     if line.strip() and not line.strip().startswith("--"))


PRINCIPAL_ROLES = {
    "USR_FDE_RO": "db_fde_ro",
    "USR_FDE_LOAD": "db_fde_load",
    "USR_FDE_SCORE": "db_fde_score",
    "USR_FDE_AUDIT": "db_fde_audit",
}


def _map_logins(cursor) -> int:
    """Create the four database users in the test database and add to roles.

    Returns how many were mapped, which is 0 when mixed-mode auth is off.
    """
    mapped = 0
    for login, role in PRINCIPAL_ROLES.items():
        exists = cursor.execute(
            "SELECT COUNT(*) FROM sys.sql_logins WHERE name = ?",
            login).fetchone()[0]
        if not exists:
            continue
        cursor.execute(f"""
            USE [{TEST_DB}];
            IF DATABASE_PRINCIPAL_ID('{login}') IS NULL
                CREATE USER [{login}] FOR LOGIN [{login}];
            ALTER ROLE [{role}] ADD MEMBER [{login}];""")
        while cursor.nextset():
            pass
        mapped += 1
    return mapped


@pytest.fixture(scope="session")
def test_database() -> str:
    """Build the test database from the production DDL, once per session."""
    admin = _connect("master")
    cur = admin.cursor()
    cur.execute(f"""
        IF DB_ID('{TEST_DB}') IS NOT NULL
        BEGIN
            ALTER DATABASE [{TEST_DB}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
            DROP DATABASE [{TEST_DB}];
        END""")
    admin.close()

    conn = _connect("master")
    cursor = conn.cursor()
    for script in sorted((PROJECT_ROOT / "sql").glob("*.sql")):
        if any(script.name.startswith(d) for d in DEFERRED):
            continue
        # The DDL names the production database; point it at the test one.
        text = script.read_text(encoding="utf-8").replace(PROD_DB, TEST_DB)
        for batch in GO_SPLIT.split(text):
            if not _strip_comments(batch).strip():
                continue
            cursor.execute(batch)
            while cursor.nextset():
                pass

    # Map the four SQL logins into the test database, if they exist.
    #
    # sql/06 is deferred here because it is the script that CREATES the logins,
    # and it does so at server level with `USE FDE_TaskExposure` -- so only
    # production ever got the database users. The roles exist in the test
    # database (sql/04 runs against whatever database it is pointed at) but had
    # no members, so every connection as USR_FDE_* failed to open the database.
    #
    # That surfaced the moment mixed-mode auth was enabled: 26 failures and 44
    # errors across the suite, all "Cannot open database FDE_TaskExposure_Test
    # requested by the login". The guardrail tests are only meaningful if the
    # test database reproduces production's security model, so it has to carry
    # the same users in the same roles.
    #
    # Conditional on the logins existing: with mixed-mode auth off there are
    # none, and the suite falls back to the developer credential exactly as
    # before.
    _map_logins(cursor)
    conn.close()

    yield TEST_DB

    admin = _connect("master")
    admin.cursor().execute(f"""
        IF DB_ID('{TEST_DB}') IS NOT NULL
        BEGIN
            ALTER DATABASE [{TEST_DB}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
            DROP DATABASE [{TEST_DB}];
        END""")
    admin.close()


@pytest.fixture
def conn(test_database: str):
    """A transactional connection, rolled back after each test."""
    connection = _connect(test_database, autocommit=False)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def cur(conn):
    return conn.cursor()


@pytest.fixture
def doc(cur):
    """Register one source document and return its id."""
    cur.execute("""
        INSERT INTO ref.source_document
            (doc_id, title, publisher, url, format, sha256, bytes, retrieved_at)
        VALUES ('d1', 'Fixture doc', 'Test publisher', 'http://example.test',
                'pdf', REPLICATE('a', 64), 100, SYSUTCDATETIME())""")
    return "d1"


@pytest.fixture
def revised_doc(cur, doc):
    """A second version of the same logical source, with different bytes."""
    cur.execute("""
        INSERT INTO ref.source_document
            (doc_id, title, publisher, url, format, sha256, bytes, retrieved_at)
        VALUES ('d1@v2', 'Fixture doc (revised)', 'Test publisher',
                'http://example.test', 'pdf', REPLICATE('b', 64), 110, SYSUTCDATETIME())""")
    return "d1@v2"


@pytest.fixture
def soc(cur):
    """The target occupation, matching the production seed."""
    cur.execute("""
        IF NOT EXISTS (SELECT 1 FROM ref.occupation WHERE soc_code = '13-2051.00')
        INSERT INTO ref.occupation (soc_code, title, domain_source, has_onet_ratings)
        VALUES ('13-2051.00', 'Financial and Investment Analysts', 'Analyst', 0)""")
    return "13-2051.00"


# --- Scoring fixtures -------------------------------------------------------

@pytest.fixture
def adoption_series() -> list[dict]:
    """A BTOS-shaped trajectory: finance AI use rising over ~11 months."""
    return [
        {"period_start": "2025-06-09", "value": 29.9},
        {"period_start": "2025-06-16", "value": 29.4},
        {"period_start": "2025-06-23", "value": 30.5},
        {"period_start": "2025-12-29", "value": 30.7},
        {"period_start": "2026-03-23", "value": 34.3},
        {"period_start": "2026-04-13", "value": 36.8},
        {"period_start": "2026-04-27", "value": 36.5},
    ]


@pytest.fixture
def lag_claims() -> list[dict]:
    """Historical grounding claims, as VW_CLAIM_EVIDENCE would return them."""
    return [
        {"claim_id": "brynjolfsson_productivity_j_curve:lag_length:6:0",
         "topic": "lag_length", "page": 6,
         "quote": "Accordingly, after an implementation lag period, AI might "
                  "significantly impact economic growth as other GPTs have."},
        {"claim_id": "brynjolfsson_productivity_j_curve:j_curve_definition:2:0",
         "topic": "j_curve_definition", "page": 2,
         "quote": "Our model generates a Productivity J-Curve that can explain "
                  "the productivity slowdowns often accompanying the advent of GPTs."},
    ]
