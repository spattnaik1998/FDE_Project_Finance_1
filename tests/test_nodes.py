"""The four orchestration nodes, tested against fake providers.

Fakes rather than live calls, because what needs testing is the *behaviour
around* the model: the refusals, the validation, the degradation. A live call
proves the API works; it does not prove that an out-of-scope request halts, or
that an invented citation is dropped, or that a rejected gate produces no
report.

Each node is a plain function over ``RunState``, so each is exercised alone.
"""

from __future__ import annotations

import uuid

import pytest

import config

from nodes import classifier, figure_guard, intent, retrieval, review_gate, synthesis
from nodes.state import Evidence, GateDecision, NodeDeps, Phase, RunState, Scope
from providers.base import (
    ModelRefused,
    ModelResponse,
    ProviderError,
    SchemaViolation,
    Usage,
)
from providers.registry import Stage
from scoring.schemas import (
    CalibrationOutcome,
    CalibrationResult,
    Confidence,
    Direction,
    LagInterval,
    Modality,
    RoleVerdict,
    Routine,
    Tacitness,
    TaskClassification,
    TaskScore,
    WeightingBound,
)
from tools.audit_adapter import NullAuditAdapter
from tools.consumption import ConsumptionTracker, UsageType

SOC = "13-2051.00"
CLAIM = "eloundou_gpts_are_gpts:not_prediction:1:0"


# ===========================================================================
# Fakes
# ===========================================================================

class FakeProvider:
    """Returns queued structured answers, or raises queued exceptions."""

    name = "fake"
    model = "fake-model"

    def __init__(self, *answers):
        self.queue = list(answers)
        self.calls: list[dict] = []

    def _next(self):
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def _response(self, structured=None, text=None):
        return ModelResponse(provider=self.name, model=self.model, text=text,
                             structured=structured,
                             usage=Usage(input_tokens=10, output_tokens=5),
                             duration_ms=1)

    def structured(self, prompt, schema, *, schema_name, system=None,
                   max_tokens=2048, context=None):
        self.calls.append({"prompt": prompt, "schema_name": schema_name,
                           "system": system})
        return self._response(structured=self._next())

    def complete(self, prompt, *, system=None, max_tokens=1024, context=None):
        self.calls.append({"prompt": prompt, "system": system})
        return self._response(text=self._next())


def deps_with(provider, tracker=None, tools=None) -> NodeDeps:
    tracker = tracker or ConsumptionTracker(run_id="test-run")
    return NodeDeps(tools=tools, tracker=tracker, audit=NullAuditAdapter(),
                    provider_for=lambda stage: provider)


@pytest.fixture
def state():
    return RunState(run_id=str(uuid.uuid4()),
                    request="How exposed are our equity research associates?")


@pytest.fixture
def scoped_state(state):
    state.scope = Scope(soc_code=SOC, naics_sector="52",
                        occupation_title="Financial and Investment Analysts")
    state.phase = Phase.SCOPED
    return state


@pytest.fixture
def claims():
    return [{"Claim_ID": CLAIM, "Topic": "not_prediction", "Page": 1,
             "Publisher": "arXiv", "Is_Mirror": False,
             "Verified_Against_Publisher": False,
             "Quote": "We do not make predictions about the adoption timeline."}]


@pytest.fixture
def evidenced_state(scoped_state, claims):
    scoped_state.evidence = Evidence(
        tasks=[{"Task_ID": "t1", "SOC_Code": SOC,
                "Occupation": "Financial and Investment Analysts",
                "Statement": "Prepare plans of action for investment.",
                "Source_Doc_ID": "d1"},
               {"Task_ID": "t2", "SOC_Code": SOC,
                "Occupation": "Financial and Investment Analysts",
                "Statement": "Develop and maintain client relationships.",
                "Source_Doc_ID": "d1"}],
        claims=claims,
        adoption=[{"Period_Start": "2025-06-09", "Value": 29.9, "Source_Doc_ID": "d2"},
                  {"Period_Start": "2026-04-27", "Value": 36.5, "Source_Doc_ID": "d2"}],
        benchmarks=[{"SOC_Code": "13-2051", "Value": 1.2728, "Percentile": 86.82,
                     "Scale_Note": "A relative index.", "Source_Doc_ID": "d3"}])
    scoped_state.phase = Phase.EVIDENCE_RETRIEVED
    return scoped_state


def make_verdict(**over) -> RoleVerdict:
    fields = dict(
        soc_code=SOC, exposure_index=0.541,
        primary_weighting=WeightingBound(weight_source="equal", lower=0.541,
                                         upper=0.541, note="Equal weighting."),
        sensitivity_weighting=None,
        lag=LagInterval(p10=5.0, p50=10.07, p90=30.0,
                        basis="Observed 29.9% to 36.5%; no curve is fitted.",
                        observation_window_years=0.88),
        augmentation_share=0.5, unclear_share=0.5,
        calibration=CalibrationResult(
            benchmark_measure="AIOE_language_modeling",
            benchmark_percentile=86.82, our_percentile=None, delta=None,
            within_tolerance=False,
            outcome=CalibrationOutcome.REVIEW_REQUIRED,
            explanation="Not identifiable from one occupation."),
        caveats=["Adoption evidence is NAICS 52; the cost line is 523."])
    fields.update(over)
    return RoleVerdict(**fields)


def make_scores(n: int = 2) -> list[TaskScore]:
    return [TaskScore(task_id=f"t{i+1}", source_doc_id="d1", exposure_raw=0.90,
                      tacitness_penalty=0.0, exposure_adjusted=0.90,
                      direction=Direction.AUGMENT, confidence=Confidence.HIGH,
                      rationale="Stated rationale.")
            for i in range(n)]


# ===========================================================================
# Intent & Scope
# ===========================================================================

def test_intent_resolves_a_known_occupation(state, monkeypatch):
    monkeypatch.setattr(intent, "available_scopes", lambda db=None: (
        [{"soc_code": SOC, "title": "Financial and Investment Analysts", "tasks": 26}],
        [{"sector_code": "52", "label": "Finance and insurance"}]))

    provider = FakeProvider({"resolved": True, "soc_code": SOC,
                             "naics_sector": "52", "geography": "US",
                             "rationale": "Equity research associates map to 13-2051."})
    result = intent.run(state, deps_with(provider))

    assert result.phase is Phase.SCOPED
    assert result.scope.soc_code == SOC
    assert result.scope.occupation_title == "Financial and Investment Analysts"


def test_intent_halts_when_the_model_says_unresolved(state, monkeypatch):
    monkeypatch.setattr(intent, "available_scopes", lambda db=None: (
        [{"soc_code": SOC, "title": "Analysts", "tasks": 26}], []))

    provider = FakeProvider({"resolved": False, "soc_code": "", "naics_sector": "",
                             "geography": "US",
                             "rationale": "The request is about paralegals."})
    result = intent.run(state, deps_with(provider))

    assert result.phase is Phase.OUT_OF_SCOPE
    assert "paralegals" in result.errors[0]


def test_intent_refuses_a_soc_code_the_model_invented(state, monkeypatch):
    """The worst possible failure: a confident answer about a different role."""
    monkeypatch.setattr(intent, "available_scopes", lambda db=None: (
        [{"soc_code": SOC, "title": "Analysts", "tasks": 26}], []))

    provider = FakeProvider({"resolved": True, "soc_code": "23-1011.00",
                             "naics_sector": "", "geography": "US",
                             "rationale": "Lawyers are close enough."})
    result = intent.run(state, deps_with(provider))

    assert result.phase is Phase.OUT_OF_SCOPE
    assert "not published" in result.errors[0]
    assert "substituting" in result.errors[0]


def test_intent_notes_an_unavailable_sector_without_halting(state, monkeypatch):
    """A missing sector degrades the lag path; it does not invalidate the run."""
    monkeypatch.setattr(intent, "available_scopes", lambda db=None: (
        [{"soc_code": SOC, "title": "Analysts", "tasks": 26}],
        [{"sector_code": "52", "label": "Finance"}]))

    provider = FakeProvider({"resolved": True, "soc_code": SOC,
                             "naics_sector": "99", "geography": "US",
                             "rationale": "ok"})
    result = intent.run(state, deps_with(provider))

    assert result.phase is Phase.SCOPED
    assert any("no published adoption evidence" in u for u in result.unresolved)


def test_intent_fails_when_nothing_is_published(state, monkeypatch):
    monkeypatch.setattr(intent, "available_scopes", lambda db=None: ([], []))
    result = intent.run(state, deps_with(FakeProvider({})))
    assert result.phase is Phase.FAILED
    assert "warehouse is empty" in result.errors[0]


def test_intent_failure_is_not_silent(state, monkeypatch):
    monkeypatch.setattr(intent, "available_scopes", lambda db=None: (
        [{"soc_code": SOC, "title": "Analysts", "tasks": 26}], []))
    provider = FakeProvider(ProviderError("down", provider="fake"))
    result = intent.run(state, deps_with(provider))
    assert result.phase is Phase.FAILED


# ===========================================================================
# Task Classifier
# ===========================================================================

def valid_classification(**over) -> dict:
    answer = {"routine": "routine", "modality": "cognitive", "tacitness": "low",
              "direction": "augment", "confidence": "high",
              "rationale": "Rule-following drafting work.",
              "evidence_claim_ids": [CLAIM]}
    answer.update(over)
    return answer


def test_classifier_emits_a_valid_contract(evidenced_state):
    provider = FakeProvider(valid_classification())
    result = classifier.run(evidenced_state, deps_with(provider))

    assert result.phase is Phase.CLASSIFIED
    assert len(result.classifications) == 2
    first = result.classifications[0]
    assert first.routine is Routine.ROUTINE
    assert first.modality is Modality.COGNITIVE
    assert first.tacitness is Tacitness.LOW
    assert first.direction is Direction.AUGMENT


def test_classification_carries_no_numeric_field(evidenced_state):
    """If a score could be supplied there, a model could set it."""
    provider = FakeProvider(valid_classification())
    result = classifier.run(evidenced_state, deps_with(provider))
    dumped = result.classifications[0].model_dump()
    assert not any(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in dumped.values())


def test_an_invented_citation_is_dropped_and_recorded(evidenced_state):
    """A model reaching for a source it half-remembers."""
    provider = FakeProvider(valid_classification(
        evidence_claim_ids=[CLAIM, "smith:invented:9:0"]))
    result = classifier.run(evidenced_state, deps_with(provider))

    assert result.classifications[0].evidence_claim_ids == [CLAIM]
    assert any("not present in the retrieved evidence" in u
               for u in result.unresolved)


def test_unclear_is_carried_forward_not_re_prompted(evidenced_state):
    """Re-asking until the model commits would manufacture agreement."""
    provider = FakeProvider(valid_classification(direction="unclear",
                                                 confidence="low"))
    result = classifier.run(evidenced_state, deps_with(provider))

    assert all(c.direction is Direction.UNCLEAR for c in result.classifications)
    # One call per task, not one per task plus retries.
    assert len(provider.calls) == len(evidenced_state.evidence.tasks)


def test_a_schema_violation_degrades_one_task_not_the_run(evidenced_state):
    provider = FakeProvider(SchemaViolation("bad json", provider="fake"))
    result = classifier.run(evidenced_state, deps_with(provider))

    assert result.phase is Phase.CLASSIFIED
    assert len(result.classifications) == 2
    assert all(c.confidence is Confidence.LOW for c in result.classifications)
    assert all(c.direction is Direction.UNCLEAR for c in result.classifications)


def test_the_degraded_fallback_does_not_inflate_exposure(evidenced_state):
    """Misreading judgment work as routine is the error direction that matters."""
    provider = FakeProvider(SchemaViolation("bad", provider="fake"))
    result = classifier.run(evidenced_state, deps_with(provider))
    assert all(c.routine is Routine.NON_ROUTINE for c in result.classifications)


def test_a_refusal_degrades_rather_than_failing(evidenced_state):
    provider = FakeProvider(ModelRefused("declined", provider="fake"))
    result = classifier.run(evidenced_state, deps_with(provider))
    assert result.phase is Phase.CLASSIFIED
    assert result.unresolved


def test_an_out_of_vocabulary_category_is_a_contract_violation(evidenced_state):
    provider = FakeProvider(valid_classification(direction="replaced"))
    result = classifier.run(evidenced_state, deps_with(provider))
    assert result.classifications[0].direction is Direction.UNCLEAR
    assert any("contract violation" in u for u in result.unresolved)


def test_classifier_refuses_to_run_with_no_tasks(scoped_state):
    result = classifier.run(scoped_state, deps_with(FakeProvider({})))
    assert result.phase is Phase.FAILED
    assert "no tasks" in result.errors[0]


def test_classifier_is_given_only_classifier_topic_claims(evidenced_state):
    """A classifier citing the J-curve paper for a task judgment would be
    reaching for authority it has not earned, and would blur the two paths."""
    evidenced_state.evidence.claims.append(
        {"Claim_ID": "jcurve:lag_length:6:0", "Topic": "lag_length", "Page": 6,
         "Publisher": "NBER", "Quote": "The implementation lag runs to years."})
    provider = FakeProvider(valid_classification())
    classifier.run(evidenced_state, deps_with(provider))

    prompt = provider.calls[0]["prompt"]
    assert CLAIM in prompt
    assert "jcurve:lag_length:6:0" not in prompt


# ===========================================================================
# Review Gate
# ===========================================================================

def gate_answer(**over) -> dict:
    answer = {"outcome": "pass", "checks_passed": ["caveats_non_empty"],
              "checks_failed": [], "reasoning": "All checks hold."}
    answer.update(over)
    return answer


@pytest.fixture
def gate_ready(evidenced_state):
    evidenced_state.verdict = make_verdict(
        calibration=CalibrationResult(
            benchmark_measure="m", benchmark_percentile=87.0, our_percentile=85.0,
            delta=-2.0, within_tolerance=True, outcome=CalibrationOutcome.PASS))
    evidenced_state.scores = make_scores(2)
    return evidenced_state


def _deps_with_sources(provider):
    tracker = ConsumptionTracker(run_id="test-run")
    tracker.record(UsageType.TASK_SOURCE, ["d1"])
    return deps_with(provider, tracker=tracker)


def test_gate_passes_a_sound_run(gate_ready):
    result = review_gate.run(gate_ready, _deps_with_sources(FakeProvider(gate_answer())))
    assert result.gate.outcome == "pass"
    assert result.gate.allows_report
    assert result.phase is Phase.REVIEWED


def test_gate_rejects_on_a_structural_failure_without_asking_the_model(gate_ready):
    """A missing verdict is not a judgment call."""
    gate_ready.verdict = None
    provider = FakeProvider(gate_answer())
    result = review_gate.run(gate_ready, _deps_with_sources(provider))

    assert result.phase is Phase.GATE_REJECTED
    assert "verdict_present" in result.gate.checks_failed
    assert provider.calls == [], "the model must not be consulted on a hard failure"


def test_gate_rejects_when_no_sources_were_bound(gate_ready):
    provider = FakeProvider(gate_answer())
    result = review_gate.run(gate_ready, deps_with(provider))
    assert result.phase is Phase.GATE_REJECTED
    assert "sources_bound" in result.gate.checks_failed


def test_gate_rejects_when_not_every_task_was_scored(gate_ready):
    gate_ready.scores = make_scores(1)
    result = review_gate.run(gate_ready, _deps_with_sources(FakeProvider(gate_answer())))
    assert "every_task_scored" in result.gate.checks_failed


def test_gate_cannot_upgrade_a_rejected_calibration(gate_ready):
    """The arithmetic is authoritative; the gate may only be at least as strict."""
    gate_ready.verdict = make_verdict(calibration=CalibrationResult(
        benchmark_measure="m", benchmark_percentile=87.0, our_percentile=20.0,
        delta=-67.0, within_tolerance=False,
        outcome=CalibrationOutcome.GATE_REJECTED))
    result = review_gate.run(gate_ready,
                             _deps_with_sources(FakeProvider(gate_answer())))
    assert result.gate.outcome == "gate_rejected"
    assert "calibration_gate_rejected" in result.gate.checks_failed


def test_gate_cannot_pass_a_review_required_calibration(gate_ready):
    result = review_gate.run(
        gate_ready, _deps_with_sources(FakeProvider(gate_answer())))
    # gate_ready's fixture calibration passes, so override it here.
    gate_ready.verdict = make_verdict()   # review_required
    result = review_gate.run(
        gate_ready, _deps_with_sources(FakeProvider(gate_answer())))
    assert result.gate.outcome == "review_required"
    assert result.phase is Phase.REVIEW_REQUIRED


def test_gate_may_be_stricter_than_the_arithmetic(gate_ready):
    """It can reject a run the calibration passed."""
    result = review_gate.run(gate_ready, _deps_with_sources(
        FakeProvider(gate_answer(outcome="gate_rejected",
                                 checks_failed=["evidence_too_thin"]))))
    assert result.gate.outcome == "gate_rejected"
    assert result.phase is Phase.GATE_REJECTED


def test_an_unavailable_gate_does_not_wave_the_run_through(gate_ready):
    provider = FakeProvider(ProviderError("down", provider="fake"))
    result = review_gate.run(gate_ready, _deps_with_sources(provider))
    assert result.phase is Phase.GATE_REJECTED
    assert "review_gate_unavailable" in result.gate.checks_failed


def test_unverified_mirrors_block_only_a_deliverable_run(gate_ready):
    gate_ready.evidence.claims[0]["Is_Mirror"] = True
    gate_ready.evidence.claims[0]["Verified_Against_Publisher"] = False

    internal = review_gate.structural_checks(gate_ready, deliverable=False,
                                             tracker_sources=1)
    deliverable = review_gate.structural_checks(gate_ready, deliverable=True,
                                                tracker_sources=1)

    assert next(c for c in internal if c.name == "mirror_policy").passed
    assert not next(c for c in deliverable if c.name == "mirror_policy").passed


def test_an_economy_profile_run_cannot_be_marked_customer_deliverable(
        gate_ready, monkeypatch):
    """A rehearsal must not be shippable, and it is the gate that says so.

    The economy profile exists to make development and demos cheap. Its runs are
    still real runs and persist like any other, so the only thing standing
    between "we tested this on the cheap model" and "we gave the client a figure
    from the cheap model" is this check. Same shape as the mirror policy:
    blocking on a deliverable run, informative on an internal one, so nobody's
    development loop is obstructed by it.
    """
    monkeypatch.setattr(config, "MODEL_PROFILE", "economy")
    monkeypatch.setattr(config, "MODEL_CLASSIFIER", "gpt-5.4-mini")

    internal = review_gate.structural_checks(gate_ready, deliverable=False,
                                             tracker_sources=1)
    deliverable = review_gate.structural_checks(gate_ready, deliverable=True,
                                                tracker_sources=1)

    assert next(c for c in internal if c.name == "model_profile").passed
    blocked = next(c for c in deliverable if c.name == "model_profile")
    assert not blocked.passed
    # The detail must name the model, so a rejected run says which one it ran.
    assert "gpt-5.4-mini" in blocked.detail


def test_the_full_profile_passes_the_same_check(gate_ready, monkeypatch):
    """Guards against the previous test passing because the check always fails."""
    monkeypatch.setattr(config, "MODEL_PROFILE", "full")
    monkeypatch.setattr(config, "MODEL_CLASSIFIER", "gpt-6-astra")
    checks = review_gate.structural_checks(gate_ready, deliverable=True,
                                           tracker_sources=1)
    assert next(c for c in checks if c.name == "model_profile").passed


def test_a_fitted_curve_would_fail_the_structural_check(gate_ready):
    gate_ready.verdict = make_verdict(
        lag=LagInterval(p10=5.0, p50=10.0, p90=30.0, basis="b",
                        observation_window_years=0.88, curve_fitted=True))
    checks = review_gate.structural_checks(gate_ready, tracker_sources=1)
    assert not next(c for c in checks if c.name == "no_curve_fitted").passed


# ===========================================================================
# Synthesis
# ===========================================================================

GOOD_NARRATIVE = (
    "The exposure index for this occupation is 0.541 under equal weighting. "
    "The adoption lag runs from 5.0 to 30.0 years with a median of 10.07. "
    "Exposure and timing are separate findings. As the authors state "
    f"[{CLAIM}], no adoption timeline is forecast. "
    "Adoption evidence is NAICS 52 while the cost line is 523.")

BAD_NARRATIVE = (
    "Exposure is 0.541, and we expect 73.2% of this work to be automated by 2031.")


@pytest.fixture
def synthesis_ready(gate_ready):
    gate_ready.gate = GateDecision(outcome="pass", reasoning="ok")
    gate_ready.phase = Phase.REVIEWED
    return gate_ready


def test_synthesis_accepts_a_sourced_narrative(synthesis_ready):
    provider = FakeProvider(GOOD_NARRATIVE)
    result = synthesis.run(synthesis_ready, deps_with(provider))
    assert result.phase is Phase.SYNTHESISED
    assert result.narrative == GOOD_NARRATIVE
    assert len(provider.calls) == 1


def test_synthesis_rejects_an_invented_figure_and_retries_once(synthesis_ready):
    provider = FakeProvider(BAD_NARRATIVE, GOOD_NARRATIVE)
    result = synthesis.run(synthesis_ready, deps_with(provider))

    assert result.phase is Phase.SYNTHESISED
    assert result.narrative == GOOD_NARRATIVE
    assert len(provider.calls) == 2
    assert "REJECTED" in provider.calls[1]["prompt"]
    assert "73.2" in provider.calls[1]["prompt"], \
        "the retry must name the offending figure"


def test_two_bad_drafts_produce_no_narrative_at_all(synthesis_ready):
    """A fluent report with one invented number is worse than no report."""
    provider = FakeProvider(BAD_NARRATIVE)
    result = synthesis.run(synthesis_ready, deps_with(provider))

    assert result.phase is Phase.FAILED
    assert result.narrative is None
    assert "invented" in result.errors[-1] or "does not support" in result.errors[-1]
    assert len(provider.calls) == synthesis.MAX_ATTEMPTS


def test_synthesis_rejects_an_invented_citation(synthesis_ready):
    bad = ("Exposure is 0.541 over 5.0 to 30.0 years. "
           "See [fabricated:source:3:0] for the argument.")
    provider = FakeProvider(bad)
    result = synthesis.run(synthesis_ready, deps_with(provider))
    assert result.phase is Phase.FAILED
    assert "citation" in result.unresolved[-1].lower()


def test_synthesis_is_skipped_when_the_gate_did_not_pass(synthesis_ready):
    synthesis_ready.gate = GateDecision(outcome="gate_rejected", reasoning="no")
    synthesis_ready.phase = Phase.GATE_REJECTED
    provider = FakeProvider(GOOD_NARRATIVE)

    result = synthesis.run(synthesis_ready, deps_with(provider))
    assert result.narrative is None
    assert result.phase is Phase.GATE_REJECTED
    assert provider.calls == [], "no model call on a gated run"


def test_synthesis_needs_a_verdict(scoped_state):
    scoped_state.gate = GateDecision(outcome="pass")
    result = synthesis.run(scoped_state, deps_with(FakeProvider("text")))
    assert result.phase is Phase.FAILED


def test_the_validator_is_usable_on_its_own(synthesis_ready):
    ok, problem = synthesis.validate(GOOD_NARRATIVE, synthesis_ready)
    assert ok and problem == ""
    ok, problem = synthesis.validate(BAD_NARRATIVE, synthesis_ready)
    assert not ok and "73.2" in problem


def test_the_prompt_carries_the_caveats(synthesis_ready):
    provider = FakeProvider(GOOD_NARRATIVE)
    synthesis.run(synthesis_ready, deps_with(provider))
    assert "NAICS 52" in provider.calls[0]["prompt"]


# ===========================================================================
# State machine integrity
# ===========================================================================

@pytest.mark.parametrize("phase,terminal", [
    (Phase.CREATED, False), (Phase.SCOPED, False), (Phase.CLASSIFIED, False),
    (Phase.OUT_OF_SCOPE, True), (Phase.GATE_REJECTED, True),
    (Phase.REVIEW_REQUIRED, True), (Phase.FAILED, True),
    (Phase.SYNTHESISED, True)])
def test_terminal_phases_are_declared(phase, terminal):
    assert phase.is_terminal is terminal


@pytest.mark.parametrize("phase", [Phase.OUT_OF_SCOPE, Phase.GATE_REJECTED,
                                   Phase.REVIEW_REQUIRED, Phase.FAILED])
def test_only_synthesis_produces_a_report(phase):
    assert not phase.produced_a_report
    assert Phase.SYNTHESISED.produced_a_report


def test_state_carries_no_credential(state):
    """A credential in the state object would travel through every node."""
    dumped = repr(state).lower()
    for marker in ("sk-", "password", "api_key"):
        assert marker not in dumped


def test_node_deps_exposes_no_database_connection():
    """A node reaches data only through tools."""
    fields = set(NodeDeps.__dataclass_fields__)
    assert not {f for f in fields if "conn" in f or "cursor" in f or "session" in f}
