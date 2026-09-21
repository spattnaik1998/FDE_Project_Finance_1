"""Typed contracts for the deterministic scoring service.

These are the boundary between what a model may judge and what Python must
compute. A :class:`TaskClassification` is the *only* thing the classifier node
produces: categorical judgments, never a number. Every numeric field below is
derived here, in code, from those categories — so a model change cannot move a
customer-facing quantity.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Routine(str, Enum):
    """Acemoglu–Autor routine axis."""

    ROUTINE = "routine"
    NON_ROUTINE = "non_routine"


class Modality(str, Enum):
    """Acemoglu–Autor cognitive/manual axis."""

    COGNITIVE = "cognitive"
    MANUAL = "manual"


class Tacitness(str, Enum):
    """Polanyi's paradox, as a three-level judgment.

    "We know more than we can tell." Autor's bound: substitution is limited by
    tasks people accomplish tacitly but cannot articulate rules for.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Direction(str, Enum):
    """Whether the capability substitutes for the worker or augments them.

    Acemoglu & Johnson: direction is chosen, not given. ``UNCLEAR`` is a
    first-class outcome — a classifier that cannot tell must say so rather than
    be re-prompted into agreement.
    """

    AUGMENT = "augment"
    SUBSTITUTE = "substitute"
    UNCLEAR = "unclear"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskClassification(BaseModel):
    """What the classifier node emits for one task: categories only.

    There is deliberately no numeric field on this model. If a score could be
    supplied here, a model could set it.
    """

    task_id: str
    routine: Routine
    modality: Modality
    tacitness: Tacitness
    direction: Direction
    confidence: Confidence
    rationale: str = Field(min_length=1)
    evidence_claim_ids: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


class TaskScore(BaseModel):
    """One scored task. Every number here was computed, not judged."""

    task_id: str
    source_doc_id: str
    exposure_raw: float = Field(ge=0.0, le=1.0)
    tacitness_penalty: float = Field(ge=0.0, le=1.0)
    exposure_adjusted: float = Field(ge=0.0, le=1.0)
    direction: Direction
    confidence: Confidence
    rationale: str
    evidence_claim_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _penalty_was_applied(self) -> "TaskScore":
        expected = round(self.exposure_raw * (1.0 - self.tacitness_penalty), 6)
        if abs(self.exposure_adjusted - expected) > 1e-6:
            raise ValueError(
                f"exposure_adjusted must equal raw * (1 - tacitness): "
                f"{self.exposure_raw} * (1 - {self.tacitness_penalty}) "
                f"= {expected}, got {self.exposure_adjusted}")
        return self


class WeightingBound(BaseModel):
    """Role index under a weighting convention.

    ``lower`` and ``upper`` coincide for equal weighting. For the adjacent-SOC
    sensitivity they differ, because no task-level mapping exists between the
    two occupations — so a bound is reported rather than a false point estimate.
    """

    weight_source: str
    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)
    note: str

    @model_validator(mode="after")
    def _ordered(self) -> "WeightingBound":
        if self.lower > self.upper:
            raise ValueError("lower bound cannot exceed upper bound")
        return self

    @property
    def is_point_estimate(self) -> bool:
        return abs(self.upper - self.lower) < 1e-9


class LagInterval(BaseModel):
    """Adoption lag in years, as an interval. Never a point.

    Computed from adoption observations and historical claims only. It has no
    field for exposure and no constructor path that accepts one.
    """

    p10: float = Field(ge=0.0)
    p50: float = Field(ge=0.0)
    p90: float = Field(ge=0.0)
    basis: str = Field(min_length=1, description="Which observations drove this")
    observation_window_years: float = Field(ge=0.0)
    curve_fitted: bool = Field(
        default=False,
        description="False by design: the observed window cannot identify a "
                    "saturation level, so no S-curve is fitted.")

    @model_validator(mode="after")
    def _ordered_and_not_overprecise(self) -> "LagInterval":
        if not (self.p10 <= self.p50 <= self.p90):
            raise ValueError(f"lag interval must be ordered: "
                             f"{self.p10} <= {self.p50} <= {self.p90}")
        return self

    @property
    def width(self) -> float:
        return self.p90 - self.p10


class CalibrationOutcome(str, Enum):
    """Three states, because disagreement and failure are different things."""

    PASS = "pass"
    REVIEW_REQUIRED = "review_required"
    GATE_REJECTED = "gate_rejected"


class CalibrationResult(BaseModel):
    benchmark_measure: str
    benchmark_percentile: float | None
    our_percentile: float | None
    delta: float | None
    within_tolerance: bool
    outcome: CalibrationOutcome
    explanation: str | None = None

    @model_validator(mode="after")
    def _review_needs_explanation(self) -> "CalibrationResult":
        if self.outcome is CalibrationOutcome.REVIEW_REQUIRED and not (
                self.explanation or "").strip():
            raise ValueError("review_required must carry a documented explanation; "
                             "that is what distinguishes it from gate_rejected")
        return self


class RoleVerdict(BaseModel):
    """The role-level output. Exposure and lag are separate fields, by design."""

    soc_code: str
    exposure_index: float = Field(ge=0.0, le=1.0)
    primary_weighting: WeightingBound
    sensitivity_weighting: WeightingBound | None
    lag: LagInterval
    augmentation_share: float = Field(ge=0.0, le=1.0)
    unclear_share: float = Field(ge=0.0, le=1.0)
    calibration: CalibrationResult
    caveats: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _caveats_are_substantive(self) -> "RoleVerdict":
        if not any((c or "").strip() for c in self.caveats):
            raise ValueError("a verdict must carry at least one stated caveat")
        return self
