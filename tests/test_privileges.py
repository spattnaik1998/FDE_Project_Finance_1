"""Runtime privilege isolation: the security model, actually exercised.

The grants in ``sql/04_roles_and_permissions.sql`` are built and their shape is
verified, but until mixed-mode authentication is enabled the loader and scoring
service connect as the developer — so the DENY grants are never *tested* at
runtime. Every test here skips with that reason rather than passing under a
credential that would satisfy anything.

Run ``scripts/enable_sql_auth.ps1`` from an elevated shell and these become
real assertions. That is the point: the skip is a recorded gap, not a silent
one.
"""

from __future__ import annotations

import pyodbc
import pytest

from warehouse.session import Principal, connect, is_isolated

PRODUCTION_DB = "FDE_TaskExposure"

ISOLATED = {p: is_isolated(p) for p in
            (Principal.READ_ONLY, Principal.LOAD, Principal.SCORE, Principal.AUDIT)}

needs = {p: pytest.mark.skipif(
    not ISOLATED[p],
    reason=f"{p.value} has no password configured; run scripts/enable_sql_auth.ps1 "
           f"to enable mixed-mode auth. Privilege isolation is NOT in force.")
    for p in ISOLATED}


def _execute(principal: Principal, sql: str, *params):
    with connect(principal, database=PRODUCTION_DB, autocommit=False) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, *params)
        while cursor.nextset():
            pass
        conn.rollback()


# --- Status ------------------------------------------------------------------

def test_isolation_status_is_recorded_either_way():
    """Always runs. Makes the state of the security model visible in the suite."""
    enabled = [p.value for p, ok in ISOLATED.items() if ok]
    disabled = [p.value for p, ok in ISOLATED.items() if not ok]
    assert enabled or disabled
    if disabled:
        pytest.skip(f"privilege isolation not in force for: {', '.join(disabled)}")


# --- USR_FDE_RO: the agent surface ------------------------------------------

@needs[Principal.READ_ONLY]
@pytest.mark.parametrize("view", ["VW_ROLE_TASKS", "VW_EXPOSURE_BENCHMARK",
                                  "VW_ADOPTION_CURVE", "VW_CLAIM_EVIDENCE",
                                  "VW_INDUSTRY_METRIC"])
def test_agent_can_read_every_published_view(view):
    _execute(Principal.READ_ONLY, f"SELECT TOP 1 * FROM dbo.{view}")


@needs[Principal.READ_ONLY]
@pytest.mark.parametrize("table", ["ref.source_document", "core.task",
                                   "score.role_verdict", "audit.AgentAuditLog"])
def test_agent_cannot_read_any_base_table(table):
    """The boundary that matters: flat views only, base tables denied."""
    with pytest.raises(pyodbc.Error):
        _execute(Principal.READ_ONLY, f"SELECT TOP 1 * FROM {table}")


@needs[Principal.READ_ONLY]
def test_agent_cannot_write_a_score():
    """It may request a score; it may not write one."""
    with pytest.raises(pyodbc.Error):
        _execute(Principal.READ_ONLY,
                 "INSERT INTO score.run (run_id, git_sha, config_hash, "
                 "rubric_version, calibration_policy_version, status) "
                 "VALUES (NEWID(), REPLICATE('a',40), REPLICATE('b',64), "
                 "'v1', 'provisional_v1', 'running')")


@needs[Principal.READ_ONLY]
def test_agent_cannot_create_objects():
    with pytest.raises(pyodbc.Error):
        _execute(Principal.READ_ONLY, "CREATE TABLE dbo.agent_scratch (x int)")


@needs[Principal.READ_ONLY]
def test_agent_cannot_drop_a_view_it_can_read():
    with pytest.raises(pyodbc.Error):
        _execute(Principal.READ_ONLY, "DROP VIEW dbo.VW_ROLE_TASKS")


# --- USR_FDE_LOAD: ingestion -------------------------------------------------

@needs[Principal.LOAD]
def test_loader_can_read_core():
    _execute(Principal.LOAD, "SELECT TOP 1 * FROM core.task")


@needs[Principal.LOAD]
def test_loader_cannot_update_a_fact_in_place():
    """Append-only is a grant, not just a convention in the loader code."""
    with pytest.raises(pyodbc.Error):
        _execute(Principal.LOAD,
                 "UPDATE core.task SET statement = 'tampered' WHERE 1 = 0")


@needs[Principal.LOAD]
def test_loader_cannot_delete_a_fact():
    with pytest.raises(pyodbc.Error):
        _execute(Principal.LOAD, "DELETE FROM core.task WHERE 1 = 0")


@needs[Principal.LOAD]
def test_loader_cannot_mutate_a_source_document():
    """Source artefacts are immutable snapshots identified by their digest."""
    with pytest.raises(pyodbc.Error):
        _execute(Principal.LOAD,
                 "UPDATE ref.source_document SET sha256 = REPLICATE('f',64) "
                 "WHERE 1 = 0")


@needs[Principal.LOAD]
def test_loader_cannot_read_the_agent_audit_log():
    with pytest.raises(pyodbc.Error):
        _execute(Principal.LOAD, "SELECT TOP 1 * FROM audit.AgentAuditLog")


# --- USR_FDE_SCORE: the scoring service -------------------------------------

@needs[Principal.SCORE]
def test_scorer_can_read_evidence():
    _execute(Principal.SCORE, "SELECT TOP 1 * FROM core.exposure_estimate")


@needs[Principal.SCORE]
def test_scorer_cannot_write_a_fact():
    """It consumes evidence; it does not author it."""
    with pytest.raises(pyodbc.Error):
        _execute(Principal.SCORE,
                 "INSERT INTO core.task (task_id, soc_code, statement, "
                 "weight_source, source_doc_id) VALUES ('x', '13-2051.00', "
                 "'invented', 'equal', 'onet_task_statements')")


@needs[Principal.SCORE]
def test_scorer_cannot_amend_a_persisted_verdict():
    with pytest.raises(pyodbc.Error):
        _execute(Principal.SCORE,
                 "UPDATE score.role_verdict SET caveats = 'none' WHERE 1 = 0")


@needs[Principal.SCORE]
def test_scorer_cannot_read_the_agent_audit_log():
    with pytest.raises(pyodbc.Error):
        _execute(Principal.SCORE, "SELECT TOP 1 * FROM audit.AgentAuditLog")


# --- USR_FDE_AUDIT: the audit adapter ---------------------------------------

@needs[Principal.AUDIT]
def test_audit_adapter_can_append_to_the_log():
    _execute(Principal.AUDIT,
             "INSERT INTO audit.AgentAuditLog (node_invoked, status) "
             "VALUES ('privilege-test', 'ok')")


@needs[Principal.AUDIT]
def test_audit_adapter_cannot_read_what_it_writes():
    """INSERT only. It is a pen, not a filing cabinet."""
    with pytest.raises(pyodbc.Error):
        _execute(Principal.AUDIT, "SELECT TOP 1 * FROM audit.AgentAuditLog")


@needs[Principal.AUDIT]
@pytest.mark.parametrize("table", ["core.task", "score.role_verdict",
                                   "ref.source_document"])
def test_audit_adapter_cannot_reach_application_data(table):
    with pytest.raises(pyodbc.Error):
        _execute(Principal.AUDIT, f"SELECT TOP 1 * FROM {table}")


@needs[Principal.AUDIT]
def test_audit_adapter_cannot_rewrite_history():
    with pytest.raises(pyodbc.Error):
        _execute(Principal.AUDIT,
                 "UPDATE audit.AgentAuditLog SET status = 'tampered' WHERE 1 = 0")


# --- The separation itself ---------------------------------------------------

@pytest.mark.skipif(not all(ISOLATED.values()),
                    reason="needs all four principals configured")
def test_no_principal_can_do_another_principals_job():
    """The four grants are disjoint, which is the whole design."""
    with pytest.raises(pyodbc.Error):
        _execute(Principal.READ_ONLY, "SELECT TOP 1 * FROM core.task")
    with pytest.raises(pyodbc.Error):
        _execute(Principal.AUDIT, "SELECT TOP 1 * FROM dbo.VW_ROLE_TASKS")
    with pytest.raises(pyodbc.Error):
        _execute(Principal.SCORE,
                 "INSERT INTO audit.AgentAuditLog (node_invoked) VALUES ('x')")
