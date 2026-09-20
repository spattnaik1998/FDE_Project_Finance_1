"""The agent-visible view layer.

These five views are the agent's entire data surface (TDD 3.1). Two properties
matter beyond "the query runs": every view must expose ``Source_Doc_ID`` so the
run-to-source binding can be populated, and the guarantees that carry the
project's guardrails into the data layer must hold on real rows.
"""

from __future__ import annotations

import pytest

from warehouse import loaders

VIEWS = ["VW_ROLE_TASKS", "VW_EXPOSURE_BENCHMARK", "VW_ADOPTION_CURVE",
         "VW_CLAIM_EVIDENCE", "VW_INDUSTRY_METRIC"]

SCALE = ("Felten/Raj/Seamans AI Occupational Exposure, language-modelling "
         "variant. A standardised relative index, not a probability.")


def _columns(cur, view: str) -> set[str]:
    return {r[0] for r in cur.execute("""
        SELECT c.name FROM sys.columns c JOIN sys.views v ON v.object_id = c.object_id
        WHERE v.name = ?""", view).fetchall()}


@pytest.mark.parametrize("view", VIEWS)
def test_view_exists(cur, view):
    cur.execute(f"SELECT TOP 0 * FROM dbo.{view}")


@pytest.mark.parametrize("view", VIEWS)
def test_view_exposes_source_doc_id(cur, view):
    """Without this the binding table cannot be populated on consumption."""
    assert "Source_Doc_ID" in _columns(cur, view)


def test_claim_view_always_carries_quote_and_page_together(cur, doc):
    """The structural answer to fabricated citations."""
    cur.execute("""INSERT INTO core.extracted_claim
                       (claim_id, topic, quote, page, source_doc_id)
                   VALUES ('c1','not_prediction',
                           'We do not make predictions about the adoption timeline.',
                           1, ?)""", doc)
    row = cur.execute(
        "SELECT Quote, Page, Publisher, Is_Mirror FROM dbo.VW_CLAIM_EVIDENCE").fetchone()
    assert row[0].startswith("We do not make predictions")
    assert row[1] == 1
    assert row[2], "the publisher must be available for citation"
    assert row[3] is not None, "mirror status must be visible to the gate"


def test_benchmark_view_cannot_return_a_value_without_its_scale_note(cur, doc):
    cur.execute("""INSERT INTO core.exposure_estimate
                       (soc_code, measure, value, percentile, scale_note, source_doc_id)
                   VALUES ('13-2051','AIOE_language_modeling', 1.27, 87.0, ?, ?)""",
                SCALE, doc)
    row = cur.execute(
        "SELECT Value, Scale_Note FROM dbo.VW_EXPOSURE_BENCHMARK").fetchone()
    assert float(row[0]) == pytest.approx(1.27)
    assert row[1].strip(), "an index without its scale statement is meaningless"


def test_adoption_view_distinguishes_suppressed_from_zero(cur, doc):
    loaders.load_adoption_observations(cur, [
        {"period": "202617", "period_start": "2026-04-20", "sector_code": "52",
         "measure": "BTOS Q7 [Yes]: did this business use AI?", "value": None,
         "unit": "percent", "geography": "US", "source_doc_id": doc},
        {"period": "202618", "period_start": "2026-04-27", "sector_code": "52",
         "measure": "BTOS Q7 [Yes]: did this business use AI?", "value": 36.5,
         "unit": "percent", "geography": "US", "source_doc_id": doc},
    ], {})

    rows = {r[0]: (r[1], r[2]) for r in cur.execute(
        "SELECT Period_Label, Value, Is_Suppressed FROM dbo.VW_ADOPTION_CURVE").fetchall()}
    assert rows["202617"][0] is None
    assert rows["202617"][1] in (1, True)
    assert float(rows["202618"][0]) == pytest.approx(36.5)
    assert rows["202618"][1] in (0, False)


def test_adoption_view_joins_the_sector_label(cur, doc):
    loaders.load_adoption_observations(cur, [
        {"period": "202618", "period_start": "2026-04-27", "sector_code": "52",
         "measure": "BTOS Q7 [Yes]: did this business use AI?", "value": 36.5,
         "unit": "percent", "geography": "US", "source_doc_id": doc}], {})
    label = cur.execute(
        "SELECT Sector_Label FROM dbo.VW_ADOPTION_CURVE").fetchone()[0]
    assert label == "Finance and insurance"


def test_role_tasks_view_joins_the_occupation_title(cur, doc, soc):
    loaders.load_tasks(cur, [{
        "task_id": "21579", "soc_code": soc, "occupation": "",
        "statement": "Advise clients on aspects of capitalization.",
        "task_type": None, "importance": None, "relevance_pct": None,
        "source_doc_id": doc}], {})
    row = cur.execute(
        "SELECT Occupation, Weight_Source FROM dbo.VW_ROLE_TASKS").fetchone()
    assert row[0] == "Financial and Investment Analysts"
    assert row[1] == "equal", "the aggregation convention must be visible to the agent"


def test_views_hide_superseded_versions(cur, doc, revised_doc, soc):
    for source, text in ((doc, "Original."), (revised_doc, "Revised.")):
        loaders.load_tasks(cur, [{
            "task_id": "t1", "soc_code": soc, "occupation": "",
            "statement": f"{text} Analyse financial statements for clients.",
            "task_type": None, "importance": None, "relevance_pct": None,
            "source_doc_id": source}], {})

    assert cur.execute("SELECT COUNT(*) FROM core.task WHERE task_id='t1'").fetchone()[0] == 2
    assert cur.execute("SELECT COUNT(*) FROM dbo.VW_ROLE_TASKS WHERE Task_ID='t1'").fetchone()[0] == 1
