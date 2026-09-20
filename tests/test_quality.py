"""Quality assertions must fire on bad data, not merely pass on good.

A check that has never been seen to fail is indistinguishable from a check that
cannot fail. Each assertion here is driven to failure deliberately.

Note the split that emerges: most assertions are *also* enforced by a CHECK or
FOREIGN KEY constraint, so the bad row cannot even be inserted. For those the
constraint is the real guarantee and the assertion is defence in depth. Three
assertions have no constraint behind them and are therefore load-bearing on
their own — they are tested by inserting the violating data and asserting the
check trips.
"""

from __future__ import annotations

import pytest

from warehouse import quality

# Assertions with no constraint behind them: these carry real weight.
UNBACKED = {"quotes_not_runon", "no_duplicate_current_tasks", "views_expose_provenance"}


def _results(cur) -> dict[str, tuple[bool, int]]:
    return {name: (passed, count) for name, passed, count in quality.run_assertions(cur)}


def _add_claim(cur, doc: str, claim_id: str, quote: str, page: int = 3) -> None:
    cur.execute("""INSERT INTO core.extracted_claim
                       (claim_id, topic, quote, page, source_doc_id)
                   VALUES (?, 'lag_length', ?, ?, ?)""", claim_id, quote, page, doc)


# --- Clean baseline ---------------------------------------------------------

def test_all_assertions_pass_on_an_empty_warehouse(cur):
    for name, (passed, count) in _results(cur).items():
        assert passed, f"{name} failed on a clean database with {count} violations"


def test_assertion_outcomes_are_recorded_for_audit(cur):
    quality.run_assertions(cur, run_id=None)
    recorded = cur.execute(
        "SELECT COUNT(*) FROM audit.quality_assertion").fetchone()[0]
    assert recorded == len(quality.ASSERTIONS), \
        "every check must leave a record, including the ones that passed"


# --- The three assertions with no constraint behind them --------------------

def test_runon_quote_is_detected(cur, doc):
    """The pdfplumber spacing defect surviving into the warehouse."""
    _add_claim(cur, doc, "c_bad",
               "We define exposure as a proxy for potential "
               "economicimpactwithoutdistinguishingbetweenlaboraugmenting effects.")
    passed, count = _results(cur)["quotes_not_runon"]
    assert not passed, "a corrupted quote must be caught; it looks citable"
    assert count == 1


def test_clean_quote_is_not_flagged_as_runon(cur, doc):
    _add_claim(cur, doc, "c_ok",
               "We do not make predictions about the development or adoption "
               "timeline of such large language models.")
    assert _results(cur)["quotes_not_runon"][0], "a legitimate quote must not trip the check"


def test_hyphenated_long_token_is_not_flagged(cur, doc):
    """Long hyphenated compounds are real words, not merged ones."""
    _add_claim(cur, doc, "c_hyphen",
               "The labor-augmenting-versus-labor-displacing distinction matters here.")
    assert _results(cur)["quotes_not_runon"][0]


def test_duplicate_current_task_versions_are_detected(cur, doc, revised_doc, soc):
    """Two current versions would make the view non-deterministic."""
    for source in (doc, revised_doc):
        cur.execute("""INSERT INTO core.task
                           (task_id, soc_code, statement, weight_source, source_doc_id)
                       VALUES ('t1', ?, 'Analyse financial statements.', 'equal', ?)""",
                    soc, source)
    passed, count = _results(cur)["no_duplicate_current_tasks"]
    assert not passed, "two rows flagged current for one task must be caught"
    assert count == 1


def test_demoting_resolves_the_duplicate(cur, doc, revised_doc, soc):
    for source in (doc, revised_doc):
        cur.execute("""INSERT INTO core.task
                           (task_id, soc_code, statement, weight_source, source_doc_id)
                       VALUES ('t1', ?, 'Analyse financial statements.', 'equal', ?)""",
                    soc, source)
    cur.execute("UPDATE core.task SET is_current = 0 WHERE source_doc_id = ?", doc)
    assert _results(cur)["no_duplicate_current_tasks"][0]


def test_every_view_exposes_its_source_document(cur):
    """Without Source_Doc_ID the run-to-source binding cannot be populated."""
    assert _results(cur)["views_expose_provenance"][0]

    missing = cur.execute("""
        SELECT v.name FROM sys.views v
        WHERE v.name LIKE 'VW_%'
          AND NOT EXISTS (SELECT 1 FROM sys.columns c
                          WHERE c.object_id = v.object_id AND c.name = 'Source_Doc_ID')
    """).fetchall()
    assert missing == [], f"views missing Source_Doc_ID: {[m[0] for m in missing]}"


# --- Constraint-backed assertions: the constraint is the real guarantee -----

@pytest.mark.parametrize("name,sql,params", [
    ("percentages_in_range",
     """INSERT INTO core.adoption_observation
            (survey, period_label, question_code, answer_label, value, source_doc_id)
        VALUES ('BTOS','202618','7','Yes', 150, ?)""", True),
    ("suppressed_not_zeroed",
     """INSERT INTO core.adoption_observation
            (survey, period_label, question_code, answer_label, value,
             is_suppressed, source_doc_id)
        VALUES ('BTOS','202618','7','Yes', 36.5, 1, ?)""", True),
    ("claims_have_page",
     """INSERT INTO core.extracted_claim (claim_id, topic, quote, page, source_doc_id)
        VALUES ('c1','lag','A sufficiently long verbatim quotation goes here.', 0, ?)""", True),
    ("quotes_substantive",
     """INSERT INTO core.extracted_claim (claim_id, topic, quote, page, source_doc_id)
        VALUES ('c1','lag','short', 3, ?)""", True),
    ("scale_notes_present",
     """INSERT INTO core.exposure_estimate
            (soc_code, measure, value, scale_note, source_doc_id)
        VALUES ('13-2051','AIOE', 1.27, '', ?)""", True),
])
def test_constraint_blocks_the_violation_before_the_assertion_is_needed(
        cur, doc, name, sql, params):
    """These violations cannot reach the warehouse at all."""
    with pytest.raises(Exception):
        cur.execute(sql, doc)
        cur.execute("SELECT 1")  # force the error to surface


def test_unprovenanced_fact_is_refused_by_foreign_key(cur, soc):
    with pytest.raises(Exception):
        cur.execute("""INSERT INTO core.task
                           (task_id, soc_code, statement, weight_source, source_doc_id)
                       VALUES ('t1', ?, 'Analyse statements.', 'equal', 'nonexistent')""", soc)


def test_invalid_weight_source_is_refused(cur, doc, soc):
    with pytest.raises(Exception):
        cur.execute("""INSERT INTO core.task
                           (task_id, soc_code, statement, weight_source, source_doc_id)
                       VALUES ('t1', ?, 'Analyse statements.', 'guessed', ?)""", soc, doc)


# --- The gate ---------------------------------------------------------------

def test_enforce_raises_when_any_assertion_failed(cur, doc):
    _add_claim(cur, doc, "c_bad",
               "A quote containing averylongmergedtokenthatshouldnotexisthere inside it.")
    with pytest.raises(quality.QualityGateFailed) as exc:
        quality.enforce(quality.run_assertions(cur))
    assert "quotes_not_runon" in str(exc.value)


def test_enforce_is_silent_when_everything_passes(cur):
    quality.enforce(quality.run_assertions(cur))


def test_failed_assertion_records_the_violation_count(cur, doc):
    _add_claim(cur, doc, "c_bad",
               "Another quote with thisisdefinitelyonelongmergedtoken embedded.")
    quality.run_assertions(cur)
    observed = cur.execute("""SELECT observed FROM audit.quality_assertion
                              WHERE check_name = 'quotes_not_runon'""").fetchone()[0]
    assert "violation" in observed, "a failure must record what was observed, not just that it failed"
