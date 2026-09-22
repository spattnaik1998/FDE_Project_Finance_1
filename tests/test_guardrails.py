"""Structural guardrails: the database must refuse what the TDD forbids.

These are the claims the TDD makes about being enforced *structurally* rather
than by convention. Each is driven to failure deliberately. A guardrail that
cannot be demonstrated failing is one nobody should trust.

Ported from ``scripts/verify_database.py`` so the checks run in the test suite
rather than only on demand.
"""

from __future__ import annotations

import uuid

import pytest


def _run(cur, run_id: str, **over) -> None:
    fields = {"git_sha": "a" * 40, "config_hash": "b" * 64, "rubric_version": "v1",
              "calibration_policy_version": "provisional_v1", "status": "running"}
    fields.update(over)
    cur.execute("""INSERT INTO score.run
                       (run_id, git_sha, config_hash, rubric_version,
                        calibration_policy_version, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                run_id, fields["git_sha"], fields["config_hash"],
                fields["rubric_version"], fields["calibration_policy_version"],
                fields["status"])


def _verdict(cur, run_id: str, soc: str, **over) -> None:
    f = {"exposure_index": 0.5, "p10": 1, "p50": 3, "p90": 5,
         "caveats": "Adoption data is NAICS 52 while the cost line is 523."}
    f.update(over)
    cur.execute("""INSERT INTO score.role_verdict
                       (run_id, soc_code, exposure_index, lag_years_p10,
                        lag_years_p50, lag_years_p90, lag_basis,
                        augmentation_share, weight_source, caveats)
                   VALUES (?, ?, ?, ?, ?, ?, 'BTOS 2025-2026', 0.4, 'equal', ?)""",
                run_id, soc, f["exposure_index"], f["p10"], f["p50"], f["p90"],
                f["caveats"])


@pytest.fixture
def run_id(cur):
    rid = str(uuid.uuid4())
    _run(cur, rid)
    return rid


# --- A verdict cannot exist without stated caveats -------------------------

def test_verdict_with_blank_caveats_is_refused(cur, run_id, soc):
    with pytest.raises(Exception):
        _verdict(cur, run_id, soc, caveats="   ")


def test_verdict_with_caveats_is_accepted(cur, run_id, soc):
    _verdict(cur, run_id, soc)
    assert cur.execute("SELECT COUNT(*) FROM score.role_verdict").fetchone()[0] == 1


# --- A lag interval cannot be inverted --------------------------------------

def test_inverted_lag_interval_is_refused(cur, run_id, soc):
    with pytest.raises(Exception):
        _verdict(cur, run_id, soc, p10=9, p50=3, p90=1)


def test_equal_bounds_lag_interval_is_accepted(cur, run_id, soc):
    """A degenerate but ordered interval is legitimate."""
    _verdict(cur, run_id, soc, p10=3, p50=3, p90=3)


# --- Closed vocabularies -----------------------------------------------------

@pytest.mark.parametrize("status", ["running", "passed", "review_required",
                                    "failed", "gate_rejected"])
def test_every_documented_run_status_is_accepted(cur, status):
    _run(cur, str(uuid.uuid4()), status=status)


def test_invented_run_status_is_refused(cur):
    with pytest.raises(Exception):
        _run(cur, str(uuid.uuid4()), status="probably_fine")


def test_invented_task_direction_is_refused(cur, run_id, doc, soc):
    cur.execute("""INSERT INTO core.task
                       (task_id, soc_code, statement, weight_source, source_doc_id)
                   VALUES ('t1', ?, 'Analyse statements.', 'equal', ?)""", soc, doc)
    with pytest.raises(Exception):
        cur.execute("""INSERT INTO score.task_score
                           (run_id, task_id, source_doc_id, exposure_raw, tacitness,
                            exposure_adjusted, direction, confidence, rationale,
                            model, prompt_version)
                       VALUES (?, 't1', ?, 0.5, 0.2, 0.4, 'replaced', 'high',
                               'because', 'gpt-6-astra', 'v1')""", run_id, doc)


def test_invented_binding_usage_type_is_refused(cur, run_id, doc):
    with pytest.raises(Exception):
        cur.execute("""INSERT INTO audit.run_source_binding
                           (run_id, source_doc_id, usage_type)
                       VALUES (?, ?, 'something_invented')""", run_id, doc)


@pytest.mark.parametrize("usage", ["task_source", "exposure_benchmark",
                                   "adoption_evidence", "claim_evidence",
                                   "industry_metric"])
def test_every_documented_binding_usage_type_is_accepted(cur, run_id, doc, usage):
    cur.execute("""INSERT INTO audit.run_source_binding
                       (run_id, source_doc_id, usage_type) VALUES (?, ?, ?)""",
                run_id, doc, usage)


# --- Calibration disagreement must be explained -----------------------------

def _calibration(cur, run_id: str, outcome: str, explanation):
    cur.execute("""INSERT INTO score.calibration
                       (run_id, benchmark_measure, benchmark_percentile,
                        our_percentile, delta, within_tolerance, outcome, explanation)
                   VALUES (?, 'AIOE_language_modeling', 87.0, 62.0, -25.0, 0, ?, ?)""",
                run_id, outcome, explanation)


def test_review_required_without_explanation_is_refused(cur, run_id):
    with pytest.raises(Exception):
        _calibration(cur, run_id, "review_required", None)


def test_review_required_with_explanation_is_accepted(cur, run_id):
    _calibration(cur, run_id, "review_required",
                 "Equal-weight convention differs from the benchmark's estimand.")


def test_gate_rejected_needs_no_explanation(cur, run_id):
    """Unexplained disagreement is precisely what gate_rejected records."""
    _calibration(cur, run_id, "gate_rejected", None)


# --- The audit log is append-only in fact -----------------------------------

def test_audit_log_accepts_inserts(cur):
    """Asserts a delta, not an absolute count.

    The log is append-only and written under autocommit, so entries from other
    tests in the session survive a rollback. An absolute count would make this
    test order-dependent.
    """
    before = cur.execute("SELECT COUNT(*) FROM audit.AgentAuditLog").fetchone()[0]
    cur.execute("""INSERT INTO audit.AgentAuditLog (node_invoked, tool_invoked, status)
                   VALUES ('3A. Task Classifier', 'VW_ROLE_TASKS', 'ok')""")
    after = cur.execute("SELECT COUNT(*) FROM audit.AgentAuditLog").fetchone()[0]
    assert after == before + 1


def test_audit_log_update_raises(cur):
    cur.execute("INSERT INTO audit.AgentAuditLog (node_invoked, status) VALUES ('n','ok')")
    with pytest.raises(Exception, match="append-only"):
        cur.execute("UPDATE audit.AgentAuditLog SET status = 'tampered'")
        while cur.nextset():
            pass


def test_audit_log_delete_raises(cur):
    cur.execute("INSERT INTO audit.AgentAuditLog (node_invoked, status) VALUES ('n','ok')")
    with pytest.raises(Exception, match="append-only"):
        cur.execute("DELETE FROM audit.AgentAuditLog")
        while cur.nextset():
            pass


def test_tool_raw_output_is_stored_unmodified(cur):
    """A disputed figure must be attributable to evidence or to reasoning."""
    raw = '[{"Task_ID":"21579","Source_Doc_ID":"guardrail_probe"}]'
    cur.execute("""INSERT INTO audit.AgentAuditLog (tool_invoked, tool_raw_output)
                   VALUES ('guardrail_probe', ?)""", raw)
    stored = cur.execute("""SELECT TOP 1 tool_raw_output FROM audit.AgentAuditLog
                            WHERE tool_invoked = 'guardrail_probe'
                            ORDER BY entry_id DESC""").fetchone()[0]
    assert stored == raw


# --- Provenance is not optional ---------------------------------------------

@pytest.mark.parametrize("table,sql", [
    ("core.exposure_estimate",
     """INSERT INTO core.exposure_estimate
            (soc_code, measure, value, scale_note, source_doc_id)
        VALUES ('13-2051','AIOE', 1.27, 'A relative index.', 'missing_doc')"""),
    ("core.extracted_claim",
     """INSERT INTO core.extracted_claim (claim_id, topic, quote, page, source_doc_id)
        VALUES ('c1','lag','A sufficiently long verbatim quotation.', 4, 'missing_doc')"""),
    ("core.industry_metric",
     """INSERT INTO core.industry_metric
            (provider, series_id, period, value, source_doc_id)
        VALUES ('FRED','OPHNFB','2026-01-01', 120.0, 'missing_doc')"""),
])
def test_fact_without_a_registered_source_is_refused(cur, table, sql):
    with pytest.raises(Exception):
        cur.execute(sql)


def test_industry_metric_rejects_an_unknown_provider(cur, doc):
    with pytest.raises(Exception):
        cur.execute("""INSERT INTO core.industry_metric
                           (provider, series_id, period, value, source_doc_id)
                       VALUES ('BLOOMBERG','X','2026-01-01', 1.0, ?)""", doc)


# --- Occupation history is retained ------------------------------------------

def test_occupation_changes_are_versioned_not_lost(cur, soc):
    """ref.occupation is temporal so a run reproduces against its own metadata."""
    cur.execute("UPDATE ref.occupation SET title = 'Renamed Occupation' WHERE soc_code = ?", soc)
    history = cur.execute(
        "SELECT COUNT(*) FROM ref.occupation_history WHERE soc_code = ?", soc).fetchone()[0]
    assert history >= 1, "the prior title must survive in the history table"
