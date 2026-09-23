"""Cohort-relative calibration.

The tests that carry weight here are the ones about *why* the cohort exists:

* a percentile needs a distribution, so a small cohort is refused rather than
  computed;
* both series must be ranked within the same reference set, so an occupation
  present on only one side cannot join;
* and a matching rank with a disagreeing ordering must not pass, which is the
  defect the first live cohort run exposed.

That last one is the important one. The target occupation landed at rank 7 of 12
in both orderings, giving a delta of exactly 0.0 and a clean pass, while
Spearman's rho across the same cohort was -0.45. A gate reading only the delta
would have certified a rubric that orders occupations roughly opposite to the
benchmark.
"""

from __future__ import annotations

import pytest

from scoring import calibration
from scoring.cohort import (COHORT_MIN, CohortCalibration,
                            calibrate_within_cohort, cohort_explanation,
                            percentile_of_rank, spearman, _average_ranks)
from scoring.schemas import CalibrationOutcome

TARGET = "13-2051.00"
MEASURE = "AIOE_language_modeling"


def _cohort(n: int = 12, *, agree: bool = True):
    """A cohort of ``n`` occupations, orderings either aligned or reversed."""
    socs = [f"13-20{11 + i:02d}.00" for i in range(n)]
    socs[min(6, n - 1)] = TARGET           # target sits mid-cohort
    ours = {soc: 0.40 + 0.01 * i for i, soc in enumerate(socs)}
    if agree:
        theirs = {soc: 80.0 + 1.0 * i for i, soc in enumerate(socs)}
    else:
        theirs = {soc: 80.0 + 1.0 * (n - i) for i, soc in enumerate(socs)}
    return socs, ours, theirs


# ===========================================================================
# Rank machinery
# ===========================================================================

def test_ties_share_an_average_rank():
    """Two detail codes under one SOC carry the same benchmark value.

    Assigning them arbitrary adjacent ranks would invent an ordering the
    source does not make.
    """
    assert _average_ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]
    assert _average_ranks([5.0, 5.0, 5.0]) == [2.0, 2.0, 2.0]


def test_percentile_uses_the_midpoint_convention():
    """The bottom of a cohort is not at zero.

    Mapping the extremes to 0 and 100 would assert the bottom-ranked
    occupation has zero exposure relative to its cohort, which a rank does
    not say.
    """
    assert percentile_of_rank(1, 12) == pytest.approx(4.17, abs=0.01)
    assert percentile_of_rank(12, 12) == pytest.approx(95.83, abs=0.01)
    assert percentile_of_rank(6.5, 12) == pytest.approx(50.0, abs=0.01)


def test_spearman_is_one_for_identical_orderings():
    assert spearman([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]) == 1.0


def test_spearman_is_minus_one_for_reversed_orderings():
    assert spearman([1.0, 2.0, 3.0, 4.0], [40.0, 30.0, 20.0, 10.0]) == -1.0


def test_spearman_is_none_for_a_constant_series():
    """A series with no ordering has no ordering to correlate."""
    assert spearman([1.0, 1.0, 1.0, 1.0], [1.0, 2.0, 3.0, 4.0]) is None


def test_spearman_is_none_below_three_points():
    assert spearman([1.0, 2.0], [1.0, 2.0]) is None


def test_spearman_handles_ties_without_raising():
    assert spearman([1.0, 1.0, 2.0, 3.0], [5.0, 6.0, 6.0, 7.0]) is not None


# ===========================================================================
# The cohort must be big enough, and shared
# ===========================================================================

def test_a_cohort_below_the_minimum_is_refused():
    """Scoring one more occupation was never going to be enough."""
    socs, ours, theirs = _cohort(n=4)
    result = calibrate_within_cohort(TARGET, ours, theirs)

    assert not result.is_identified
    assert result.our_percentile is None
    assert result.cohort_size == 4
    assert "below the minimum" in result.explanation
    assert str(COHORT_MIN) in result.explanation


def test_two_occupations_do_not_make_a_distribution():
    """The specific claim corrected before this workstream started."""
    ours = {TARGET: 0.5, "13-2099.01": 0.4}
    theirs = {TARGET: 86.82, "13-2099.01": 85.4}

    result = calibrate_within_cohort(TARGET, ours, theirs)

    assert not result.is_identified
    assert result.cohort_size == 2


def test_only_occupations_on_both_sides_join_the_cohort():
    """A one-sided member would shift one side's ranks and not the other."""
    socs, ours, theirs = _cohort(n=12)
    ours["13-9999.00"] = 0.99          # scored by us, not in the benchmark
    theirs["13-8888.00"] = 99.0        # benchmarked, not scored by us

    result = calibrate_within_cohort(TARGET, ours, theirs)

    assert result.cohort_size == 12
    assert "13-9999.00" not in result.members
    assert "13-8888.00" not in result.members


def test_a_target_outside_the_cohort_gets_no_percentile():
    socs, ours, theirs = _cohort(n=12)
    result = calibrate_within_cohort("99-9999.00", ours, theirs)

    assert not result.is_identified
    assert "not in the comparable cohort" in result.explanation


def test_a_target_we_did_not_score_names_the_missing_side():
    socs, ours, theirs = _cohort(n=12)
    theirs["44-4444.00"] = 90.0
    result = calibrate_within_cohort("44-4444.00", ours, theirs)
    assert "our scores" in result.explanation


# ===========================================================================
# An identified comparison
# ===========================================================================

def test_an_aligned_cohort_identifies_and_agrees():
    socs, ours, theirs = _cohort(n=12, agree=True)
    result = calibrate_within_cohort(TARGET, ours, theirs)

    assert result.is_identified
    assert result.cohort_size == 12
    assert result.rank_correlation == 1.0
    assert result.delta == pytest.approx(0.0, abs=0.01)
    assert result.granularity_points == pytest.approx(8.33, abs=0.01)


def test_both_percentiles_are_ranks_in_the_same_reference_set():
    """Neither percentile may be a rank within the benchmark's 774."""
    socs, ours, theirs = _cohort(n=12, agree=True)
    result = calibrate_within_cohort(TARGET, ours, theirs)

    # The benchmark's own published percentile for the target is ~86; its
    # percentile *within this cohort* must be the cohort rank instead.
    assert result.benchmark_percentile < 100
    assert result.benchmark_percentile != pytest.approx(86.82, abs=0.01)
    assert set(result.detail) == set(result.members)


def test_the_detail_table_exposes_every_rank():
    """The ranking has to be auditable, not just its conclusion."""
    socs, ours, theirs = _cohort(n=12)
    result = calibrate_within_cohort(TARGET, ours, theirs)

    for soc in result.members:
        row = result.detail[soc]
        assert {"ours", "our_rank", "benchmark", "benchmark_rank"} <= set(row)


def test_granularity_is_reported_and_scales_with_cohort_size():
    for n, expected in ((10, 10.0), (12, 8.33), (20, 5.0)):
        socs, ours, theirs = _cohort(n=n)
        result = calibrate_within_cohort(TARGET, ours, theirs)
        assert result.granularity_points == pytest.approx(expected, abs=0.01)


def test_the_explanation_states_the_cohort_and_its_limits():
    socs, ours, theirs = _cohort(n=12)
    text = cohort_explanation(calibrate_within_cohort(TARGET, ours, theirs))

    assert "same cohort" in text
    assert "774" in text                     # names the population not used
    assert "resolution" in text
    assert "different estimands" in text


# ===========================================================================
# The defect the first live cohort run exposed
# ===========================================================================

def test_a_matching_rank_with_a_reversed_ordering_does_not_pass():
    """The important test in this file.

    A delta of zero is not evidence of agreement when the orderings diverge.
    """
    socs, ours, theirs = _cohort(n=12, agree=False)
    result = calibrate_within_cohort(TARGET, ours, theirs)

    assert result.is_identified
    assert result.rank_correlation < 0

    outcome = calibration.calibrate(
        result.our_percentile, result.benchmark_percentile,
        benchmark_measure=MEASURE,
        rank_correlation=result.rank_correlation,
        explanation=cohort_explanation(result))

    assert outcome.within_tolerance is True, "the delta itself is small"
    assert outcome.outcome is CalibrationOutcome.REVIEW_REQUIRED, (
        "a small delta with a disagreeing ordering must not pass")
    assert "order this cohort in substantially different ways" in (
        outcome.explanation)


def test_the_ordering_check_does_not_fire_when_orderings_agree():
    socs, ours, theirs = _cohort(n=12, agree=True)
    result = calibrate_within_cohort(TARGET, ours, theirs)

    outcome = calibration.calibrate(
        result.our_percentile, result.benchmark_percentile,
        benchmark_measure=MEASURE,
        rank_correlation=result.rank_correlation)

    assert outcome.outcome is CalibrationOutcome.PASS


@pytest.mark.parametrize("rho,expected", [
    (1.0, CalibrationOutcome.PASS),
    (0.60, CalibrationOutcome.PASS),
    (0.30, CalibrationOutcome.PASS),
    (0.29, CalibrationOutcome.REVIEW_REQUIRED),
    (0.0, CalibrationOutcome.REVIEW_REQUIRED),
    (-0.45, CalibrationOutcome.REVIEW_REQUIRED),
])
def test_the_rank_correlation_floor_is_enforced(rho, expected):
    outcome = calibration.calibrate(
        50.0, 50.0, benchmark_measure=MEASURE, rank_correlation=rho)
    assert outcome.outcome is expected


def test_no_rank_correlation_leaves_the_old_behaviour_intact():
    """A single-occupation run has no ordering; the check must not fire."""
    outcome = calibration.calibrate(
        50.0, 50.0, benchmark_measure=MEASURE, rank_correlation=None)
    assert outcome.outcome is CalibrationOutcome.PASS


def test_a_wide_delta_still_rejects_without_an_explanation():
    """The ordering check must not have weakened the delta rule."""
    outcome = calibration.calibrate(
        10.0, 90.0, benchmark_measure=MEASURE, rank_correlation=1.0)
    assert outcome.outcome is CalibrationOutcome.GATE_REJECTED


def test_the_policy_version_records_that_the_criterion_changed():
    """A figure calibrated under v1 is not comparable to one under v2."""
    assert calibration.CALIBRATION_POLICY_VERSION == "provisional_v2_cohort"


def test_the_cohort_minimum_matches_the_percentile_guard():
    """Two modules must not disagree about where a rank becomes a statistic."""
    from scoring.calibration import percentile_within

    assert percentile_within(0.5, [0.1] * (COHORT_MIN - 1)) is None
    assert percentile_within(0.5, [0.1] * COHORT_MIN) is not None


# ===========================================================================
# Shape
# ===========================================================================

def test_summary_is_reportable():
    socs, ours, theirs = _cohort(n=12)
    summary = calibrate_within_cohort(TARGET, ours, theirs).summary()

    for key in ("target_soc", "cohort_size", "our_percentile",
                "benchmark_percentile", "delta", "rank_correlation",
                "granularity_points", "identified"):
        assert key in summary


def test_an_unidentified_cohort_has_no_delta():
    result = CohortCalibration(
        target_soc=TARGET, cohort_size=3, our_percentile=None,
        benchmark_percentile=None, rank_correlation=None,
        granularity_points=None)
    assert result.delta is None
    assert not result.is_identified


# ===========================================================================
# Does the benchmark discriminate inside the cohort at all?
# ===========================================================================

def test_a_narrow_benchmark_spread_is_reported():
    """AIOE compresses the whole finance family into a narrow band.

    Its within-finance percentile dispersion is about 15% of its
    full-population dispersion, so its ordering inside the family is driven by
    small differences and a rank comparison against it is under-powered.
    """
    socs, ours, theirs = _cohort(n=12, agree=False)
    # Cohort percentiles clustered high; population spread across the range.
    theirs = {soc: 80.0 + 0.5 * i for i, soc in enumerate(socs)}
    population = [float(i) for i in range(0, 100)]

    result = calibrate_within_cohort(TARGET, ours, theirs,
                                     population_values=population)

    assert result.benchmark_spread_ratio is not None
    assert result.benchmark_spread_ratio < 0.35
    assert not result.benchmark_discriminates
    assert "barely varies" in cohort_explanation(result)
    assert "under-powered" in cohort_explanation(result)


def test_a_wide_benchmark_spread_is_not_flagged():
    socs, ours, theirs = _cohort(n=12, agree=True)
    theirs = {soc: 5.0 + 8.0 * i for i, soc in enumerate(socs)}
    population = [float(i) for i in range(0, 100)]

    result = calibrate_within_cohort(TARGET, ours, theirs,
                                     population_values=population)

    assert result.benchmark_discriminates
    assert "barely varies" not in cohort_explanation(result)


def test_an_impossible_spread_ratio_is_refused_not_reported():
    """A subset cannot be more dispersed than its own population.

    A ratio above 1 means the two series were measured differently -- which is
    exactly how the original unit mismatch here was caught, when cohort
    percentiles were divided by population raw values and produced 4.21.
    Reporting that as a spread would assert something that cannot be true.
    """
    from scoring.cohort import benchmark_spread_ratio

    # Cohort in percentile units, population in index units: the real bug.
    cohort_percentiles = [79.3, 83.5, 86.8, 91.9, 94.4]
    population_values = [-1.85, -0.5, 0.0, 0.6, 1.93]

    assert benchmark_spread_ratio(cohort_percentiles, population_values) is None


def test_matching_units_give_a_ratio_at_or_below_one():
    from scoring.cohort import benchmark_spread_ratio

    population = [float(i) for i in range(100)]
    ratio = benchmark_spread_ratio([40.0, 45.0, 50.0, 55.0], population)
    assert ratio is not None and 0 < ratio <= 1.0


def test_an_absent_diagnostic_is_not_read_as_a_finding():
    """No population supplied means unknown, not "does not discriminate"."""
    socs, ours, theirs = _cohort(n=12)
    result = calibrate_within_cohort(TARGET, ours, theirs)

    assert result.benchmark_spread_ratio is None
    assert result.benchmark_discriminates is True
