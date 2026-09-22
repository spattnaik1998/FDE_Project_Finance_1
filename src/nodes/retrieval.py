"""Evidence Retrieval: gather everything through the tool surface.

Not a model node. It is a deterministic sequence of tool calls, which is why
the TDD lists its provider as "— (tool)". Retrieval precedes reasoning
throughout this design, so the classifier reasons over evidence it did not
generate and cannot extend.

Both paths are fed here, and separately: the classifier receives tasks and
claim evidence, the lag model receives adoption observations and historical
claims. Neither can reach the other's inputs.
"""

from __future__ import annotations

import logging

from nodes.state import Evidence, NodeDeps, Phase, RunState
from tools.evidence import ToolError

LOG = logging.getLogger("nodes.retrieval")

NODE = "2. Evidence Retrieval"

# Topics the lag path is grounded in. Kept here rather than in the lag model,
# which must not know how evidence is fetched.
LAG_TOPICS = ("lag_length", "j_curve_definition", "intangible_complement",
              "mismeasurement")

# Topics the classifier may cite when judging a task.
CLASSIFIER_TOPICS = ("not_prediction", "exposure_definition", "exposure_share",
                     "occupation_level")

ADJACENT_SOC = "13-2099.01"
BENCHMARK_MEASURE = "AIOE_language_modeling"


def _benchmark_soc(soc_code: str) -> str:
    """AIOE keys on the 6-digit SOC without O*NET's detail suffix."""
    return soc_code.split(".")[0]


def run(state: RunState, deps: NodeDeps) -> RunState:
    """Populate ``state.evidence`` from the six published tools."""
    if state.scope is None:
        return state.fail(Phase.FAILED, "Retrieval ran before scope was resolved.")

    scope = state.scope
    evidence = Evidence()
    tools = deps.tools

    try:
        tasks = tools.get_tasks(scope.soc_code)
        evidence.tasks = tasks.rows
        if tasks.note:
            evidence.notes.append(tasks.note)
    except ToolError as exc:
        # Refusing here rather than proceeding on an empty task list: an
        # exposure index over zero tasks is not a degraded answer, it is a
        # meaningless one.
        return state.fail(Phase.FAILED, f"Task retrieval failed: {exc}")

    benchmarks = tools.get_exposure_benchmarks(
        _benchmark_soc(scope.soc_code), measure=BENCHMARK_MEASURE)
    evidence.benchmarks = benchmarks.rows
    if benchmarks.note:
        evidence.notes.append(benchmarks.note)

    if scope.naics_sector:
        adoption = tools.get_adoption_curve(scope.naics_sector)
        evidence.adoption = adoption.rows
        if adoption.note:
            evidence.notes.append(adoption.note)
    else:
        state.unresolved.append(
            "No sector resolved, so no adoption evidence was retrieved and the "
            "lag interval will rest on the historical prior alone.")

    seen: set[str] = set()
    for topic in LAG_TOPICS + CLASSIFIER_TOPICS:
        result = tools.search_claims(topic=topic)
        for row in result.rows:
            if row["Claim_ID"] not in seen:
                seen.add(row["Claim_ID"])
                evidence.claims.append(row)
        if result.note and result.note not in evidence.notes:
            evidence.notes.append(result.note)

    # The adjacent occupation's importance ratings, for the sensitivity bound
    # only. Absent is fine: the bound is then simply not reported.
    try:
        adjacent = tools.get_tasks(ADJACENT_SOC)
        evidence.adjacent_tasks = adjacent.rows
    except ToolError:
        state.unresolved.append(
            f"Adjacent occupation {ADJACENT_SOC} is not published, so no "
            f"weighting sensitivity bound will be reported.")

    state.evidence = evidence
    state.phase = Phase.EVIDENCE_RETRIEVED

    deps.audit.tool_call(
        tool="evidence_retrieval_summary", node=NODE,
        payload={"tasks": len(evidence.tasks), "benchmarks": len(evidence.benchmarks),
                 "adoption": len(evidence.adoption), "claims": len(evidence.claims),
                 "adjacent_tasks": len(evidence.adjacent_tasks),
                 "notes": evidence.notes})

    LOG.info("node=retrieval status=ok run_id=%s tasks=%s adoption=%s claims=%s "
             "sources=%s", state.run_id, len(evidence.tasks),
             len(evidence.adoption), len(evidence.claims),
             deps.tracker.total_sources)
    return state


def claims_for_classifier(state: RunState, limit: int = 6) -> list[dict]:
    """The subset of claims a task classification may cite.

    Deliberately excludes the lag-grounding topics. A classifier citing the
    J-curve paper to justify a *task* judgment would be reaching for
    authority it has not earned, and would also blur the two paths.
    """
    return [c for c in state.evidence.claims
            if c.get("Topic") in CLASSIFIER_TOPICS][:limit]


def claims_for_lag(state: RunState) -> list[dict]:
    """The subset of claims that ground the historical lag prior."""
    return [c for c in state.evidence.claims if c.get("Topic") in LAG_TOPICS]
