"""Calibration against published exposure benchmarks.

Three states, because **calibration disagreement and calibration failure are
different things**. Our methodology and Felten/Raj/Seamans' AIOE are not the
same estimand: theirs is a standardised relative index built from work
activities, ours is a task-level rubric with an explicit Polanyi discount. A
large delta accompanied by a documented methodological reason is a finding, not
proof that the arithmetic is wrong. A gate that rejected it would quietly turn
this system into a mechanism for reproducing somebody else's number.

The tolerance is ``provisional_v1`` and is labelled as such: it is an
engineering bootstrap, not a validated criterion. The empirical distribution of
deviations across occupations should be examined before it is locked.
"""

from __future__ import annotations

import logging
from bisect import bisect_left
from typing import Sequence

from scoring.schemas import CalibrationOutcome, CalibrationResult

LOG = logging.getLogger("scoring.calibration")

# Bumped from provisional_v1 when cohort calibration arrived: the criterion
# itself changed, so a figure calibrated under the old rule is not comparable
# to one calibrated under this one. The version is the only thing that tells
# those two apart in the audit record.
CALIBRATION_POLICY_VERSION = "provisional_v2_cohort"
DEFAULT_TOLERANCE_POINTS = 15.0

# A cohort comparison must clear two bars, not one. The first cohort run found
# out why: the target occupation sat at rank 7 of 12 in BOTH orderings, giving
# a delta of exactly 0.0 and a clean pass -- while Spearman's rho across the
# same cohort was -0.45. The orderings disagreed almost completely and the
# matching rank was coincidence. A single-point delta cannot see that, and a
# gate that reads only the delta will pass a rubric that anti-correlates with
# the benchmark.
#
# So: a negative rho can never pass, and weak positive agreement is held for
# review. Provisional like the tolerance -- with 12 points rho has wide
# variance, and the floor should be set from the empirical distribution once
# more cohorts exist rather than from this one.
MIN_RANK_CORRELATION = 0.30

ANTI_CORRELATED_EXPLANATION = (
    "Our index and the published benchmark order this cohort in substantially "
    "different ways (rank correlation {rho}). The target occupation's "
    "percentile delta of {delta} is therefore not evidence of agreement: a "
    "single rank can coincide while the orderings diverge. Ordering agreement "
    "is the meaningful test for two indices on different scales, so the run is "
    "held rather than passed on the delta alone."
)

SINGLE_OCCUPATION_EXPLANATION = (
    "Our percentile is not identifiable from a single scored occupation. A "
    "percentile is a rank within a distribution, and this run scored one "
    "occupation, so there is no distribution of our own scores to rank within. "
    "The benchmark value is recorded for reference and the run is held for "
    "review rather than passed or rejected on an unidentifiable comparison."
)


class CalibrationError(ValueError):
    """Calibration was asked for something it cannot compute."""


def percentile_within(value: float, distribution: Sequence[float]) -> float | None:
    """Where ``value`` sits in ``distribution``, as a percentile.

    Returns ``None`` when the distribution is too small to define a rank. Two
    points do not make a distribution, and pretending otherwise is how a
    meaningless number acquires a decimal place.
    """
    ordered = sorted(distribution)
    if len(ordered) < 10:
        return None
    below = bisect_left(ordered, value)
    return round(100.0 * below / len(ordered), 2)


def calibrate(our_percentile: float | None,
              benchmark_percentile: float | None,
              *,
              benchmark_measure: str,
              tolerance_points: float = DEFAULT_TOLERANCE_POINTS,
              rank_correlation: float | None = None,
              explanation: str | None = None) -> CalibrationResult:
    """Compare our percentile with a published one and emit one of three states.

    ``our_percentile`` of ``None`` means the comparison is not identifiable —
    which yields ``review_required`` with a stated reason, never a silent pass.
    """
    if benchmark_percentile is None:
        return CalibrationResult(
            benchmark_measure=benchmark_measure,
            benchmark_percentile=None, our_percentile=our_percentile,
            delta=None, within_tolerance=False,
            outcome=CalibrationOutcome.REVIEW_REQUIRED,
            explanation=explanation or (
                f"No published benchmark available for {benchmark_measure}, so "
                f"the result is uncalibrated and held for review."))

    if our_percentile is None:
        return CalibrationResult(
            benchmark_measure=benchmark_measure,
            benchmark_percentile=benchmark_percentile, our_percentile=None,
            delta=None, within_tolerance=False,
            outcome=CalibrationOutcome.REVIEW_REQUIRED,
            explanation=explanation or SINGLE_OCCUPATION_EXPLANATION)

    delta = round(our_percentile - benchmark_percentile, 2)
    within = abs(delta) <= tolerance_points

    # The ordering check. Only applies when a cohort-wide correlation was
    # supplied; a single-occupation run has no ordering to correlate and is
    # already held above.
    ordering_disagrees = (rank_correlation is not None
                          and rank_correlation < MIN_RANK_CORRELATION)

    if within and ordering_disagrees:
        # The case that motivated this check: delta says agree, rho says no.
        return CalibrationResult(
            benchmark_measure=benchmark_measure,
            benchmark_percentile=benchmark_percentile,
            our_percentile=our_percentile, delta=delta,
            within_tolerance=within,
            outcome=CalibrationOutcome.REVIEW_REQUIRED,
            explanation=(explanation or "") + (" " if explanation else "")
            + ANTI_CORRELATED_EXPLANATION.format(rho=rank_correlation,
                                                 delta=delta))

    if within:
        outcome = CalibrationOutcome.PASS
        detail = explanation
    elif (explanation or "").strip():
        # Disagreement with a documented reason: a finding for a human.
        outcome = CalibrationOutcome.REVIEW_REQUIRED
        detail = explanation
    else:
        # Disagreement with no account of why: the arithmetic is not trusted.
        outcome = CalibrationOutcome.GATE_REJECTED
        detail = None

    LOG.info("policy=%s status=%s benchmark=%.2f ours=%.2f delta=%+.2f "
             "tolerance=%.1f rho=%s", CALIBRATION_POLICY_VERSION,
             outcome.value, benchmark_percentile, our_percentile, delta,
             tolerance_points, rank_correlation)

    return CalibrationResult(
        benchmark_measure=benchmark_measure,
        benchmark_percentile=benchmark_percentile,
        our_percentile=our_percentile, delta=delta,
        within_tolerance=within, outcome=outcome, explanation=detail)


def gate_allows_report(result: CalibrationResult) -> bool:
    """Only a clean pass produces a report without human intervention."""
    return result.outcome is CalibrationOutcome.PASS
