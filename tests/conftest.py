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
