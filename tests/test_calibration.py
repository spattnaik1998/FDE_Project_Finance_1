"""Calibration: three states, and honest about what it cannot identify.

The state that matters most is the middle one. A binary gate would either
suppress a legitimate methodological disagreement or, loosened enough to admit
it, become decorative. ``review_required`` is what lets a large delta be a
finding rather than a verdict on the arithmetic.
"""

from __future__ import annotations

import pytest

from scoring import calibration
from scoring.schemas import CalibrationOutcome, CalibrationResult

BENCHMARK = "AIOE_language_modeling"
AIOE_PERCENTILE = 87.0
REASON = ("Equal-weight convention differs from the benchmark's estimand: AIOE "
          "is built from work activities, ours from task statements with an "
          "explicit Polanyi discount.")


def calibrate(ours, benchmark=AIOE_PERCENTILE, **kw):
    return calibration.calibrate(ours, benchmark, benchmark_measure=BENCHMARK, **kw)


# --- Pass -------------------------------------------------------------------

def test_exact_agreement_passes():
    result = calibrate(87.0)
    assert result.outcome is CalibrationOutcome.PASS
    assert result.delta == 0.0
    assert result.within_tolerance


@pytest.mark.parametrize("ours", [72.0, 80.0, 87.0, 95.0, 102.0])
def test_within_tolerance_passes(ours):
    assert calibrate(ours).outcome is CalibrationOutcome.PASS


def test_exactly_at_the_tolerance_boundary_passes():
    """15.0 points is within a +-15 tolerance, not outside it."""
    assert calibrate(87.0 - 15.0).outcome is CalibrationOutcome.PASS
    assert calibrate(87.0 + 15.0).outcome is CalibrationOutcome.PASS


def test_delta_sign_is_preserved():
    assert calibrate(80.0).delta == pytest.approx(-7.0)
    assert calibrate(94.0).delta == pytest.approx(7.0)


# --- The middle state: disagreement is not failure --------------------------

def test_outside_tolerance_with_an_explanation_is_review_required():
    result = calibrate(62.0, explanation=REASON)
    assert result.outcome is CalibrationOutcome.REVIEW_REQUIRED
    assert not result.within_tolerance
    assert result.explanation == REASON


def test_outside_tolerance_without_an_explanation_is_rejected():
    """Unexplained disagreement means the arithmetic is not trusted."""
    result = calibrate(62.0)
    assert result.outcome is CalibrationOutcome.GATE_REJECTED
    assert result.explanation is None


def test_whitespace_is_not_an_explanation():
    assert calibrate(62.0, explanation="   ").outcome is CalibrationOutcome.GATE_REJECTED


def test_schema_refuses_review_required_without_an_explanation():
    with pytest.raises(Exception, match="documented explanation"):
        CalibrationResult(
            benchmark_measure=BENCHMARK, benchmark_percentile=87.0,
            our_percentile=62.0, delta=-25.0, within_tolerance=False,
            outcome=CalibrationOutcome.REVIEW_REQUIRED, explanation=None)


def test_gate_rejected_needs_no_explanation():
    CalibrationResult(
        benchmark_measure=BENCHMARK, benchmark_percentile=87.0,
        our_percentile=62.0, delta=-25.0, within_tolerance=False,
        outcome=CalibrationOutcome.GATE_REJECTED, explanation=None)


# --- What it cannot identify ------------------------------------------------

def test_single_occupation_run_cannot_identify_a_percentile():
    """A percentile is a rank within a distribution. One score has no rank."""
    result = calibrate(None)
    assert result.outcome is CalibrationOutcome.REVIEW_REQUIRED
    assert result.our_percentile is None
    assert result.delta is None
    assert "not identifiable" in result.explanation


def test_single_occupation_explanation_says_why():
    result = calibrate(None)
    assert "one occupation" in result.explanation.lower()
    assert "rank" in result.explanation.lower()


def test_missing_benchmark_is_held_for_review_not_passed():
    result = calibration.calibrate(70.0, None, benchmark_measure=BENCHMARK)
    assert result.outcome is CalibrationOutcome.REVIEW_REQUIRED
    assert "no published benchmark" in result.explanation.lower()


def test_percentile_within_refuses_a_distribution_too_small_to_rank():
    """Two points do not make a distribution."""
    assert calibration.percentile_within(0.5, [0.1, 0.9]) is None


def test_percentile_within_computes_a_rank_on_a_real_distribution():
    distribution = [i / 100 for i in range(100)]
    assert calibration.percentile_within(0.87, distribution) == pytest.approx(87.0)


def test_percentile_within_handles_the_extremes():
    distribution = [i / 100 for i in range(100)]
    assert calibration.percentile_within(-1.0, distribution) == 0.0
    assert calibration.percentile_within(99.0, distribution) == 100.0


# --- The gate ---------------------------------------------------------------

def test_only_a_pass_allows_a_report_without_intervention():
    assert calibration.gate_allows_report(calibrate(87.0))
    assert not calibration.gate_allows_report(calibrate(62.0, explanation=REASON))
    assert not calibration.gate_allows_report(calibrate(62.0))
    assert not calibration.gate_allows_report(calibrate(None))


# --- Policy versioning ------------------------------------------------------

def test_tolerance_is_labelled_provisional():
    """It is an engineering bootstrap, not a validated criterion."""
    assert calibration.CALIBRATION_POLICY_VERSION == "provisional_v1"


def test_tolerance_is_configurable_per_run():
    tight = calibration.calibrate(80.0, AIOE_PERCENTILE,
                                  benchmark_measure=BENCHMARK,
                                  tolerance_points=2.0)
    assert tight.outcome is CalibrationOutcome.GATE_REJECTED

    loose = calibration.calibrate(80.0, AIOE_PERCENTILE,
                                  benchmark_measure=BENCHMARK,
                                  tolerance_points=50.0)
    assert loose.outcome is CalibrationOutcome.PASS


def test_calibration_is_deterministic():
    a = calibrate(62.0, explanation=REASON)
    b = calibrate(62.0, explanation=REASON)
    assert a.model_dump() == b.model_dump()
