"""Exposure scoring: categories in, numbers out.

The rubric is a lookup table small enough to read in one screen and argue with,
which is the point. The charter forbids solving architecture problems with
longer prompts; the corollary is that the rubric must be inspectable rather than
buried in a model's judgment.

Two deliberate properties:

* **The mapping is about LLM and agent exposure specifically**, not automation
  in general. Routine *manual* work scores low here even though classical
  automation hits it hard, because a language model does not move boxes.
* **Tacitness discounts multiplicatively and the discount is reported.**
  Polanyi's paradox is the bound, so it must be visible in the output rather
  than folded invisibly into a single number.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from scoring.schemas import (
    Confidence,
    Direction,
    Modality,
    Routine,
    Tacitness,
    TaskClassification,
    TaskScore,
    WeightingBound,
)

LOG = logging.getLogger("scoring.exposure")

RUBRIC_VERSION = "exposure_v1"

# --------------------------------------------------------------------------
# The Acemoglu–Autor 2x2, scored for LLM/agent exposure.
#
# routine + cognitive     highest: rule-following symbolic work is what current
#                         models do well -- data pulls, formatting, extraction
# non-routine + cognitive moderate: judgment work models increasingly reach,
#                         but Eloundou et al. decline to claim displacement
# routine + manual        low: classical automation territory, not language
# non-routine + manual    lowest: Moravec's paradox still holds
# --------------------------------------------------------------------------
EXPOSURE_MATRIX: dict[tuple[Routine, Modality], float] = {
    (Routine.ROUTINE, Modality.COGNITIVE): 0.90,
    (Routine.NON_ROUTINE, Modality.COGNITIVE): 0.55,
    (Routine.ROUTINE, Modality.MANUAL): 0.20,
    (Routine.NON_ROUTINE, Modality.MANUAL): 0.05,
}

# Polanyi discount. A task whose rules cannot be articulated resists
# substitution regardless of how routine it looks from outside.
TACITNESS_PENALTY: dict[Tacitness, float] = {
    Tacitness.LOW: 0.00,
    Tacitness.MEDIUM: 0.25,
    Tacitness.HIGH: 0.55,
}

# A low-confidence classification should not carry full weight into the role
# index. This shrinks toward the matrix midpoint rather than toward zero --
# uncertainty is not evidence of safety.
CONFIDENCE_WEIGHT: dict[Confidence, float] = {
    Confidence.HIGH: 1.00,
    Confidence.MEDIUM: 0.85,
    Confidence.LOW: 0.60,
}


class RubricError(ValueError):
    """The rubric was asked for a cell it does not define."""


def exposure_raw(classification: TaskClassification) -> float:
    """Look up the matrix cell. Raises rather than guessing a default."""
    key = (classification.routine, classification.modality)
    if key not in EXPOSURE_MATRIX:
        raise RubricError(f"No rubric entry for {key}")
    return EXPOSURE_MATRIX[key]


def tacitness_penalty(classification: TaskClassification) -> float:
    """The Polanyi discount for this task, in [0,1]."""
    return TACITNESS_PENALTY[classification.tacitness]


def score_task(classification: TaskClassification, source_doc_id: str) -> TaskScore:
    """Turn one categorical classification into one scored task."""
    raw = exposure_raw(classification)
    penalty = tacitness_penalty(classification)
    adjusted = round(raw * (1.0 - penalty), 6)

    return TaskScore(
        task_id=classification.task_id,
        source_doc_id=source_doc_id,
        exposure_raw=raw,
        tacitness_penalty=penalty,
        exposure_adjusted=adjusted,
        direction=classification.direction,
        confidence=classification.confidence,
        rationale=classification.rationale,
        evidence_claim_ids=list(classification.evidence_claim_ids),
    )


def score_tasks(classifications: list[TaskClassification],
                source_doc_ids: dict[str, str]) -> list[TaskScore]:
    """Score a batch. Every task must have a known source document."""
    scores = []
    for classification in classifications:
        doc = source_doc_ids.get(classification.task_id)
        if not doc:
            raise RubricError(
                f"Task {classification.task_id} has no source document; an "
                f"unprovenanced score is not admissible")
        scores.append(score_task(classification, doc))
    return scores


# --------------------------------------------------------------------------
# Role-level aggregation
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TaskWeight:
    """One task's weight under some convention."""

    task_id: str
    weight: float


def equal_weighting(scores: list[TaskScore]) -> WeightingBound:
    """The primary convention: every task counts the same.

    This is described as an **aggregation convention**, not a claim that every
    task is economically equally important. O*NET publishes no importance
    ratings for 13-2051 — its task list is analyst-written rather than
    survey-based — so there is nothing to weight by. Stating the convention is
    the honest alternative to inventing weights.
    """
    if not scores:
        raise RubricError("cannot compute a role index from zero tasks")

    index = round(statistics.fmean(s.exposure_adjusted for s in scores), 6)
    return WeightingBound(
        weight_source="equal",
        lower=index,
        upper=index,
        note=("Equal weighting across all tasks. An aggregation convention, not "
              "a claim of equal economic importance: O*NET publishes no "
              "importance ratings for this occupation."),
    )


def adjacent_soc_bound(scores: list[TaskScore],
                       adjacent_weights: list[float],
                       adjacent_soc: str) -> WeightingBound:
    """Sensitivity bound using an adjacent occupation's importance distribution.

    There is no task-level mapping between this occupation and the adjacent
    one, so *any* particular assignment of those weights to these tasks would
    be arbitrary. Instead both extremal assignments are computed — weights
    sorted with exposure, and against it — which brackets every possible
    assignment. The result is a bound that holds regardless of the mapping,
    rather than a point estimate that depends on one nobody can justify.

    This also guards against the endogeneity problem: importing a quantitative
    occupation's importance structure as *the* answer would push the result in
    the direction the exercise is trying to measure.
    """
    if not scores:
        raise RubricError("cannot compute a role index from zero tasks")
    if not adjacent_weights:
        raise RubricError("no adjacent-occupation weights supplied")

    exposures = sorted(s.exposure_adjusted for s in scores)
    weights = sorted(adjacent_weights)

    # Recycle or truncate the weight distribution to match task count.
    if len(weights) < len(exposures):
        weights = [weights[i % len(weights)] for i in range(len(exposures))]
    weights = sorted(weights[:len(exposures)])

    total = sum(weights)
    if total <= 0:
        raise RubricError("adjacent-occupation weights sum to zero")

    # Least favourable: highest weight on lowest exposure, and vice versa.
    lower = sum(e * w for e, w in zip(exposures, reversed(weights))) / total
    upper = sum(e * w for e, w in zip(exposures, weights)) / total

    return WeightingBound(
        weight_source="adjacent_soc",
        lower=round(min(lower, upper), 6),
        upper=round(max(lower, upper), 6),
        note=(f"Bound under the importance distribution of {adjacent_soc}. No "
              f"task-level mapping exists between the occupations, so both "
              f"extremal assignments are reported; the true weighted index "
              f"lies within this range under any assignment."),
    )


def augmentation_share(scores: list[TaskScore]) -> float:
    """Share of tasks classified as augmenting rather than substituting.

    Reported because the survey prior is strongly augmentation-leaning: among
    finance firms that adopted AI, 47.2% reported their workers' skill level
    rising against 1.6% reporting it falling. A score that outputs
    "substitute" has to clear that bar.
    """
    if not scores:
        return 0.0
    augment = sum(1 for s in scores if s.direction is Direction.AUGMENT)
    return round(augment / len(scores), 6)


def unclear_share(scores: list[TaskScore]) -> float:
    """Share the classifier could not resolve. Carried forward, not hidden."""
    if not scores:
        return 0.0
    unclear = sum(1 for s in scores if s.direction is Direction.UNCLEAR)
    return round(unclear / len(scores), 6)


def confidence_profile(scores: list[TaskScore]) -> dict[str, int]:
    """Count of tasks by confidence, for the caveat section."""
    profile = {c.value: 0 for c in Confidence}
    for score in scores:
        profile[score.confidence.value] += 1
    return profile
