"""Database session management.

One place defines the connection string, so the credential a component uses is
a deliberate choice rather than whatever happened to be copied. Each role in
TDD 3.2 maps to a :class:`Principal`; until mixed-mode authentication is
enabled the developer's trusted connection stands in, and that substitution is
logged rather than hidden.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from enum import Enum
from typing import Iterator

import pyodbc

LOG = logging.getLogger("warehouse.session")

SERVER = os.environ.get("SQLSERVER_HOST", "LAPTOP-FO95TROJ")
DATABASE = os.environ.get("SQLSERVER_DATABASE", "FDE_TaskExposure")
DRIVER = os.environ.get("SQLSERVER_DRIVER", "ODBC Driver 17 for SQL Server")


class Principal(str, Enum):
    """The four principals of TDD 3.2, plus the developer fallback."""

    READ_ONLY = "USR_FDE_RO"
    LOAD = "USR_FDE_LOAD"
    SCORE = "USR_FDE_SCORE"
    AUDIT = "USR_FDE_AUDIT"
    DEVELOPER = "DEVELOPER"


class WarehouseError(RuntimeError):
    """A warehouse operation failed in a way the caller must handle."""


def _password_for(principal: Principal) -> str | None:
    """SQL-login password, from the process environment or the project .env.

    This used to read ``os.environ`` only, with the comment "never read from a
    file". The result was that ``scripts/enable_sql_auth.ps1`` wrote the four
    passwords to ``.env`` -- the only place it can persist them -- and this
    function never looked there, so privilege isolation silently never engaged.
    The instance had mixed-mode auth on, the logins existed, and every
    connection still fell back to the developer credential.

    The original reasoning was also backwards. An environment variable is
    inherited by every child process this shell spawns and is readable from a
    process listing; ``.env`` is access-controlled to its owner, SYSTEM and
    Administrators by ``scripts/harden_secrets.ps1``. The file is the narrower
    store, not the wider one.

    Precedence matches ``config.resolve_key``: a value exported for this
    process wins, because someone set it deliberately; otherwise ``.env``.
    """
    name = f"{principal.value}_PASSWORD"
    explicit = os.environ.get(name)
    if explicit:
        return explicit
    try:
        import config
        return config._parse_env_file(config.ENV_PATH).get(name) or None
    except Exception:                               # noqa: BLE001
        # A missing or unreadable .env means "no password", which degrades to
        # the developer fallback with its WARNING -- never to a silent failure.
        return None


def connection_string(principal: Principal = Principal.DEVELOPER,
                      database: str | None = None) -> str:
    """Build a connection string for the given principal.

    Falls back to the trusted developer connection when the SQL login has no
    password configured, because mixed-mode authentication is not yet enabled
    on this instance. The fallback is logged at WARNING: a run that believes it
    is sandboxed but is not should say so loudly.
    """
    db = database or DATABASE
    base = f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={db};TrustServerCertificate=yes"

    if principal is Principal.DEVELOPER:
        return f"{base};Trusted_Connection=yes"

    password = _password_for(principal)
    if not password:
        LOG.warning(
            "principal=%s status=fallback_developer_credential -- mixed-mode auth "
            "is not enabled, so privilege isolation is NOT in force for this run",
            principal.value)
        return f"{base};Trusted_Connection=yes"

    return f"{base};UID={principal.value};PWD={password}"


def is_isolated(principal: Principal) -> bool:
    """True when the principal will actually authenticate as itself.

    Tests use this to skip privilege assertions honestly rather than passing
    them under a credential that would satisfy anything.
    """
    return principal is not Principal.DEVELOPER and bool(_password_for(principal))


@contextmanager
def connect(principal: Principal = Principal.DEVELOPER,
            database: str | None = None,
            autocommit: bool = False) -> Iterator[pyodbc.Connection]:
    """Yield a connection, committing on success and rolling back on error."""
    conn = pyodbc.connect(connection_string(principal, database),
                          timeout=30, autocommit=autocommit)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def scalar(sql: str, params: tuple = (), *,
           principal: Principal = Principal.DEVELOPER) -> object:
    """Run a single-value query. Convenience for assertions and counts."""
    with connect(principal) as conn:
        row = conn.cursor().execute(sql, params).fetchone()
        return row[0] if row else None
