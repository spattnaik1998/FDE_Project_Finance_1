"""Loader behaviour: append-only, idempotent, and honest about missing data.

The two properties under test are the ones the architecture review turned on:
loading is idempotent on source hash, *and* a source revision leaves prior rows
untouched so a past run still resolves to what it actually saw. Those are
different requirements, and passing one does not imply the other.
"""

from __future__ import annotations

import pytest

from warehouse import loaders

SCALE = "Standardised relative index; higher means more exposed."


def _task(task_id: str, doc: str, soc: str = "13-2051.00", **over) -> dict:
    base = {"task_id": task_id, "soc_code": soc, "occupation": "",
            "statement": "Analyse financial statements and prepare reports.",
            "task_type": None, "importance": None, "relevance_pct": None,
            "source_doc_id": doc}
    base.update(over)
    return base


def _obs(period: str, doc: str, value, answer: str = "Yes", **over) -> dict:
    base = {"period": period, "period_start": "2026-04-27", "sector_code": "52",
            "measure": f"BTOS Q7 [{answer}]: did this business use AI?",
            "value": value, "unit": "percent", "geography": "US",
            "source_doc_id": doc}
    base.update(over)
    return base


def _claim(cid: str, doc: str, **over) -> dict:
    base = {"claim_id": cid, "topic": "lag_length",
            "quote": "The implementation lag for a general purpose technology runs to years.",
            "page": 6, "note": "", "source_doc_id": doc}
    base.update(over)
    return base


def _count(cur, table: str, where: str = "1=1") -> int:
    return cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


# --- Idempotency -----------------------------------------------------------

def test_loading_identical_tasks_twice_inserts_once(cur, doc, soc):
    tasks = [_task("t1", doc), _task("t2", doc)]
    first = loaders.load_tasks(cur, tasks, {})
    second = loaders.load_tasks(cur, tasks, {})

    assert first.inserted == 2
    assert second.inserted == 0, "second load must insert nothing"
    assert second.skipped_existing == 2
    assert _count(cur, "core.task") == 2


def test_loading_identical_claims_twice_inserts_once(cur, doc):
    claims = [_claim("d1:lag_length:6:0", doc)]
    assert loaders.load_claims(cur, claims, {}).inserted == 1
    assert loaders.load_claims(cur, claims, {}).inserted == 0
    assert _count(cur, "core.extracted_claim") == 1


def test_loading_identical_observations_twice_inserts_once(cur, doc):
    obs = [_obs("202618", doc, 36.5)]
    assert loaders.load_adoption_observations(cur, obs, {}).inserted == 1
    assert loaders.load_adoption_observations(cur, obs, {}).inserted == 0
    assert _count(cur, "core.adoption_observation") == 1


# --- Revision handling: the reproducibility requirement --------------------

def test_revision_appends_and_leaves_prior_row_intact(cur, doc, revised_doc, soc):
    """A revised artefact must not disturb what an earlier run consumed."""
    loaders.load_tasks(cur, [_task("t1", doc, statement="Original statement text.")], {})
    loaders.load_tasks(cur, [_task("t1", revised_doc, statement="Revised statement text.")], {})

    rows = cur.execute("""SELECT source_doc_id, statement, is_current
                          FROM core.task WHERE task_id = 't1'
                          ORDER BY source_doc_id""").fetchall()
    assert len(rows) == 2, "revision must append, not overwrite"

    original = next(r for r in rows if r[0] == doc)
    assert original[1] == "Original statement text.", \
        "the prior version's content must survive the revision verbatim"


def test_revision_demotes_older_version_from_current(cur, doc, revised_doc, soc):
    loaders.load_tasks(cur, [_task("t1", doc)], {})
    loaders.load_tasks(cur, [_task("t1", revised_doc)], {})

    current = cur.execute("""SELECT source_doc_id FROM core.task
                             WHERE task_id = 't1' AND is_current = 1""").fetchall()
    assert len(current) == 1, "exactly one version may be current"
    assert current[0][0] == revised_doc


def test_view_shows_only_the_current_version(cur, doc, revised_doc, soc):
    loaders.load_tasks(cur, [_task("t1", doc, statement="Original statement text.")], {})
    loaders.load_tasks(cur, [_task("t1", revised_doc, statement="Revised statement text.")], {})

    rows = cur.execute(
        "SELECT Statement, Source_Doc_ID FROM dbo.VW_ROLE_TASKS WHERE Task_ID = 't1'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Revised statement text."
    assert rows[0][1] == revised_doc


# --- Suppressed cells: missing is not zero ---------------------------------

def test_suppressed_observation_is_null_not_zero(cur, doc):
    loaders.load_adoption_observations(cur, [_obs("202618", doc, None)], {})
    row = cur.execute("""SELECT value, is_suppressed FROM core.adoption_observation
                         WHERE period_label = '202618'""").fetchone()
    assert row[0] is None, "a suppressed cell must never be zero-filled"
    assert row[1] is True or row[1] == 1


def test_present_observation_is_not_marked_suppressed(cur, doc):
    loaders.load_adoption_observations(cur, [_obs("202618", doc, 36.5)], {})
    row = cur.execute("""SELECT value, is_suppressed FROM core.adoption_observation
                         WHERE period_label = '202618'""").fetchone()
    assert float(row[0]) == pytest.approx(36.5)
    assert row[1] is False or row[1] == 0


# --- Parsing and normalisation ---------------------------------------------

def test_measure_string_is_split_into_columns(cur, doc):
    loaders.load_adoption_observations(cur, [_obs("202618", doc, 36.5, answer="Yes")], {})
    row = cur.execute("""SELECT survey, question_code, answer_label
                         FROM core.adoption_observation""").fetchone()
    assert row[0] == "BTOS"
    assert row[1] == "7"
    assert row[2] == "Yes", "answer must be a column, not buried in prose"


def test_na_task_type_is_stored_as_null(cur, doc, soc):
    """O*NET has no Core/Supplemental split for 13-2051; 'n/a' is not a value."""
    loaders.load_tasks(cur, [_task("t1", doc, task_type="n/a")], {})
    assert cur.execute("SELECT task_type FROM core.task").fetchone()[0] is None


def test_weight_source_is_recorded_on_every_task(cur, doc, soc):
    """The aggregation convention must travel with the data (decision 1)."""
    loaders.load_tasks(cur, [_task("t1", doc)], {})
    assert cur.execute("SELECT weight_source FROM core.task").fetchone()[0] == "equal"


def test_adjacent_soc_weighting_is_recorded_distinctly(cur, doc, soc):
    loaders.load_tasks(cur, [_task("t1", doc)], {}, weight_source="adjacent_soc")
    assert cur.execute("SELECT weight_source FROM core.task").fetchone()[0] == "adjacent_soc"


# --- Exposure percentiles ---------------------------------------------------

def test_percentile_is_computed_across_the_full_distribution(cur, doc):
    estimates = [
        {"soc_code": f"00-{i:04d}", "occupation": None, "measure": "AIOE_language_modeling",
         "value": float(i), "scale_note": SCALE, "source_doc_id": doc}
        for i in range(100)
    ]
    loaders.load_exposure_estimates(cur, estimates, {})
    row = cur.execute("""SELECT percentile FROM core.exposure_estimate
                         WHERE soc_code = '00-0087'""").fetchone()
    assert float(row[0]) == pytest.approx(87.0), \
        "percentile must rank within the whole distribution, not a subset"


def test_exposure_estimate_requires_a_scale_note(cur, doc):
    bad = [{"soc_code": "13-2051", "occupation": None, "measure": "AIOE_language_modeling",
            "value": 1.27, "scale_note": "", "source_doc_id": doc}]
    with pytest.raises(Exception):
        loaders.load_exposure_estimates(cur, bad, {})


# --- Provenance -------------------------------------------------------------

def test_fact_with_unknown_source_document_is_refused(cur, soc):
    with pytest.raises(Exception):
        loaders.load_tasks(cur, [_task("t1", "no_such_document")], {})


def test_doc_map_redirects_facts_to_the_effective_version(cur, doc, revised_doc, soc):
    """When registration returns a new version id, facts must follow it."""
    loaders.load_tasks(cur, [_task("t1", "d1")], {"d1": revised_doc})
    assert cur.execute("SELECT source_doc_id FROM core.task").fetchone()[0] == revised_doc


def test_claim_id_is_rewritten_to_match_the_effective_version(cur, doc, revised_doc):
    loaders.load_claims(cur, [_claim("d1:lag_length:6:0", "d1")], {"d1": revised_doc})
    row = cur.execute("SELECT claim_id, source_doc_id FROM core.extracted_claim").fetchone()
    assert row[1] == revised_doc
    assert row[0].startswith(revised_doc), \
        "claim_id is version-scoped, so it must track the version it came from"
