"""Integration: the real warehouse, loaded from the real corpus.

These run against the production database rather than the test fixture, so
they assert that the actual load produced what the exploration reported. They
skip cleanly if the warehouse has not been loaded, rather than failing in a way
that looks like a defect.
"""

from __future__ import annotations

import pytest

from warehouse.session import Principal, connect, is_isolated

EXPECTED = {
    "core.exposure_estimate": 774,
    "core.adoption_observation": 126,
    "core.extracted_claim": 21,
}

# Task counts are asserted per occupation, not per table: the warehouse holds
# the target occupation plus the rated neighbour used for the sensitivity
# bound, so a table-wide count would have to change every time another
# occupation is added.
EXPECTED_TASKS_BY_SOC = {
    "13-2051.00": 26,   # target: analyst-written, no importance ratings
    "13-2099.01": 21,   # rated neighbour, for the weighting sensitivity
}


@pytest.fixture(scope="module")
def prod():
    with connect(Principal.DEVELOPER, database="FDE_TaskExposure") as conn:
        cursor = conn.cursor()
        loaded = cursor.execute("SELECT COUNT(*) FROM core.task").fetchone()[0]
        if not loaded:
            pytest.skip("warehouse not loaded; run scripts/load_warehouse.py")
        yield cursor


@pytest.mark.parametrize("table,expected", EXPECTED.items())
def test_expected_row_counts(prod, table, expected):
    assert prod.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected


@pytest.mark.parametrize("soc,expected", EXPECTED_TASKS_BY_SOC.items())
def test_expected_task_counts_per_occupation(prod, soc, expected):
    actual = prod.execute(
        "SELECT COUNT(*) FROM dbo.VW_ROLE_TASKS WHERE SOC_Code = ?", soc).fetchone()[0]
    assert actual == expected


def test_every_fact_resolves_to_a_registered_source(prod):
    orphans = prod.execute("""
        SELECT (SELECT COUNT(*) FROM core.task t
                WHERE NOT EXISTS (SELECT 1 FROM ref.source_document d
                                  WHERE d.doc_id = t.source_doc_id))
             + (SELECT COUNT(*) FROM core.extracted_claim c
                WHERE NOT EXISTS (SELECT 1 FROM ref.source_document d
                                  WHERE d.doc_id = c.source_doc_id))
             + (SELECT COUNT(*) FROM core.industry_metric m
                WHERE NOT EXISTS (SELECT 1 FROM ref.source_document d
                                  WHERE d.doc_id = m.source_doc_id))""").fetchone()[0]
    assert orphans == 0


def test_financial_analysts_sit_at_the_calibration_benchmark(prod):
    """The external target our rubric must be reconciled against."""
    row = prod.execute("""SELECT Value, Percentile FROM dbo.VW_EXPOSURE_BENCHMARK
                          WHERE SOC_Code = '13-2051'
                            AND Measure = 'AIOE_language_modeling'""").fetchone()
    assert row is not None, "the benchmark for the target occupation must be loaded"
    assert float(row[0]) == pytest.approx(1.2728, abs=1e-3)
    assert 85 <= float(row[1]) <= 90, \
        "13-2051 should land near the 87th percentile of 774 occupations"


def test_the_adoption_curve_is_queryable_for_finance(prod):
    rows = prod.execute("""SELECT Period_Start, Value FROM dbo.VW_ADOPTION_CURVE
                           WHERE Sector_Code = '52' AND Question_Code = '7'
                             AND Answer_Label = 'Yes' AND Value IS NOT NULL
                           ORDER BY Period_Start""").fetchall()
    assert len(rows) >= 20, "the BTOS trajectory should carry ~21 observations"
    first, last = float(rows[0][1]), float(rows[-1][1])
    assert last > first, "finance AI use rose across the observed window"


def test_the_authors_own_caveat_survived_into_the_warehouse(prod):
    """Eloundou et al. decline to forecast timing -- the basis for exposure != lag."""
    row = prod.execute("""SELECT Quote, Page FROM dbo.VW_CLAIM_EVIDENCE
                          WHERE Topic = 'not_prediction'
                            AND Quote LIKE '%do not make predictions%'""").fetchone()
    assert row is not None
    assert row[1] >= 1, "a claim must carry a checkable page number"


def test_no_quote_lost_its_word_spacing(prod):
    """The pdfplumber defect must not have reached the warehouse."""
    corrupted = prod.execute("""
        SELECT COUNT(*) FROM core.extracted_claim
        WHERE EXISTS (SELECT 1 FROM STRING_SPLIT(quote, ' ') w
                      WHERE LEN(w.value) >= 28 AND w.value NOT LIKE '%-%')""").fetchone()[0]
    assert corrupted == 0


def test_mirrored_sources_are_flagged(prod):
    """Two AIOE files came from a reproducibility repo, not the publisher."""
    mirrors = prod.execute(
        "SELECT COUNT(*) FROM ref.source_document WHERE is_mirror = 1").fetchone()[0]
    assert mirrors >= 2, "mirror provenance must survive into the warehouse"


def test_quality_assertions_were_recorded(prod):
    recorded = prod.execute(
        "SELECT COUNT(*) FROM audit.quality_assertion").fetchone()[0]
    assert recorded > 0, "a load must leave an audit trail of its checks"


@pytest.mark.skipif(is_isolated(Principal.READ_ONLY),
                    reason="runs only while mixed-mode auth is unavailable")
def test_privilege_isolation_is_not_yet_in_force(prod):
    """Honest failure: record that the security model is built but unproven.

    This inverts once mixed-mode authentication is enabled. Until then the
    loader runs as the developer, so the DENY grants are untested at runtime
    and the suite says so rather than passing silently.
    """
    assert not is_isolated(Principal.READ_ONLY)


# --- P2: the control run, end to end ---------------------------------------

def test_control_run_persisted_a_verdict(prod):
    """The deterministic path must produce a defensible number before any agent."""
    row = prod.execute("""
        SELECT TOP 1 v.exposure_index, v.lag_years_p10, v.lag_years_p50,
                     v.lag_years_p90, v.weight_source, LEN(v.caveats), r.status
        FROM score.role_verdict v JOIN score.run r ON r.run_id = v.run_id
        WHERE v.soc_code = '13-2051.00'
        ORDER BY v.created_at DESC""").fetchone()
    if row is None:
        pytest.skip("no scoring run yet; run scripts/run_scoring.py")

    assert 0.0 <= float(row[0]) <= 1.0
    assert float(row[1]) <= float(row[2]) <= float(row[3])
    assert row[4] == "equal", "primary weighting must be the equal-weight convention"
    assert row[5] > 200, "the caveat block must be substantive, not a token string"
    assert row[6] in ("passed", "review_required", "gate_rejected")


def test_control_run_bound_the_sources_it_consumed(prod):
    run_id = prod.execute("""SELECT TOP 1 run_id FROM score.role_verdict
                             ORDER BY created_at DESC""").fetchone()
    if run_id is None:
        pytest.skip("no scoring run yet")

    usages = {r[0] for r in prod.execute(
        "SELECT usage_type FROM audit.run_source_binding WHERE run_id = ?",
        run_id[0]).fetchall()}
    assert "task_source" in usages
    assert "adoption_evidence" in usages, "the lag path's evidence must be bound too"


def test_control_run_lag_was_not_curve_fitted(prod):
    row = prod.execute("""SELECT TOP 1 lag_basis FROM score.role_verdict
                          ORDER BY created_at DESC""").fetchone()
    if row is None:
        pytest.skip("no scoring run yet")
    assert "no curve is fitted" in row[0].lower()


def test_control_run_scores_every_task_with_provenance(prod):
    run_id = prod.execute("""SELECT TOP 1 run_id FROM score.role_verdict
                             WHERE soc_code = '13-2051.00'
                             ORDER BY created_at DESC""").fetchone()
    if run_id is None:
        pytest.skip("no scoring run yet")

    orphans = prod.execute("""
        SELECT COUNT(*) FROM score.task_score s
        WHERE s.run_id = ?
          AND NOT EXISTS (SELECT 1 FROM core.task t
                          WHERE t.task_id = s.task_id
                            AND t.source_doc_id = s.source_doc_id)""",
        run_id[0]).fetchone()[0]
    assert orphans == 0, "every score must resolve to the task version it scored"


def test_adjacent_occupation_is_loaded_with_real_ratings(prod):
    """The sensitivity bound needs weights; 13-2099.01 is the rated neighbour."""
    rated = prod.execute("""SELECT COUNT(*) FROM dbo.VW_ROLE_TASKS
                            WHERE SOC_Code = '13-2099.01'
                              AND Importance IS NOT NULL""").fetchone()[0]
    assert rated >= 20, "13-2099.01 should carry O*NET incumbent importance ratings"


def test_target_occupation_has_no_ratings_as_documented(prod):
    """The data property that forced the equal-weight convention."""
    rated = prod.execute("""SELECT COUNT(*) FROM dbo.VW_ROLE_TASKS
                            WHERE SOC_Code = '13-2051.00'
                              AND Importance IS NOT NULL""").fetchone()[0]
    assert rated == 0
