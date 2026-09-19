"""Adversarial verification of the database guardrails.

The TDD claims certain guardrails are *structural* -- enforced by the database
rather than by convention. This script tries to violate each one and asserts
that the database refuses. Every test runs inside a transaction that is rolled
back, so the schema is left clean.

A guardrail that cannot be demonstrated failing is a guardrail nobody should
trust.
"""

from __future__ import annotations

import sys
import uuid

sys.path.insert(0, "src")

import pyodbc

SERVER = "LAPTOP-FO95TROJ"
DATABASE = "FDE_TaskExposure"

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def connect() -> pyodbc.Connection:
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER};"
        f"DATABASE={DATABASE};Trusted_Connection=yes;TrustServerCertificate=yes",
        timeout=30, autocommit=False)


def seed(cur: pyodbc.Cursor) -> None:
    """Minimal parent rows so foreign keys resolve inside the transaction.

    Guarded, because script 05 seeds ref.occupation for real: the harness must
    coexist with legitimately present reference data rather than assume an
    empty database.
    """
    cur.execute("""
        IF NOT EXISTS (SELECT 1 FROM ref.source_document WHERE doc_id = 't_doc')
        INSERT INTO ref.source_document
            (doc_id, title, publisher, url, format, sha256, retrieved_at)
        VALUES ('t_doc', 'Test', 'Test', 'http://x', 'pdf', REPLICATE('a', 64), SYSUTCDATETIME())""")
    cur.execute("""
        IF NOT EXISTS (SELECT 1 FROM ref.occupation WHERE soc_code = '13-2051.00')
        INSERT INTO ref.occupation (soc_code, title, has_onet_ratings)
        VALUES ('13-2051.00', 'Financial and Investment Analysts', 0)""")


def _split_statements(sql: str) -> list[str]:
    """Split on semicolons that are NOT inside a quoted string literal.

    A naive split breaks any statement containing a semicolon in its data --
    which caveat text routinely does.
    """
    out, buf, in_quote = [], [], False
    for ch in sql:
        if ch == "'":
            in_quote = not in_quote
        if ch == ";" and not in_quote:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def _run(cur: pyodbc.Cursor, sql: str, params: tuple = ()) -> None:
    """Execute possibly-multiple statements, surfacing errors from every one.

    pyodbc only raises for the FIRST result set of a multi-statement batch, so
    a constraint violation in a later statement stays buried unless the sets
    are drained. Statements are therefore executed individually.
    """
    statements = [st.strip() for st in _split_statements(sql) if st.strip()]
    for i, statement in enumerate(statements):
        cur.execute(statement, params if (params and i == len(statements) - 1) else ())
        while cur.nextset():
            pass


def must_fail(name: str, sql: str, params: tuple = (), needs_seed: bool = True) -> None:
    """Assert the database REFUSES this statement."""
    conn = connect()
    cur = conn.cursor()
    try:
        if needs_seed:
            seed(cur)
        _run(cur, sql, params)
        results.append((name, FAIL, "statement was ACCEPTED but should have been refused"))
    except pyodbc.Error as exc:
        msg = str(exc)
        detail = next((p for p in msg.split("]") if "constraint" in p.lower()
                       or "append-only" in p.lower() or "permission" in p.lower()), msg[:110])
        results.append((name, PASS, detail.strip()[:110]))
    finally:
        conn.rollback()
        conn.close()


def must_succeed(name: str, sql: str, params: tuple = (), needs_seed: bool = True) -> None:
    """Assert a legitimate statement is ACCEPTED (guards against over-tight rules)."""
    conn = connect()
    cur = conn.cursor()
    try:
        if needs_seed:
            seed(cur)
        _run(cur, sql, params)
        results.append((name, PASS, "accepted as expected"))
    except pyodbc.Error as exc:
        results.append((name, FAIL, f"legitimate statement REFUSED: {str(exc)[:110]}"))
    finally:
        conn.rollback()
        conn.close()


RUN = str(uuid.uuid4())
RUN_INSERT = f"""
    INSERT INTO score.run (run_id, git_sha, config_hash, rubric_version,
                           calibration_policy_version, status)
    VALUES ('{RUN}', REPLICATE('a',40), REPLICATE('b',64), 'v1', 'provisional_v1', 'running');"""


def main() -> None:
    print("Adversarial guardrail verification\n" + "=" * 78)

    # --- Guardrail: a verdict cannot exist without stated caveats -----------
    must_fail(
        "role_verdict with EMPTY caveats is refused",
        RUN_INSERT + f"""
        INSERT INTO score.role_verdict
            (run_id, soc_code, exposure_index, lag_years_p10, lag_years_p50,
             lag_years_p90, lag_basis, augmentation_share, weight_source, caveats)
        VALUES ('{RUN}', '13-2051.00', 0.5, 1, 3, 5, 'basis', 0.4, 'equal', '   ')""")

    must_succeed(
        "role_verdict WITH caveats is accepted",
        RUN_INSERT + f"""
        INSERT INTO score.role_verdict
            (run_id, soc_code, exposure_index, lag_years_p10, lag_years_p50,
             lag_years_p90, lag_basis, augmentation_share, weight_source, caveats)
        VALUES ('{RUN}', '13-2051.00', 0.5, 1, 3, 5, 'basis', 0.4, 'equal',
                'Adoption data is NAICS 52; the cost line is 523.')""")

    # --- Guardrail: lag interval cannot be inverted -------------------------
    must_fail(
        "role_verdict with INVERTED lag interval (p10>p90) is refused",
        RUN_INSERT + f"""
        INSERT INTO score.role_verdict
            (run_id, soc_code, exposure_index, lag_years_p10, lag_years_p50,
             lag_years_p90, lag_basis, augmentation_share, weight_source, caveats)
        VALUES ('{RUN}', '13-2051.00', 0.5, 9, 3, 1, 'basis', 0.4, 'equal', 'stated')""")

    # --- Guardrail: a suppressed cell is missing, never zero ----------------
    must_fail(
        "adoption_observation marked suppressed WITH a value is refused",
        """INSERT INTO core.adoption_observation
               (survey, period_label, question_code, answer_label, value,
                is_suppressed, source_doc_id)
           VALUES ('BTOS', '202618', '7', 'Yes', 36.5, 1, 't_doc')""")

    must_succeed(
        "adoption_observation suppressed with NULL value is accepted",
        """INSERT INTO core.adoption_observation
               (survey, period_label, question_code, answer_label, value,
                is_suppressed, source_doc_id)
           VALUES ('BTOS', '202618', '7', 'Yes', NULL, 1, 't_doc')""")

    # --- Guardrail: percentages must be percentages -------------------------
    must_fail(
        "adoption_observation with value 150 is refused",
        """INSERT INTO core.adoption_observation
               (survey, period_label, question_code, answer_label, value, source_doc_id)
           VALUES ('BTOS', '202618', '7', 'Yes', 150, 't_doc')""")

    # --- Guardrail: a quote too short to check is not admissible ------------
    must_fail(
        "extracted_claim with a 5-character quote is refused",
        """INSERT INTO core.extracted_claim (claim_id, topic, quote, page, source_doc_id)
           VALUES ('c1', 'lag', 'short', 3, 't_doc')""")

    must_fail(
        "extracted_claim with page 0 is refused",
        """INSERT INTO core.extracted_claim (claim_id, topic, quote, page, source_doc_id)
           VALUES ('c1', 'lag', 'A sufficiently long verbatim quotation here.', 0, 't_doc')""")

    # --- Guardrail: an index without its scale statement is meaningless -----
    must_fail(
        "exposure_estimate with EMPTY scale_note is refused",
        """INSERT INTO core.exposure_estimate (soc_code, measure, value, scale_note, source_doc_id)
           VALUES ('13-2051.00', 'AIOE_language_modeling', 1.27, '', 't_doc')""")

    # --- Guardrail: an unprovenanced fact is not representable --------------
    must_fail(
        "core.task with a NON-EXISTENT source_doc_id is refused",
        """INSERT INTO core.task (task_id, soc_code, statement, weight_source, source_doc_id)
           VALUES ('t1', '13-2051.00', 'Analyse financial statements.', 'equal', 'no_such_doc')""")

    # --- Guardrail: calibration disagreement must be explained --------------
    must_fail(
        "calibration 'review_required' WITHOUT explanation is refused",
        RUN_INSERT + f"""
        INSERT INTO score.calibration
            (run_id, benchmark_measure, benchmark_percentile, our_percentile,
             delta, within_tolerance, outcome, explanation)
        VALUES ('{RUN}', 'AIOE_language_modeling', 87.0, 62.0, -25.0, 0, 'review_required', NULL)""")

    must_succeed(
        "calibration 'review_required' WITH explanation is accepted",
        RUN_INSERT + f"""
        INSERT INTO score.calibration
            (run_id, benchmark_measure, benchmark_percentile, our_percentile,
             delta, within_tolerance, outcome, explanation)
        VALUES ('{RUN}', 'AIOE_language_modeling', 87.0, 62.0, -25.0, 0, 'review_required',
                'Equal-weight convention differs from the benchmark estimand.')""")

    # --- Guardrail: the audit log is append-only IN FACT --------------------
    must_fail(
        "UPDATE on audit.AgentAuditLog raises (append-only trigger)",
        """INSERT INTO audit.AgentAuditLog (node_invoked, status) VALUES ('test','ok');
           UPDATE audit.AgentAuditLog SET status = 'tampered' WHERE node_invoked = 'test';""",
        needs_seed=False)

    must_fail(
        "DELETE on audit.AgentAuditLog raises (append-only trigger)",
        """INSERT INTO audit.AgentAuditLog (node_invoked, status) VALUES ('test','ok');
           DELETE FROM audit.AgentAuditLog WHERE node_invoked = 'test';""",
        needs_seed=False)

    must_succeed(
        "INSERT on audit.AgentAuditLog is accepted",
        """INSERT INTO audit.AgentAuditLog (node_invoked, tool_invoked, status)
           VALUES ('3A. Task Classifier', 'VW_ROLE_TASKS', 'ok')""",
        needs_seed=False)

    # --- Guardrail: enumerations are closed ---------------------------------
    must_fail(
        "run_source_binding with an unknown usage_type is refused",
        RUN_INSERT + f"""
        INSERT INTO ref.source_document
            (doc_id, title, publisher, url, format, sha256, retrieved_at)
        VALUES ('t_doc', 'Test', 'Test', 'http://x', 'pdf', REPLICATE('a',64), SYSUTCDATETIME());
        INSERT INTO audit.run_source_binding (run_id, source_doc_id, usage_type)
        VALUES ('{RUN}', 't_doc', 'something_invented')""",
        needs_seed=False)

    must_fail(
        "task_score with direction 'replaced' is refused (closed vocabulary)",
        """INSERT INTO score.task_score
               (run_id, task_id, source_doc_id, exposure_raw, tacitness,
                exposure_adjusted, direction, confidence, rationale, model, prompt_version)
           VALUES (NEWID(), 't1', 't_doc', 0.5, 0.2, 0.4, 'replaced', 'high', 'r', 'm', 'v1')""")

    # --- Report -------------------------------------------------------------
    print()
    width = max(len(n) for n, _, _ in results)
    for name, status, detail in results:
        mark = "OK " if status == PASS else "!! "
        print(f"{mark}{name:<{width}}  {detail}")

    failed = [r for r in results if r[1] == FAIL]
    print("\n" + "=" * 78)
    print(f"{len(results) - len(failed)}/{len(results)} guardrails verified")
    if failed:
        print(f"{len(failed)} FAILED:")
        for n, _, d in failed:
            print(f"  - {n}: {d}")
        sys.exit(1)
    print("Every guardrail is enforced by the database, not by convention.")


if __name__ == "__main__":
    main()
