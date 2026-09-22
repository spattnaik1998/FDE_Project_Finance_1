"""The orchestration state object and the dependencies nodes are handed.

Nodes are plain functions over this state rather than methods on a graph, so
each is testable on its own and the graph in W6 is assembly rather than logic.

Two things the state deliberately does **not** carry: credentials, and any
partially-computed score. Credentials live behind the provider registry and the
session layer; scores come from the deterministic service in one step, so there
is no intermediate value a node could nudge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from providers.accounting import Ledger
from scoring.schemas import (
    LagInterval,
    RoleVerdict,
    TaskClassification,
    TaskScore,
    WeightingBound,
)
from tools.audit_adapter import AuditAdapter
from tools.consumption import ConsumptionTracker
from tools.evidence import EvidenceTools


class Phase(str, Enum):
    """Where a run got to. Terminal phases are explicit."""

    CREATED = "created"
    SCOPED = "scoped"
    EVIDENCE_RETRIEVED = "evidence_retrieved"
    CLASSIFIED = "classified"
    SCORED = "scored"
    REVIEWED = "reviewed"
    SYNTHESISED = "synthesised"
    # Terminal failures, each distinguishable from the others.
    OUT_OF_SCOPE = "out_of_scope"
    GATE_REJECTED = "gate_rejected"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {Phase.OUT_OF_SCOPE, Phase.GATE_REJECTED,
                        Phase.REVIEW_REQUIRED, Phase.FAILED,
                        Phase.SYNTHESISED}

    @property
    def produced_a_report(self) -> bool:
        return self is Phase.SYNTHESISED


@dataclass
class Scope:
    """What the run resolved the request to. Never guessed."""

    soc_code: str
    naics_sector: str
    geography: str = "US"
    occupation_title: str = ""
    rationale: str = ""


@dataclass
class Evidence:
    """Everything retrieved through the tool surface, as returned."""

    tasks: list[dict] = field(default_factory=list)
    benchmarks: list[dict] = field(default_factory=list)
    adoption: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    adjacent_tasks: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def claim_ids(self) -> set[str]:
        """The only claim ids anything downstream may cite."""
        return {c["Claim_ID"] for c in self.claims if c.get("Claim_ID")}


@dataclass
class GateDecision:
    """What the Review Gate concluded, and on what grounds."""

    outcome: str                      # pass | review_required | gate_rejected
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)
    reasoning: str = ""

    @property
    def allows_report(self) -> bool:
        return self.outcome == "pass"


@dataclass
class RunState:
    """Everything a run accumulates. Passed between nodes, never global."""

    run_id: str
    request: str
    phase: Phase = Phase.CREATED

    scope: Scope | None = None
    evidence: Evidence = field(default_factory=Evidence)
    classifications: list[TaskClassification] = field(default_factory=list)

    # The two scoring paths write to SEPARATE fields, which is what lets the
    # graph fan out in parallel and what makes the independence checkable in
    # the topology rather than only in the module imports. Nothing on the
    # exposure side ever writes `lag`, and nothing on the lag side ever writes
    # `scores` or either weighting bound.
    scores: list[TaskScore] = field(default_factory=list)
    primary_weighting: WeightingBound | None = None
    sensitivity_weighting: WeightingBound | None = None
    lag: LagInterval | None = None
    # Owned by the lag branch alone. It cannot append to `unresolved` because
    # the classifier branch runs concurrently and would contend for that key;
    # assembly folds these in afterwards.
    lag_notes: list[str] = field(default_factory=list)

    verdict: RoleVerdict | None = None
    gate: GateDecision | None = None
    narrative: str | None = None

    errors: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def fail(self, phase: Phase, reason: str) -> "RunState":
        """Move to a terminal phase with the reason recorded."""
        self.phase = phase
        self.errors.append(reason)
        return self

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "phase": self.phase.value,
            "produced_a_report": self.phase.produced_a_report,
            "soc_code": self.scope.soc_code if self.scope else None,
            "tasks": len(self.evidence.tasks),
            "classifications": len(self.classifications),
            "exposure_index": self.verdict.exposure_index if self.verdict else None,
            "gate": self.gate.outcome if self.gate else None,
            "errors": list(self.errors),
            "unresolved": list(self.unresolved),
        }


@dataclass
class NodeDeps:
    """What a node is allowed to reach.

    Handed in rather than imported, so a test can substitute a fake provider or
    a null audit adapter without patching module globals. Note what is absent:
    no database connection and no credential. A node reaches data only through
    ``tools`` and models only through the registry.
    """

    tools: EvidenceTools
    tracker: ConsumptionTracker
    audit: AuditAdapter
    ledger: Ledger = field(default_factory=Ledger)
    provider_for: Any = None          # Callable[[Stage], ModelProvider]
    prompt_version: str = "v1"

    # Our own percentile within a distribution of our scores. None in
    # production and by default: a percentile is a rank, and a
    # single-occupation run has no rank. Injectable only so the pass path --
    # which production therefore cannot currently reach -- stays testable.
    our_percentile: float | None = None

    def provider(self, stage):
        """Resolve the provider for a stage, defaulting to the real registry."""
        if self.provider_for is not None:
            return self.provider_for(stage)
        from providers.registry import for_stage
        return for_stage(stage)
