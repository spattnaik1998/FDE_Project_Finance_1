"""The lag model: an interval that refuses to be narrower than the evidence.

The decisive property here is *negative*. The model must decline to fit a curve
and must refuse over-precision on a short window. A lag model that produced a
tight interval from 11 months of data would be the single most likely thing in
this project to embarrass us in front of a customer who knows diffusion curves.
"""

from __future__ import annotations

import pytest

from scoring import lag
from scoring.schemas import LagInterval


def series(points: list[tuple[str, float]]) -> list[dict]:
    return [{"period_start": d, "value": v} for d, v in points]


LONG_WINDOW = series([
    ("2020-01-01", 5.0), ("2022-01-01", 20.0), ("2024-01-01", 38.0),
    ("2026-01-01", 55.0),
])


# --- It does not fit a curve ------------------------------------------------

def test_curve_is_never_fitted(adoption_series, lag_claims):
    interval = lag.estimate_lag(adoption_series, lag_claims)
    assert interval.curve_fitted is False


def test_basis_states_that_no_curve_was_fitted(adoption_series, lag_claims):
    basis = lag.estimate_lag(adoption_series, lag_claims).basis
    assert "no curve is fitted" in basis.lower()


# --- It refuses over-precision on a short window ----------------------------

def test_short_window_forces_a_wide_interval(adoption_series, lag_claims):
    """The observed window is ~0.9 years. It cannot identify curvature."""
    interval = lag.estimate_lag(adoption_series, lag_claims)
    assert interval.observation_window_years < lag.MIN_IDENTIFYING_WINDOW_YEARS
    assert interval.width >= lag.MIN_WIDTH_ON_SHORT_WINDOW_YEARS


def test_short_window_is_named_in_the_basis(adoption_series, lag_claims):
    basis = lag.estimate_lag(adoption_series, lag_claims).basis
    assert "under the" in basis.lower() and "minimum" in basis.lower()
    assert "precision the evidence cannot support" in basis.lower() or \
           "already wide enough" in basis.lower()


def test_a_tight_prior_cannot_produce_a_tight_interval_on_a_short_window(
        adoption_series, lag_claims):
    """Even handed a deliberately narrow prior, the model must widen."""
    interval = lag.estimate_lag(adoption_series, lag_claims, prior=(9.0, 10.0, 11.0))
    assert interval.width >= lag.MIN_WIDTH_ON_SHORT_WINDOW_YEARS


def test_long_window_is_allowed_a_narrower_interval(lag_claims):
    """The refusal is tied to the evidence, not hardcoded pessimism."""
    interval = lag.estimate_lag(LONG_WINDOW, lag_claims, prior=(9.0, 10.0, 11.0))
    assert interval.observation_window_years >= lag.MIN_IDENTIFYING_WINDOW_YEARS
    assert interval.width < lag.MIN_WIDTH_ON_SHORT_WINDOW_YEARS


# --- Interval integrity -----------------------------------------------------

def test_interval_is_ordered(adoption_series, lag_claims):
    i = lag.estimate_lag(adoption_series, lag_claims)
    assert i.p10 <= i.p50 <= i.p90


def test_interval_is_non_negative(lag_claims):
    """A lag cannot be in the past."""
    already_there = series([("2024-01-01", 80.0), ("2026-01-01", 95.0)])
    i = lag.estimate_lag(already_there, lag_claims)
    assert i.p10 >= 0.0


def test_schema_rejects_an_inverted_interval():
    with pytest.raises(Exception, match="ordered"):
        LagInterval(p10=9, p50=3, p90=1, basis="b", observation_window_years=1.0)


def test_schema_requires_a_basis():
    with pytest.raises(Exception):
        LagInterval(p10=1, p50=2, p90=3, basis="", observation_window_years=1.0)


# --- Trajectory summarisation ------------------------------------------------

def test_trajectory_reads_first_and_last_chronologically():
    t = lag.summarise_trajectory(series([
        ("2026-04-27", 36.5), ("2025-06-09", 29.9), ("2026-01-01", 31.0)]))
    assert t.first_value == 29.9
    assert t.last_value == 36.5
    assert t.n_observations == 3


def test_suppressed_observations_are_dropped_not_zeroed():
    """Zero-filling a suppressed cell would invent a decline."""
    with_nulls = series([("2025-06-09", 29.9), ("2026-04-27", 36.5)])
    with_nulls.insert(1, {"period_start": "2025-12-01", "value": None})
    t = lag.summarise_trajectory(with_nulls)
    assert t.n_observations == 2
    assert t.points_per_year > 0


def test_a_single_observation_cannot_describe_a_trajectory():
    with pytest.raises(lag.LagEvidenceError, match="at least two"):
        lag.summarise_trajectory(series([("2026-01-01", 30.0)]))


def test_empty_observations_are_refused():
    with pytest.raises(lag.LagEvidenceError):
        lag.summarise_trajectory([])


def test_warehouse_column_names_are_accepted():
    """VW_ADOPTION_CURVE returns Period_Start/Value, not period_start/value."""
    t = lag.summarise_trajectory([
        {"Period_Start": "2025-06-09", "Value": 29.9},
        {"Period_Start": "2026-04-27", "Value": 36.5},
    ])
    assert t.first_value == 29.9


def test_rate_is_computed_per_year():
    t = lag.summarise_trajectory(series([("2024-01-01", 10.0), ("2026-01-01", 30.0)]))
    assert t.points_per_year == pytest.approx(10.0, rel=0.01)


# --- Flat or declining adoption ---------------------------------------------

def test_flat_adoption_yields_no_implied_estimate(lag_claims):
    flat = series([("2024-01-01", 30.0), ("2026-01-01", 30.0)])
    assert lag.implied_years_to_reference(lag.summarise_trajectory(flat)) is None


def test_declining_adoption_yields_no_implied_estimate(lag_claims):
    declining = series([("2024-01-01", 40.0), ("2026-01-01", 30.0)])
    assert lag.implied_years_to_reference(lag.summarise_trajectory(declining)) is None


def test_flat_adoption_falls_back_to_the_historical_prior(lag_claims):
    flat = series([("2024-01-01", 30.0), ("2026-01-01", 30.0)])
    interval = lag.estimate_lag(flat, lag_claims)
    assert (interval.p10, interval.p50, interval.p90) == lag.HISTORICAL_PRIOR_YEARS
    assert "flat or negative" in interval.basis


def test_already_at_reference_implies_zero_remaining_years():
    done = lag.summarise_trajectory(series([("2024-01-01", 70.0), ("2026-01-01", 90.0)]))
    assert lag.implied_years_to_reference(done) == 0.0


# --- Disagreement widens rather than averages -------------------------------

def test_disagreement_between_sources_is_declared(lag_claims):
    """A fast observed trajectory against a slow historical prior."""
    fast = series([("2024-01-01", 10.0), ("2026-01-01", 70.0)])
    interval = lag.estimate_lag(fast, lag_claims, prior=(20.0, 40.0, 60.0))
    assert "disagree" in interval.basis.lower()


def test_interval_spans_both_sources_when_they_disagree(lag_claims):
    fast = series([("2024-01-01", 10.0), ("2026-01-01", 70.0)])
    interval = lag.estimate_lag(fast, lag_claims, prior=(20.0, 40.0, 60.0))
    implied = lag.implied_years_to_reference(lag.summarise_trajectory(fast))
    assert interval.p10 <= implied <= interval.p90
    assert interval.p90 >= 60.0, "the historical upper bound must survive"


# --- Provenance of the prior -------------------------------------------------

def test_supporting_claims_are_recorded_in_the_basis(adoption_series, lag_claims):
    basis = lag.estimate_lag(adoption_series, lag_claims).basis
    assert lag_claims[0]["claim_id"] in basis


def test_absent_claims_are_declared_rather_than_ignored(adoption_series):
    basis = lag.estimate_lag(adoption_series, []).basis
    assert "not evidenced" in basis.lower()


def test_basis_reports_the_observed_trajectory_numerically(adoption_series, lag_claims):
    basis = lag.estimate_lag(adoption_series, lag_claims).basis
    assert "29.9%" in basis and "36.5%" in basis


def test_historical_prior_is_wide_by_construction():
    """A narrow historical prior would be its own overclaim."""
    p10, p50, p90 = lag.HISTORICAL_PRIOR_YEARS
    assert p90 - p10 >= 20.0


# --- Determinism -------------------------------------------------------------

def test_lag_estimation_is_deterministic(adoption_series, lag_claims):
    a = lag.estimate_lag(adoption_series, lag_claims)
    b = lag.estimate_lag(adoption_series, lag_claims)
    assert a.model_dump() == b.model_dump()
