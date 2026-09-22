"""LangGraph assembly: a fixed node set, not an open ReAct loop.

The graph is the architecture's central claim made structural. Two properties
are visible in the topology itself rather than asserted in prose:

* **The twin paths.** ``exposure_path`` and ``lag_path`` are parallel branches
  out of ``retrieve``, meeting only at ``assemble_verdict``. There is no edge
  between them and ``tests/test_graph.py`` fails if one appears.

  The exposure branch runs classification and scoring inside a single node.
  That is a concession to LangGraph 0.3.34: with branches of *unequal* length
  the join node fires once per incoming edge rather than waiting, which was
  observed directly (a two-hop and a one-hop branch ran the join twice) and
  produced a write race on ``phase``. ``add_node(defer=True)`` would fix it but
  is not available in this version. Equal-length branches make the fan-in fire
  once, and the resulting shape matches the architecture diagram's 3B/3C pair
  more closely than the split did. The classifier remains its own module and
  its own tested function; it is simply not its own graph node.
* **Termination.** ``gate_rejected`` and ``review_required`` route to ``END``
  without reaching synthesis, so a gated run cannot produce a report.

The node set is fixed and the routing is conditional on ``phase``, never on a
model deciding what to do next. A model choosing the next step is how a run
becomes unreproducible, and the output here is a number a customer budgets
against.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from nodes import classifier, intent, retrieval, review_gate, scoring_nodes, synthesis
from nodes.state import NodeDeps, Phase, RunState

LOG = logging.getLogger("graph")

GRAPH_VERSION = "graph_v1_fixed_nodes"

# Node names, in one place so the topology test and the builder cannot drift.
INTENT = "intent_scope"
RETRIEVE = "evidence_retrieval"
EXPOSURE_PATH = "exposure_path"      # classify, then score. One superstep.
LAG_PATH = "lag_path"
ASSEMBLE = "assemble_verdict"
GATE = "review_gate"
SYNTHESISE = "synthesis"

NODE_NAMES = (INTENT, RETRIEVE, EXPOSURE_PATH, LAG_PATH, ASSEMBLE, GATE,
              SYNTHESISE)

# Named so the independence assertion reads in terms of the design rather than
# string literals.
EXPOSURE_CHAIN = (EXPOSURE_PATH,)
LAG_CHAIN = (LAG_PATH,)


# Which state fields each node is allowed to write. Declared rather than
# implied, because LangGraph treats a returned whole-state object as an update
# to EVERY field -- which silently made the classifier write `lag=None`
# concurrently with the lag branch writing the real value. Two nodes in the
# same superstep contending for one key is an error LangGraph raises, and this
# mapping is what prevents it. It also documents ownership: no field is written
# by two paths.
NODE_WRITES: dict[str, tuple[str, ...]] = {
    INTENT: ("scope", "phase", "errors", "unresolved"),
    RETRIEVE: ("evidence", "phase", "errors", "unresolved"),
    EXPOSURE_PATH: ("classifications", "scores", "primary_weighting",
                    "sensitivity_weighting", "phase", "errors", "unresolved"),
    LAG_PATH: ("lag", "lag_notes"),
    ASSEMBLE: ("verdict", "phase", "errors", "unresolved"),
    GATE: ("gate", "phase"),
    SYNTHESISE: ("narrative", "phase", "errors", "unresolved"),
}


def _wrap(name: str, fn: Callable[..., RunState], deps: NodeDeps,
          **kwargs) -> Callable:
    """Adapt a ``(state, deps) -> state`` node to LangGraph's ``(state) -> dict``.

    Returns only the fields this node owns, per :data:`NODE_WRITES`.
    """
    writes = NODE_WRITES[name]

    @functools.wraps(fn)
    def node(state: RunState) -> dict[str, Any]:
        result = fn(state, deps, **kwargs)
        return {field: getattr(result, field) for field in writes}
    return node


def concurrent_write_conflicts() -> set[str]:
    """Fields written by BOTH parallel branches.

    Must be empty. The branches run in the same superstep, so a shared field
    would be a race LangGraph refuses -- and, worse, would couple the two paths
    through the state object even though neither module imports the other.
    """
    return set(NODE_WRITES[EXPOSURE_PATH]) & set(NODE_WRITES[LAG_PATH])


def _exposure_path(deps: NodeDeps) -> Callable:
    """Classify, then score. One graph node, two tested functions.

    Merged so the fan-in is symmetric; see the module docstring. A failure in
    classification short-circuits scoring, which would otherwise run on an
    empty classification list.
    """
    writes = NODE_WRITES[EXPOSURE_PATH]

    def node(state: RunState) -> dict[str, Any]:
        classified = classifier.run(state, deps)
        if classified.phase is Phase.CLASSIFIED:
            classified = scoring_nodes.score_exposure(classified, deps)
        return {field: getattr(classified, field) for field in writes}
    return node


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_after_intent(state: RunState) -> str:
    """Continue only if a scope was resolved. Out of scope halts."""
    if state.phase is Phase.SCOPED:
        return RETRIEVE
    return END


def route_after_retrieval(state: RunState) -> list[str]:
    """Fan out to both scoring paths, or halt.

    Returning both branch names is what creates the parallelism, and therefore
    what makes the absence of an edge between them meaningful.
    """
    if state.phase is Phase.EVIDENCE_RETRIEVED:
        return [EXPOSURE_PATH, LAG_PATH]
    return [END]


def route_after_gate(state: RunState) -> str:
    """Only a clean pass reaches synthesis."""
    if state.gate is not None and state.gate.allows_report:
        return SYNTHESISE
    return END


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def build(deps: NodeDeps, *, deliverable: bool = False,
          database: str | None = None) -> StateGraph:
    """Build the uncompiled graph, so tests can inspect its topology."""
    graph = StateGraph(RunState)

    graph.add_node(INTENT, _wrap(INTENT, intent.run, deps, database=database))
    graph.add_node(RETRIEVE, _wrap(RETRIEVE, retrieval.run, deps))
    graph.add_node(EXPOSURE_PATH, _exposure_path(deps))
    graph.add_node(LAG_PATH, _wrap(LAG_PATH, scoring_nodes.score_lag, deps))
    graph.add_node(ASSEMBLE,
                   _wrap(ASSEMBLE, scoring_nodes.assemble_verdict, deps))
    graph.add_node(GATE, _wrap(GATE, review_gate.run, deps,
                               deliverable=deliverable))
    graph.add_node(SYNTHESISE, _wrap(SYNTHESISE, synthesis.run, deps))

    graph.add_edge(START, INTENT)
    graph.add_conditional_edges(INTENT, route_after_intent, [RETRIEVE, END])

    # The fan-out. Both scoring paths start here, and neither depends on the
    # other having run.
    graph.add_conditional_edges(RETRIEVE, route_after_retrieval,
                                [EXPOSURE_PATH, LAG_PATH, END])

    # The fan-in. Both branches are one hop, so assembly fires exactly once.
    graph.add_edge(EXPOSURE_PATH, ASSEMBLE)
    graph.add_edge(LAG_PATH, ASSEMBLE)

    graph.add_edge(ASSEMBLE, GATE)
    graph.add_conditional_edges(GATE, route_after_gate, [SYNTHESISE, END])
    graph.add_edge(SYNTHESISE, END)

    return graph


def compile_graph(deps: NodeDeps, *, deliverable: bool = False,
                  database: str | None = None):
    """Build and compile. The compiled graph is what a run invokes."""
    compiled = build(deps, deliverable=deliverable, database=database).compile()
    LOG.info("graph=%s status=compiled nodes=%s", GRAPH_VERSION, len(NODE_NAMES))
    return compiled


# ---------------------------------------------------------------------------
# Topology introspection -- so the independence claim is checkable
# ---------------------------------------------------------------------------

def edges(deps: NodeDeps | None = None) -> set[tuple[str, str]]:
    """Every edge in the graph, conditional branches included.

    Read from the compiled graph rather than reconstructed by hand, so the
    assertion is about what was actually built.
    """
    deps = deps or _null_deps()
    compiled = build(deps).compile()
    drawable = compiled.get_graph()
    return {(e.source, e.target) for e in drawable.edges}


def successors(node: str, deps: NodeDeps | None = None) -> set[str]:
    return {target for source, target in edges(deps) if source == node}


def predecessors(node: str, deps: NodeDeps | None = None) -> set[str]:
    return {source for source, target in edges(deps) if target == node}


def reaches(start: str, goal: str, deps: NodeDeps | None = None) -> bool:
    """Whether ``goal`` is reachable from ``start`` by following edges."""
    all_edges = edges(deps)
    seen, frontier = {start}, [start]
    while frontier:
        current = frontier.pop()
        for source, target in all_edges:
            if source == current and target not in seen:
                if target == goal:
                    return True
                seen.add(target)
                frontier.append(target)
    return False


def _null_deps() -> NodeDeps:
    """Dependencies sufficient to build the graph but not to run it."""
    from providers.accounting import Ledger
    from tools.audit_adapter import NullAuditAdapter
    from tools.consumption import ConsumptionTracker
    return NodeDeps(tools=None, tracker=ConsumptionTracker(),
                    audit=NullAuditAdapter(), ledger=Ledger(),
                    provider_for=lambda stage: None)
