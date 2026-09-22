"""Task Classifier: categorical judgments, one task at a time.

Runs on OpenAI. Emits a :class:`TaskClassification`, which has **no numeric
field** — if a score could be supplied there, a model could set it, and the
whole "agents judge categories, Python computes numbers" commitment would be
decorative.

Three behaviours worth naming:

* **Low confidence is carried forward, not re-prompted away.** A task the model
  cannot resolve stays ``unclear``. Re-asking until it commits would manufacture
  agreement, and ``unclear`` is a legitimate answer the verdict reports as a
  share.
* **Citations are validated against what retrieval returned.** A claim ID the
  model invented is dropped and recorded, not passed through.
* **A schema violation on one task does not fail the run.** It is recorded and
  the task is marked unclear at low confidence, because losing one task's
  judgment is a smaller error than losing the analysis.
"""

from __future__ import annotations

import logging

from nodes import prompts, retrieval
from nodes.state import NodeDeps, Phase, RunState
from providers.base import CallContext, ModelRefused, ProviderError, SchemaViolation
from providers.registry import Stage
from scoring.schemas import (
    Confidence,
    Direction,
    Modality,
    Routine,
    Tacitness,
    TaskClassification,
)

LOG = logging.getLogger("nodes.classifier")

NODE = "3A. Task Classifier"

# Enough for the model to reason and answer. Established the hard way: a
# reasoning model handed too small a budget spends it all thinking and returns
# nothing at all.
MAX_TOKENS = 2000


def _format_evidence(claims: list[dict]) -> str:
    if not claims:
        return "  (no claim evidence retrieved; cite nothing)"
    return "\n".join(
        f"  [{c['Claim_ID']}] p.{c['Page']} — \"{c['Quote'][:220]}\""
        for c in claims)


def _fallback(task_id: str, reason: str) -> TaskClassification:
    """What to record when a task cannot be classified.

    Non-routine, cognitive, medium tacitness, unclear, low confidence. Chosen
    so the failure does not inflate exposure: misreading judgment work as
    routine is the error direction that matters here.
    """
    return TaskClassification(
        task_id=task_id, routine=Routine.NON_ROUTINE, modality=Modality.COGNITIVE,
        tacitness=Tacitness.MEDIUM, direction=Direction.UNCLEAR,
        confidence=Confidence.LOW,
        rationale=f"Classification unavailable ({reason}); recorded as unclear at "
                  f"low confidence rather than guessed.",
        evidence_claim_ids=[])


def classify_one(task: dict, state: RunState, deps: NodeDeps,
                 claims: list[dict]) -> TaskClassification:
    """Classify a single task. Never raises; records and degrades instead."""
    task_id = str(task["Task_ID"])
    provider = deps.provider(Stage.TASK_CLASSIFIER)

    try:
        response = provider.structured(
            prompts.CLASSIFIER_USER.format(
                occupation=task.get("Occupation", ""),
                soc_code=task.get("SOC_Code", ""),
                statement=task["Statement"],
                evidence=_format_evidence(claims)),
            prompts.CLASSIFIER_SCHEMA,
            schema_name="task_classification",
            system=prompts.CLASSIFIER_SYSTEM,
            max_tokens=MAX_TOKENS,
            context=CallContext(run_id=state.run_id,
                                stage=Stage.TASK_CLASSIFIER.value,
                                prompt_version=deps.prompt_version))
    except (SchemaViolation, ModelRefused) as exc:
        LOG.warning("node=classifier status=degraded task=%s error=%s",
                    task_id, str(exc)[:160])
        state.unresolved.append(f"Task {task_id}: {str(exc)[:160]}")
        return _fallback(task_id, type(exc).__name__)
    except ProviderError as exc:
        LOG.error("node=classifier status=provider_error task=%s error=%s",
                  task_id, str(exc)[:160])
        state.unresolved.append(f"Task {task_id}: provider error")
        return _fallback(task_id, "provider error")

    deps.ledger.record(response, stage=Stage.TASK_CLASSIFIER.value,
                       prompt_version=deps.prompt_version)
    deps.audit.model_call(node=NODE, provider=response.provider,
                          model=response.model,
                          prompt_version=deps.prompt_version,
                          decision=response.structured,
                          input_tokens=response.usage.input_tokens,
                          output_tokens=response.usage.output_tokens,
                          duration_ms=response.duration_ms)

    answer = response.structured or {}

    # Only citations retrieval actually returned survive. A model reaching for
    # a source it half-remembers is the failure mode the whole provenance chain
    # exists to prevent, so an invented id is dropped and recorded.
    allowed = state.evidence.claim_ids
    cited = [c for c in answer.get("evidence_claim_ids", []) if c in allowed]
    invented = [c for c in answer.get("evidence_claim_ids", []) if c not in allowed]
    if invented:
        LOG.error("node=classifier status=invented_citation task=%s ids=%s",
                  task_id, invented)
        state.unresolved.append(
            f"Task {task_id}: dropped {len(invented)} citation(s) not present in "
            f"the retrieved evidence: {', '.join(invented[:3])}")

    try:
        return TaskClassification(
            task_id=task_id,
            routine=Routine(answer["routine"]),
            modality=Modality(answer["modality"]),
            tacitness=Tacitness(answer["tacitness"]),
            direction=Direction(answer["direction"]),
            confidence=Confidence(answer["confidence"]),
            rationale=answer.get("rationale") or "No rationale supplied.",
            evidence_claim_ids=cited)
    except (KeyError, ValueError) as exc:
        LOG.warning("node=classifier status=contract_violation task=%s error=%s",
                    task_id, exc)
        state.unresolved.append(f"Task {task_id}: contract violation ({exc})")
        return _fallback(task_id, "contract violation")


def run(state: RunState, deps: NodeDeps) -> RunState:
    """Classify every retrieved task."""
    if not state.evidence.tasks:
        return state.fail(Phase.FAILED, "Classifier ran with no tasks retrieved.")

    claims = retrieval.claims_for_classifier(state)
    state.classifications = [
        classify_one(task, state, deps, claims) for task in state.evidence.tasks]
    state.phase = Phase.CLASSIFIED

    unclear = sum(1 for c in state.classifications
                  if c.direction is Direction.UNCLEAR)
    low = sum(1 for c in state.classifications
              if c.confidence is Confidence.LOW)
    LOG.info("node=classifier status=ok run_id=%s classified=%s unclear=%s "
             "low_confidence=%s", state.run_id, len(state.classifications),
             unclear, low)
    return state
