"""The graph: a fixed node set, and independence visible in the topology.

W2 proved exposure and lag are independent at the module level, by parsing
imports. This proves it at the *graph* level: the two paths are parallel
branches out of retrieval that meet only at assembly, so coupling them would
require adding an edge — and these tests refuse one.

The workflow smoke tests drive the whole graph with fake providers, which is
the only way to assert what happens on a gated run, an out-of-scope request or
a fabricated figure. A live run proves the wiring; it cannot prove the
refusals.
"""

from __future__ import annotations

import uuid
import warnings

import pytest

warnings.filterwarnings("ignore")

from graph import build, runner
from nodes.state import NodeDeps, Phase, RunState
from providers.accounting import Ledger
from providers.base import ModelResponse, Usage
from scoring.schemas import Confidence, Direction
from tools.audit_adapter import NullAuditAdapter
from tools.consumption import ConsumptionTracker
from tools.evidence import EvidenceTools

SOC = "13-2051.00"
DOC = "graph_doc"
CLAIM_NOT_PREDICTION = f"{DOC}:not_prediction:1:0"
CLAIM_LAG = f"{DOC}:lag_length:6:0"


# ===========================================================================
# Topology -- the independence claim, checkable
# ===========================================================================

def test_the_node_set_is_fixed():
    """Not an open ReAct loop: the nodes are declared, not discovered."""
    graph_edges = build.edges()
    declared = set(build.NODE_NAMES)
    in_graph = {n for edge in graph_edges for n in edge
                if not n.startswith("__")}
    assert in_graph == declared


def test_lag_has_exactly_one_predecessor_and_it_is_retrieval():
    """The lag path reads adoption evidence. Nothing else feeds it."""
    assert build.predecessors(build.LAG_PATH) == {build.RETRIEVE}


def test_the_two_branches_share_no_state_field():
    """They run in the same superstep, so a shared field would be a race --
    and would couple the paths through state even though neither module
    imports the other."""
    assert build.concurrent_write_conflicts() == set()


def test_the_fan_in_is_symmetric():
    """Unequal branch lengths make LangGraph 0.3.34 fire the join twice."""
    assert build.predecessors(build.EXPOSURE_PATH) == {build.RETRIEVE}
    assert build.predecessors(build.LAG_PATH) == {build.RETRIEVE}


def test_the_exposure_chain_cannot_reach_the_lag_path():
    """The decisive assertion. Adding the coupling means deleting this test."""
    for node in build.EXPOSURE_CHAIN:
        assert not build.reaches(node, build.LAG_PATH), (
            f"{node} reaches {build.LAG_PATH}; the lag estimate must be "
            f"derivable from adoption evidence alone.")


def test_the_lag_path_cannot_reach_the_exposure_chain():
    """Independence has to hold in both directions to be independence."""
    for node in build.EXPOSURE_CHAIN:
        assert not build.reaches(build.LAG_PATH, node)


def test_both_paths_fan_out_from_retrieval():
    assert build.successors(build.RETRIEVE) >= {build.EXPOSURE_PATH,
                                                build.LAG_PATH}


def test_the_two_paths_meet_only_at_assembly():
    assert build.predecessors(build.ASSEMBLE) == {build.EXPOSURE_PATH,
                                                  build.LAG_PATH}


def test_the_gate_sits_between_assembly_and_synthesis():
    assert build.predecessors(build.GATE) == {build.ASSEMBLE}
    assert build.SYNTHESISE in build.successors(build.GATE)


def test_synthesis_is_reachable_only_through_the_gate():
    """No path may skip the approval gate."""
    assert build.predecessors(build.SYNTHESISE) == {build.GATE}


def test_the_gate_can_terminate_without_synthesis():
    """Asserted through the routing function, not the drawn edges.

    LangGraph's drawable graph omits conditional edges whose target is END, so
    the topology alone cannot show the termination branch. The routing function
    is the authority.
    """
    from nodes.state import GateDecision
    assert build.route_after_gate(
        _state(gate=GateDecision(outcome="gate_rejected"))) == "__end__"


def test_scoring_nodes_do_not_route_to_each_other():
    assert build.LAG_PATH not in build.successors(build.EXPOSURE_PATH)
    assert build.EXPOSURE_PATH not in build.successors(build.LAG_PATH)


# ===========================================================================
# Routing functions -- including the END branches the drawn graph omits
# ===========================================================================

def _state(**over) -> RunState:
    state = RunState(run_id="r", request="q")
    for key, value in over.items():
        setattr(state, key, value)
    return state


def test_out_of_scope_routes_to_end():
    assert build.route_after_intent(_state(phase=Phase.OUT_OF_SCOPE)) == "__end__"


def test_a_resolved_scope_routes_to_retrieval():
    assert build.route_after_intent(_state(phase=Phase.SCOPED)) == build.RETRIEVE


def test_retrieval_fans_out_to_both_paths():
    targets = build.route_after_retrieval(_state(phase=Phase.EVIDENCE_RETRIEVED))
    assert set(targets) == {build.EXPOSURE_PATH, build.LAG_PATH}


def test_failed_retrieval_routes_to_end():
    assert build.route_after_retrieval(_state(phase=Phase.FAILED)) == ["__end__"]


@pytest.mark.parametrize("outcome,expected", [
    ("pass", build.SYNTHESISE),
    ("review_required", "__end__"),
    ("gate_rejected", "__end__"),
])
def test_only_a_pass_reaches_synthesis(outcome, expected):
    from nodes.state import GateDecision
    assert build.route_after_gate(_state(gate=GateDecision(outcome=outcome))) == expected


def test_an_absent_gate_does_not_reach_synthesis():
    assert build.route_after_gate(_state(gate=None)) == "__end__"


# ===========================================================================
# Fake providers for the workflow tests
# ===========================================================================

class ScriptedProvider:
    """Answers per stage, so one fake drives the whole graph."""

    name = "scripted"
    model = "scripted-model"

    def __init__(self, answers: dict, narrative: str = ""):
        self.answers = answers
        self.narrative = narrative
        self.stages: list[str] = []

    def _resp(self, structured=None, text=None):
        return ModelResponse(provider=self.name, model=self.model, text=text,
                             structured=structured,
                             usage=Usage(input_tokens=5, output_tokens=5),
                             duration_ms=1)

    def structured(self, prompt, schema, *, schema_name, system=None,
                   max_tokens=2048, context=None):
        stage = context.stage if context else schema_name
        self.stages.append(stage)
        if schema_name not in self.answers:
            raise AssertionError(f"no scripted answer for {schema_name}")
        return self._resp(structured=self.answers[schema_name])

    def complete(self, prompt, *, system=None, max_tokens=1024, context=None):
        self.stages.append(context.stage if context else "complete")
        return self._resp(text=self.narrative)


def scripted(*, soc=SOC, sector="52", gate_outcome="pass",
             narrative="", direction="augment") -> ScriptedProvider:
    return ScriptedProvider({
        "scope_resolution": {"resolved": True, "soc_code": soc,
                             "naics_sector": sector, "geography": "US",
                             "rationale": "Maps to the analyst occupation."},
        "task_classification": {
            "routine": "routine", "modality": "cognitive", "tacitness": "low",
            "direction": direction, "confidence": "high",
            "rationale": "Rule-following drafting work.",
            "evidence_claim_ids": [CLAIM_NOT_PREDICTION]},
        "gate_decision": {"outcome": gate_outcome,
                          "checks_passed": ["caveats_non_empty"],
                          "checks_failed": [] if gate_outcome == "pass"
                                           else ["evidence_too_thin"],
                          "reasoning": "Scripted decision."},
    }, narrative=narrative)


@pytest.fixture(scope="module")
def graph_db(test_database):
    """A three-task fixture occupation, committed, cleaned up afterwards."""
    from warehouse.session import Principal, connect

    with connect(Principal.DEVELOPER, database=test_database,
                 autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM ref.source_document WHERE doc_id = ?)
            INSERT INTO ref.source_document
                (doc_id, title, publisher, url, format, sha256, bytes,
                 retrieved_at, is_mirror, verified_against_publisher)
            VALUES (?, 'Graph fixture', 'Fixture publisher', 'http://g.test',
                    'pdf', REPLICATE('e', 64), 10, SYSUTCDATETIME(), 0, 1)""",
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

        for i, statement in enumerate([
                "Prepare plans of action for investment.",
                "Draw charts and graphs to illustrate technical reports.",
                "Develop and maintain client relationships."], start=1):
            cur.execute("""INSERT INTO core.task
                               (task_id, soc_code, statement, weight_source,
                                source_doc_id)
                           VALUES (?, ?, ?, 'equal', ?)""",
                        f"g{i}", SOC, statement, DOC)

        cur.execute("""INSERT INTO core.exposure_estimate
                           (soc_code, measure, value, percentile, scale_note,
                            source_doc_id)
                       VALUES ('13-2051', 'AIOE_language_modeling', 1.2728, 86.82,
                               'A standardised relative index.', ?)""", DOC)

        for period, start, value in (("202601", "2025-06-09", 29.9),
                                     ("202618", "2026-04-27", 36.5)):
            cur.execute("""INSERT INTO core.adoption_observation
                               (survey, period_label, period_start, sector_code,
                                question_code, answer_label, value, unit,
                                source_doc_id)
                           VALUES ('BTOS', ?, ?, '52', '7', 'Yes', ?, 'percent', ?)""",
                        period, start, value, DOC)

        cur.execute("""INSERT INTO core.extracted_claim
                           (claim_id, topic, quote, page, source_doc_id)
                       VALUES (?, 'not_prediction',
                               'We do not make predictions about the adoption timeline.',
                               1, ?)""", CLAIM_NOT_PREDICTION, DOC)
        cur.execute("""INSERT INTO core.extracted_claim
                           (claim_id, topic, quote, page, source_doc_id)
                       VALUES (?, 'lag_length',
                               'The implementation lag for a general purpose technology runs to years.',
                               6, ?)""", CLAIM_LAG, DOC)

    yield test_database

    with connect(Principal.DEVELOPER, database=test_database,
                 autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM audit.run_source_binding")
        cur.execute("DELETE FROM score.calibration")
        cur.execute("DELETE FROM score.role_verdict")
        cur.execute("DELETE FROM score.task_score")
        cur.execute("DELETE FROM score.run")
        for table in ("core.industry_metric", "core.extracted_claim",
                      "core.adoption_observation", "core.exposure_estimate",
                      "core.task"):
            cur.execute(f"DELETE FROM {table} WHERE source_doc_id = ?", DOC)
        cur.execute("DELETE FROM ref.source_document WHERE doc_id = ?", DOC)


def run_graph(graph_db, provider, *, deliverable=False, persist=True,
              our_percentile=None):
    """Drive the graph.

    ``our_percentile`` defaults to None, matching production, which means
    calibration returns review_required and no report is produced. Tests that
    need the pass path supply one -- see
    ``test_production_cannot_currently_reach_a_pass``.
    """
    return runner.invoke("How exposed are our analysts?",
                         deliverable=deliverable, database=graph_db,
                         provider_for=lambda stage: provider, persist=persist,
                         our_percentile=our_percentile)


# ===========================================================================
# Workflow smoke tests
# ===========================================================================

GOOD_NARRATIVE = (
    "The exposure index is 0.9 under equal weighting across 3 tasks. "
    "The adoption lag spans 5.0 to 30.0 years. Exposure and timing are "
    "separate findings. Adoption evidence is NAICS 52 while the cost line "
    "is 523.")


def test_a_complete_run_produces_a_verdict_with_provenance(graph_db):
    outcome = run_graph(graph_db, scripted(narrative=GOOD_NARRATIVE))

    assert outcome.state.verdict is not None
    assert outcome.state.scope.soc_code == SOC
    assert len(outcome.state.scores) == 3
    assert outcome.persisted
    assert outcome.bindings > 0, "a run must bind the sources it consumed"
    assert outcome.state.verdict.caveats


def test_the_lag_is_computed_and_not_curve_fitted(graph_db):
    outcome = run_graph(graph_db, scripted(narrative=GOOD_NARRATIVE))
    lag = outcome.state.verdict.lag
    assert lag.p10 <= lag.p50 <= lag.p90
    assert lag.curve_fitted is False


def test_the_lag_does_not_move_when_classification_changes(graph_db):
    """Independence, end to end through the graph."""
    augmenting = run_graph(graph_db, scripted(direction="augment",
                                              narrative=GOOD_NARRATIVE))
    substituting = run_graph(graph_db, scripted(direction="substitute",
                                                narrative=GOOD_NARRATIVE))

    a, b = augmenting.state.verdict, substituting.state.verdict
    assert a.augmentation_share != b.augmentation_share, \
        "sanity: the classification really did change"
    assert (a.lag.p10, a.lag.p50, a.lag.p90) == (b.lag.p10, b.lag.p50, b.lag.p90)
    assert a.lag.basis == b.lag.basis


def test_a_passing_gate_produces_a_narrative(graph_db):
    outcome = run_graph(graph_db, scripted(gate_outcome="pass",
                                           narrative=GOOD_NARRATIVE),
                        our_percentile=85.0)
    assert outcome.state.phase is Phase.SYNTHESISED
    assert outcome.produced_a_report
    assert outcome.state.narrative == GOOD_NARRATIVE


def test_a_rejected_gate_produces_no_report(graph_db):
    """The run terminates rather than narrating a result it does not trust."""
    provider = scripted(gate_outcome="gate_rejected", narrative=GOOD_NARRATIVE)
    outcome = run_graph(graph_db, provider, our_percentile=85.0)

    assert outcome.state.phase is Phase.GATE_REJECTED
    assert outcome.state.narrative is None
    assert not outcome.produced_a_report
    assert outcome.status == "gate_rejected"
    assert "synthesis" not in provider.stages


def test_a_review_required_gate_produces_no_report(graph_db):
    provider = scripted(gate_outcome="review_required", narrative=GOOD_NARRATIVE)
    outcome = run_graph(graph_db, provider)

    assert outcome.state.phase is Phase.REVIEW_REQUIRED
    assert outcome.state.narrative is None
    assert "synthesis" not in provider.stages


def test_a_rejected_run_still_persists_its_verdict_and_status(graph_db):
    """The evidence trail survives a rejection; only the report does not."""
    outcome = run_graph(graph_db, scripted(gate_outcome="gate_rejected"),
                        our_percentile=85.0)
    assert outcome.persisted
    assert outcome.status == "gate_rejected"

    from warehouse.session import Principal, connect
    with connect(Principal.DEVELOPER, database=graph_db) as conn:
        row = conn.cursor().execute(
            "SELECT status FROM score.run WHERE run_id = ?",
            outcome.context.run_id).fetchone()
    assert row[0] == "gate_rejected"


def test_an_out_of_scope_request_halts_before_any_evidence_is_read(graph_db):
    provider = ScriptedProvider({
        "scope_resolution": {"resolved": False, "soc_code": "",
                             "naics_sector": "", "geography": "US",
                             "rationale": "The request is about paralegals."}})
    outcome = run_graph(graph_db, provider)

    assert outcome.state.phase is Phase.OUT_OF_SCOPE
    assert outcome.state.evidence.tasks == []
    assert not outcome.persisted
    assert outcome.tracker.is_empty(), "nothing consumed, so nothing bound"
    assert provider.stages == ["intent_scope"]


def test_an_invented_soc_code_halts_the_run(graph_db):
    """A confident answer about a different occupation is the worst failure."""
    provider = ScriptedProvider({
        "scope_resolution": {"resolved": True, "soc_code": "23-1011.00",
                             "naics_sector": "52", "geography": "US",
                             "rationale": "Lawyers are close enough."}})
    outcome = run_graph(graph_db, provider)

    assert outcome.state.phase is Phase.OUT_OF_SCOPE
    assert "not published" in outcome.state.errors[-1]
    assert not outcome.persisted


def test_a_fabricated_figure_prevents_the_report(graph_db):
    """Two bad drafts produce no narrative, and the run says so."""
    provider = scripted(gate_outcome="pass",
                        narrative="Exposure is 0.9 but 73.2% will be automated by 2031.")
    outcome = run_graph(graph_db, provider, our_percentile=85.0)

    assert outcome.state.narrative is None
    assert outcome.state.phase is Phase.FAILED
    assert not outcome.produced_a_report
    assert any("73.2" in u for u in outcome.state.unresolved)


def test_nothing_is_persisted_when_no_verdict_was_produced(graph_db):
    """An empty row that looks like a result is worse than no row."""
    provider = ScriptedProvider({
        "scope_resolution": {"resolved": False, "soc_code": "",
                             "naics_sector": "", "geography": "US",
                             "rationale": "out of scope"}})
    outcome = run_graph(graph_db, provider)
    assert not outcome.persisted
    assert "nothing persisted" in outcome.notes[0]


def test_production_cannot_currently_reach_a_pass(graph_db):
    """A documented limitation, asserted so it cannot drift unnoticed.

    With no percentile of our own -- which is production, because one scored
    occupation has no rank -- calibration returns review_required, the gate
    cannot upgrade it, and no report is produced. Scoring several occupations
    is what unblocks this, not a change to the gate.
    """
    provider = scripted(gate_outcome="pass", narrative=GOOD_NARRATIVE)
    outcome = run_graph(graph_db, provider)          # our_percentile=None

    assert outcome.state.verdict.calibration.our_percentile is None
    assert outcome.state.phase is Phase.REVIEW_REQUIRED
    assert outcome.state.narrative is None
    assert "synthesis" not in provider.stages


# ===========================================================================
# The audit trail and the ledger
# ===========================================================================

def test_every_stage_appears_in_the_ledger(graph_db):
    outcome = run_graph(graph_db, scripted(narrative=GOOD_NARRATIVE),
                        our_percentile=85.0)
    stages = set(outcome.ledger.by_stage())
    assert {"intent_scope", "task_classifier", "review_gate", "synthesis"} <= stages


def test_the_ledger_records_tokens_but_withholds_unknown_cost(graph_db):
    outcome = run_graph(graph_db, scripted(narrative=GOOD_NARRATIVE))
    spend = outcome.ledger.summary()
    assert spend["total_tokens"] > 0
    assert spend["cost_usd"] is None
    assert "unpriced_models" in spend["cost_status"]


def test_the_run_binds_sources_across_multiple_usage_types(graph_db):
    outcome = run_graph(graph_db, scripted(narrative=GOOD_NARRATIVE))
    usages = set(outcome.tracker.as_dict())
    assert "task_source" in usages
    assert "adoption_evidence" in usages, "the lag path's evidence must bind too"


def test_the_summary_is_reportable(graph_db):
    outcome = run_graph(graph_db, scripted(narrative=GOOD_NARRATIVE),
                        our_percentile=85.0)
    summary = outcome.summary()
    assert summary["soc_code"] == SOC
    assert summary["curve_fitted"] is False
    assert summary["produced_a_report"] is True
    assert summary["bindings"] > 0


# ===========================================================================
# Graph hygiene
# ===========================================================================

def test_the_graph_compiles_without_credentials():
    """Building the topology must not require a provider or a database."""
    compiled = build.compile_graph(build._null_deps())
    assert compiled is not None


def test_the_state_schema_is_the_domain_object():
    """One state type, not a graph-shaped copy that can drift from it."""
    graph = build.build(build._null_deps())
    assert graph.schema is RunState


def test_persistence_can_be_skipped_for_a_dry_run(graph_db):
    outcome = run_graph(graph_db, scripted(narrative=GOOD_NARRATIVE),
                        persist=False)
    assert not outcome.persisted
    assert outcome.state.verdict is not None
    assert "Persistence skipped" in outcome.notes[0]
