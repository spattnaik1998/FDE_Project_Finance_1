"""The agent's data surface: six tools, five views, nothing else reachable.

Three properties carry real weight and each is driven adversarially:

* **Scope** — a tool cannot be made to read a base table even by a caller that
  wants it to.
* **Provenance** — a row without ``Source_Doc_ID`` raises rather than being
  returned, because it could otherwise appear in an output with no traceable
  origin.
* **Consumption** — the binding records what a run *drew on*, not what happened
  to be loaded.

Tools open their own connections, so these tests seed committed data into the
test database and clean it up afterwards rather than using the rolled-back
transaction fixture.
"""

from __future__ import annotations

import json

import pytest

from tools.audit_adapter import AuditAdapter, AuditEntry, NullAuditAdapter, _serialise
from tools.consumption import ConsumptionTracker, ProvenanceMissing, UsageType
from tools.definitions import (
    TOOL_SPECS,
    anthropic_tools,
    dispatch,
    openai_tools,
    spec_names,
)
from tools.evidence import (
    ALLOWED_VIEWS,
    EvidenceTools,
    ToolError,
    ToolScopeViolation,
)
from warehouse.session import Principal, connect

DOC = "tools_doc"
SOC = "13-2051.00"
# The benchmark keys on the 6-digit SOC; O*NET task statements carry the
# 8-digit detail code. Two code systems, as in production.
SOC_6DIGIT = "13-2051"
LONG_QUOTE = ("We do not make predictions about the development or adoption "
              "timeline of such large language models.")


@pytest.fixture(scope="module")
def tools_db(test_database):
    """Committed seed data in the test database, removed afterwards."""
    with connect(Principal.DEVELOPER, database=test_database,
                 autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.source_document WHERE doc_id = ?)
            INSERT INTO ref.source_document
                (doc_id, title, publisher, url, format, sha256, bytes,
                 retrieved_at, is_mirror, verified_against_publisher)
            VALUES (?, 'Seed document', 'Seed publisher', 'http://seed.test',
                    'pdf', REPLICATE('c', 64), 42, SYSUTCDATETIME(), 1, 0)""",
            DOC, DOC)
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.occupation WHERE soc_code = ?)
            INSERT INTO ref.occupation (soc_code, title, domain_source,
                                        has_onet_ratings)
            VALUES (?, 'Financial and Investment Analysts', 'Analyst', 0)""",
            SOC, SOC)
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.naics_sector WHERE sector_code = '52')
            INSERT INTO ref.naics_sector (sector_code, label, level)
            VALUES ('52', 'Finance and insurance', 2)""")

        for task_id, statement in (("tt1", "Prepare plans of action for investment."),
                                   ("tt2", "Develop and maintain client relationships.")):
            cur.execute("""INSERT INTO core.task
                               (task_id, soc_code, statement, weight_source,
                                source_doc_id)
                           VALUES (?, ?, ?, 'equal', ?)""",
                        task_id, SOC, statement, DOC)

        cur.execute("""INSERT INTO core.exposure_estimate
                           (soc_code, measure, value, percentile, scale_note,
                            source_doc_id)
                       VALUES ('13-2051', 'AIOE_language_modeling', 1.2728, 86.82,
                               'A standardised relative index, not a probability.', ?)""",
                    DOC)

        for period, start, value, suppressed in (("202601", "2026-01-05", 30.7, 0),
                                                 ("202610", "2026-03-09", None, 1),
                                                 ("202618", "2026-04-27", 36.5, 0)):
            cur.execute("""INSERT INTO core.adoption_observation
                               (survey, period_label, period_start, sector_code,
                                question_code, answer_label, value, unit,
                                is_suppressed, source_doc_id)
                           VALUES ('BTOS', ?, ?, '52', '7', 'Yes', ?, 'percent', ?, ?)""",
                        period, start, value, suppressed, DOC)

        cur.execute("""INSERT INTO core.extracted_claim
                           (claim_id, topic, quote, page, source_doc_id)
                       VALUES (?, 'not_prediction', ?, 1, ?)""",
                    f"{DOC}:not_prediction:1:0", LONG_QUOTE, DOC)
        cur.execute("""INSERT INTO core.extracted_claim
                           (claim_id, topic, quote, page, source_doc_id)
                       VALUES (?, 'lag_length',
                               'The implementation lag for a general purpose technology runs to years.',
                               6, ?)""", f"{DOC}:lag_length:6:0", DOC)

        cur.execute("""INSERT INTO core.industry_metric
                           (provider, series_id, industry_code, period, value,
                            unit, source_doc_id)
                       VALUES ('FRED', 'OPHNFB', NULL, '2026-01-01', 120.0, NULL, ?)""",
                    DOC)

    yield test_database

    with connect(Principal.DEVELOPER, database=test_database,
                 autocommit=True) as conn:
        cur = conn.cursor()
        for table in ("core.industry_metric", "core.extracted_claim",
                      "core.adoption_observation", "core.exposure_estimate",
                      "core.task"):
            cur.execute(f"DELETE FROM {table} WHERE source_doc_id = ?", DOC)
        cur.execute("DELETE FROM ref.source_document WHERE doc_id = ?", DOC)


@pytest.fixture
def tracker():
    return ConsumptionTracker(run_id="test-run")


@pytest.fixture
def tools(tools_db, tracker):
    return EvidenceTools(tracker=tracker, audit=NullAuditAdapter(),
                         database=tools_db)


# ===========================================================================
# The published surface
# ===========================================================================

def test_surface_is_six_tools_not_twenty_datasets():
    assert len(spec_names()) == 6
    assert set(spec_names()) == set(EvidenceTools.tool_names())


def test_every_spec_has_a_matching_implementation(tools):
    for name in spec_names():
        assert callable(getattr(tools, name))


def test_allowed_views_are_exactly_the_six_published_views():
    """Six views, and nothing that is not a view.

    Was "the five plus reference metadata", where the reference metadata was
    ref.source_document -- a base table. The grants deny db_fde_ro all of
    SCHEMA::ref, so the whitelist and the permission model contradicted each
    other, and nothing noticed while every connection ran as the developer.
    Citation metadata is now dbo.VW_SOURCE_DOCUMENT and the exception is gone.
    """
    expected = {
        "dbo.VW_ROLE_TASKS",
        "dbo.VW_EXPOSURE_BENCHMARK",
        "dbo.VW_ADOPTION_CURVE",
        "dbo.VW_CLAIM_EVIDENCE",
        "dbo.VW_INDUSTRY_METRIC",
        "dbo.VW_SOURCE_DOCUMENT",
    }
    assert set(ALLOWED_VIEWS) == expected
    assert all(v.startswith("dbo.VW_") for v in ALLOWED_VIEWS)


# ===========================================================================
# Scope enforcement
# ===========================================================================

@pytest.mark.parametrize("target", ["core.task", "score.role_verdict",
                                    "audit.AgentAuditLog", "dbo.VW_SOMETHING_ELSE",
                                    "ref.occupation"])
def test_querying_outside_the_surface_is_refused(tools, target):
    """A tool cannot be made to read a base table even deliberately."""
    with pytest.raises(ToolScopeViolation, match="outside it"):
        tools._query(f"SELECT TOP 1 * FROM {target}", (), targets=(target,))


def test_scope_violation_names_the_allowed_surface(tools):
    with pytest.raises(ToolScopeViolation) as exc:
        tools._query("SELECT 1", (), targets=("core.task",))
    assert "VW_ROLE_TASKS" in str(exc.value)


def test_no_tool_references_a_base_table_in_its_sql():
    """Structural check: parse the module, not just the runtime guard."""
    import ast
    import inspect

    import tools.evidence as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    # Require SELECT ... FROM, or the module docstring matches on prose.
    sql = [s for s in strings
           if "SELECT" in s.upper() and "FROM" in s.upper()]
    assert sql, "no SQL found to check; the test would pass vacuously"

    # ref. is in this list now. It was not, which is how the tool surface came
    # to read ref.source_document directly for four workstreams: the whitelist
    # carved out an exception, the forbidden list never mentioned ref, and every
    # connection ran as the developer so nothing refused it. Real isolation
    # broke the tool the moment it was enabled. Any base-table schema belongs
    # here, not just the ones that felt like evidence at the time.
    forbidden = ("core.task", "core.exposure_estimate", "core.adoption_observation",
                 "core.extracted_claim", "core.industry_metric", "score.",
                 "ref.source_document", "ref.occupation", "ref.naics_sector",
                 "audit.AgentAuditLog", "run_source_binding")
    offenders = [(f, s[:70]) for s in sql for f in forbidden if f in s]
    assert not offenders, f"tool SQL touches base tables: {offenders}"


# ===========================================================================
# get_tasks
# ===========================================================================

def test_get_tasks_returns_rows_with_provenance(tools):
    result = tools.get_tasks(SOC)
    assert result.row_count == 2
    assert all(row["Source_Doc_ID"] == DOC for row in result.rows)
    assert result.sources == {DOC}


def test_get_tasks_exposes_the_weighting_convention(tools):
    assert tools.get_tasks(SOC).rows[0]["Weight_Source"] == "equal"


def test_get_tasks_refuses_an_unknown_occupation_rather_than_substituting(tools):
    """Silently returning a neighbour would be the worst possible answer."""
    with pytest.raises(ToolError, match="must not be silently substituted"):
        tools.get_tasks("99-9999.00")


def test_get_tasks_records_consumption(tools, tracker):
    tools.get_tasks(SOC)
    assert tracker.sources_for(UsageType.TASK_SOURCE) == {DOC}


# ===========================================================================
# get_exposure_benchmarks
# ===========================================================================

def test_benchmark_always_carries_its_scale_note(tools):
    row = tools.get_exposure_benchmarks("13-2051").rows[0]
    assert row["Scale_Note"].strip()
    assert "not a probability" in row["Scale_Note"]


def test_benchmark_can_be_filtered_by_measure(tools):
    assert tools.get_exposure_benchmarks(
        "13-2051", measure="AIOE_language_modeling").row_count == 1
    assert tools.get_exposure_benchmarks(
        "13-2051", measure="does_not_exist").row_count == 0


def test_missing_benchmark_returns_empty_with_a_note_not_an_error(tools):
    """Uncalibrated is a legitimate state; the gate handles it."""
    result = tools.get_exposure_benchmarks("99-9999")
    assert result.row_count == 0
    assert "uncalibrated" in result.note


# ===========================================================================
# get_adoption_curve
# ===========================================================================

def test_adoption_curve_excludes_suppressed_cells_by_default(tools):
    result = tools.get_adoption_curve("52")
    assert result.row_count == 2
    assert all(row["Value"] is not None for row in result.rows)


def test_adoption_curve_can_surface_where_data_is_missing(tools):
    result = tools.get_adoption_curve("52", include_suppressed=True)
    assert result.row_count == 3
    suppressed = [r for r in result.rows if r["Is_Suppressed"]]
    assert len(suppressed) == 1
    assert suppressed[0]["Value"] is None, "suppressed must never be zero-filled"
    assert "never zero" in result.note


def test_adoption_curve_is_ordered_chronologically(tools):
    periods = [r["Period_Start"] for r in tools.get_adoption_curve("52").rows]
    assert periods == sorted(periods)


def test_adoption_curve_joins_the_sector_label(tools):
    assert tools.get_adoption_curve("52").rows[0]["Sector_Label"] == \
        "Finance and insurance"


# ===========================================================================
# search_claims
# ===========================================================================

def test_search_claims_returns_quote_and_page_together(tools):
    row = tools.search_claims(topic="not_prediction").rows[0]
    assert row["Quote"] == LONG_QUOTE
    assert row["Page"] == 1
    assert row["Publisher"]


def test_search_claims_by_free_text(tools):
    result = tools.search_claims(text="do not make predictions")
    assert result.row_count == 1


def test_search_claims_reports_the_fulltext_fallback(tools):
    """Honest degradation: adequate at this corpus size, and not beyond."""
    result = tools.search_claims(text="predictions")
    if not tools._has_fulltext():
        assert "Full-Text Search is not installed" in result.note
        assert "will be missed" in result.note


def test_search_claims_surfaces_unverified_mirrors(tools):
    """These block the Review Gate on a customer-deliverable run."""
    result = tools.search_claims(topic="lag_length")
    assert result.rows[0]["Is_Mirror"]
    assert "unverified mirror" in result.note


def test_search_claims_needs_a_query(tools):
    with pytest.raises(ToolError, match="needs a topic or a text query"):
        tools.search_claims()


def test_search_claims_honours_the_limit(tools):
    assert tools.search_claims(topic="not_prediction", limit=0).row_count == 0


# ===========================================================================
# get_industry_metric
# ===========================================================================

def test_industry_metric_returns_the_series(tools):
    result = tools.get_industry_metric("OPHNFB")
    assert result.row_count == 1
    assert result.rows[0]["Provider"] == "FRED"


def test_industry_metric_narrows_by_period(tools):
    assert tools.get_industry_metric("OPHNFB", start="2027-01-01").row_count == 0
    assert tools.get_industry_metric("OPHNFB", end="2027-01-01").row_count == 1


# ===========================================================================
# get_source_document
# ===========================================================================

def test_source_document_resolves_a_citation(tools):
    row = tools.get_source_document(DOC).rows[0]
    assert row["sha256"] == "c" * 64
    assert row["publisher"] == "Seed publisher"
    assert row["is_mirror"]


def test_source_document_registers_no_consumption(tools, tracker):
    """It is metadata about an artefact already bound; binding twice would
    double-count."""
    tools.get_source_document(DOC)
    assert tracker.is_empty()


def test_unknown_source_document_raises(tools):
    with pytest.raises(ToolError, match="No source document"):
        tools.get_source_document("no_such_doc")


# ===========================================================================
# Consumption tracking
# ===========================================================================

def test_tracker_starts_empty(tracker):
    assert tracker.is_empty()
    assert tracker.as_dict() == {}


def test_tracker_is_idempotent(tracker):
    assert tracker.record(UsageType.TASK_SOURCE, ["d1"]) == 1
    assert tracker.record(UsageType.TASK_SOURCE, ["d1"]) == 0
    assert tracker.total_bindings == 1


def test_same_source_under_two_usage_types_is_two_bindings(tracker):
    """One artefact can contribute in more than one capacity."""
    tracker.record(UsageType.TASK_SOURCE, ["d1"])
    tracker.record(UsageType.CLAIM_EVIDENCE, ["d1"])
    assert tracker.total_sources == 1
    assert tracker.total_bindings == 2


def test_tracker_ignores_empty_ids(tracker):
    tracker.record(UsageType.TASK_SOURCE, ["", None, "d1"])
    assert tracker.sources_for(UsageType.TASK_SOURCE) == {"d1"}


def test_row_without_provenance_is_refused(tracker):
    with pytest.raises(ProvenanceMissing, match="must not reach the caller"):
        tracker.record_rows(UsageType.TASK_SOURCE, [{"Task_ID": "t1"}])


def test_zero_rows_bind_nothing(tools, tracker):
    """Availability is not consumption."""
    tools.get_exposure_benchmarks("99-9999")
    assert tracker.is_empty()


def test_only_the_sources_actually_returned_are_bound(tools, tracker):
    """The warehouse holds many sources; only the queried one is bound."""
    tools.get_tasks(SOC)
    assert tracker.as_dict() == {"task_source": {DOC}}


def test_tracker_shape_matches_the_binding_writer(tools, tracker):
    tools.get_tasks(SOC)
    tools.get_adoption_curve("52")
    payload = tracker.as_dict()
    assert set(payload) <= {u.value for u in UsageType}
    assert all(isinstance(v, set) for v in payload.values())


def test_tracker_summary_reports_by_usage(tools, tracker):
    tools.get_tasks(SOC)
    tools.search_claims(topic="lag_length")
    summary = tracker.summary()
    assert summary["distinct_sources"] == 1
    assert summary["bindings"] == 2
    assert summary["by_usage"] == {"task_source": 1, "claim_evidence": 1}


# ===========================================================================
# Audit adapter
# ===========================================================================

def test_tool_calls_are_audited(tools_db, tracker):
    audit = NullAuditAdapter(run_id="test-run")
    tools = EvidenceTools(tracker=tracker, audit=audit, database=tools_db)
    tools.get_tasks(SOC)
    assert audit.entries_written == 1
    assert audit.emitted[0].tool_invoked == "get_tasks"


def test_tool_raw_output_is_stored_unmodified(tools_db, tracker):
    """A disputed figure must be attributable to evidence or to reasoning."""
    audit = NullAuditAdapter()
    tools = EvidenceTools(tracker=tracker, audit=audit, database=tools_db)
    result = tools.get_tasks(SOC)
    stored = json.loads(audit.emitted[0].tool_raw_output)
    assert len(stored) == result.row_count
    assert stored[0]["Task_ID"] == result.rows[0]["Task_ID"]


def test_serialise_truncates_and_says_so():
    from tools.audit_adapter import MAX_RAW_OUTPUT_CHARS
    text = _serialise("x" * (MAX_RAW_OUTPUT_CHARS + 500))
    assert "[TRUNCATED:" in text
    assert str(MAX_RAW_OUTPUT_CHARS) in text


def test_serialise_leaves_short_payloads_alone():
    assert _serialise("short") == "short"
    assert _serialise(None) is None
    assert json.loads(_serialise([{"a": 1}])) == [{"a": 1}]


def test_audit_adapter_writes_to_the_real_log(tools_db):
    adapter = AuditAdapter(run_id=None, database=tools_db)
    before = _log_count(tools_db)
    assert adapter.model_call(node="review_gate", provider="anthropic",
                              model="claude-opus-5", prompt_version="v1",
                              decision={"outcome": "pass"},
                              input_tokens=100, output_tokens=20)
    assert _log_count(tools_db) == before + 1


def test_audit_adapter_records_the_model_decision(tools_db):
    adapter = AuditAdapter(database=tools_db)
    adapter.model_call(node="task_classifier", provider="openai",
                       model="gpt-6-astra", prompt_version="v2",
                       decision={"routine": "routine"})
    with connect(Principal.DEVELOPER, database=tools_db) as conn:
        row = conn.cursor().execute("""
            SELECT TOP 1 provider, model, prompt_version, llm_decision
            FROM audit.AgentAuditLog WHERE node_invoked = 'task_classifier'
            ORDER BY entry_id DESC""").fetchone()
    assert row[0] == "openai"
    assert row[2] == "v2"
    assert json.loads(row[3]) == {"routine": "routine"}


def test_disabled_adapter_writes_nothing(tools_db):
    adapter = AuditAdapter(database=tools_db, enabled=False)
    before = _log_count(tools_db)
    assert adapter.tool_call(tool="get_tasks", node="n", payload=[]) is False
    assert _log_count(tools_db) == before


def _log_count(database: str) -> int:
    with connect(Principal.DEVELOPER, database=database) as conn:
        return conn.cursor().execute(
            "SELECT COUNT(*) FROM audit.AgentAuditLog").fetchone()[0]


# ===========================================================================
# Model-facing definitions
# ===========================================================================

def test_openai_and_anthropic_specs_describe_the_same_tools():
    assert [t["name"] for t in openai_tools()] == spec_names()
    assert [t["name"] for t in anthropic_tools()] == spec_names()


def test_anthropic_specs_use_input_schema():
    for spec in anthropic_tools():
        assert "input_schema" in spec
        assert spec["input_schema"]["type"] == "object"


def test_openai_specs_are_function_typed():
    for spec in openai_tools():
        assert spec["type"] == "function"
        assert spec["parameters"]["additionalProperties"] is False


def test_every_spec_has_a_substantive_description():
    for spec in TOOL_SPECS:
        assert len(spec["description"]) > 80, \
            f"{spec['name']} needs a description a model can act on"


def test_descriptions_carry_the_guardrails_not_just_the_signature():
    """A caveat three thousand tokens away in a system prompt is easier to miss."""
    by_name = {s["name"]: s["description"] for s in TOOL_SPECS}
    assert "never zero" in by_name["get_adoption_curve"]
    assert "ONLY what this tool returns" in by_name["search_claims"]
    assert "meaningless without it" in by_name["get_exposure_benchmarks"]


def test_dispatch_routes_to_the_implementation(tools):
    result = dispatch(tools, "get_tasks", {"soc_code": SOC})
    assert result.row_count == 2


def test_dispatch_refuses_an_unknown_tool(tools):
    with pytest.raises(KeyError, match="published surface"):
        dispatch(tools, "drop_everything", {})


def test_dispatch_passes_keyword_arguments(tools):
    result = dispatch(tools, "get_adoption_curve",
                      {"sector_code": "52", "include_suppressed": True})
    assert result.row_count == 3


# ===========================================================================
# Binding reaches the database
# ===========================================================================

def test_consumption_is_written_to_run_source_binding(tools_db, tracker):
    """End to end: tools consume, the tracker accumulates, the binding persists."""
    import uuid

    from scoring import run as runner

    tools = EvidenceTools(tracker=tracker, audit=NullAuditAdapter(),
                          database=tools_db)
    tools.get_tasks(SOC)
    tools.get_adoption_curve("52")
    tools.search_claims(topic="lag_length")

    context = runner.new_run()
    context.run_id = str(uuid.uuid4())

    with connect(Principal.DEVELOPER, database=tools_db,
                 autocommit=False) as conn:
        cur = conn.cursor()
        runner.open_run(cur, context)
        written = runner.bind_sources(cur, context, tracker.as_dict())

        rows = cur.execute("""SELECT usage_type, source_doc_id
                              FROM audit.run_source_binding WHERE run_id = ?
                              ORDER BY usage_type""", context.run_id).fetchall()
        conn.rollback()

    assert written == 3
    assert {r[0] for r in rows} == {"task_source", "adoption_evidence",
                                    "claim_evidence"}
    assert all(r[1] == DOC for r in rows)


def test_a_benchmark_miss_on_an_onet_code_names_the_code_system(tools_db):
    """A zero result must not assert an absence that is false.

    VW_ROLE_TASKS carries O*NET's 8-digit codes; the AIOE benchmark keys on the
    6-digit SOC. A caller passing the task-style code gets zero rows even
    though a benchmark exists, and the note used to say "No published benchmark
    for this occupation" -- wrong, and wrong in the direction that matters,
    because a reader would record the run as uncalibrated for the wrong reason.
    """
    tools = EvidenceTools(tracker=ConsumptionTracker(run_id="soc-note"),
                          database=tools_db)

    result = tools.get_exposure_benchmarks(f"{SOC_6DIGIT}.00")

    assert result.row_count == 0
    assert SOC_6DIGIT in result.note
    assert "6-digit" in result.note
    assert "No published benchmark for this occupation" not in result.note


def test_a_genuine_absence_still_reads_as_an_absence(tools_db):
    """The mismatch note must not fire when there really is no benchmark."""
    tools = EvidenceTools(tracker=ConsumptionTracker(run_id="soc-note-2"),
                          database=tools_db)

    result = tools.get_exposure_benchmarks("99-9999.00")

    assert result.row_count == 0
    assert "No published benchmark for this occupation" in result.note


def test_every_allowed_object_is_a_view_not_a_base_table():
    """The whitelist may only name views.

    ALLOWED_VIEWS is the scope control, and it previously contained
    ref.source_document -- a base table. That contradicted the grants, which
    deny db_fde_ro all of SCHEMA::ref, and the contradiction was invisible
    while every connection ran as the developer. Naming the rule explicitly is
    cheaper than rediscovering it the next time isolation is switched on.
    """
    offenders = [obj for obj in ALLOWED_VIEWS
                 if not obj.split(".")[-1].startswith("VW_")]
    assert not offenders, (
        f"ALLOWED_VIEWS names non-view object(s): {offenders}. The agent reads "
        f"flat views and is denied every base table; a sixth published object "
        f"must be a view, not an exception carved into a table.")


def test_the_allowed_set_matches_the_granted_set():
    """The whitelist and the grants must not be able to drift apart.

    Whichever is wrong, disagreement between them is only discoverable by
    enabling real isolation and watching a tool fail -- which is how this was
    found.
    """
    from pathlib import Path

    grants = Path("sql/04_roles_and_permissions.sql").read_text(encoding="utf-8")
    granted = {line.split(" ON ")[1].split(" TO ")[0].strip()
               for line in grants.splitlines()
               if line.startswith("GRANT SELECT ON dbo.VW_")
               and "db_fde_ro" in line}

    assert granted == set(ALLOWED_VIEWS), (
        f"granted but not whitelisted: {granted - set(ALLOWED_VIEWS)}; "
        f"whitelisted but not granted: {set(ALLOWED_VIEWS) - granted}")
