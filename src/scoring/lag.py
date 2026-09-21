"""Adoption-lag estimation from diffusion evidence and historical precedent.

**No curve is fitted.** The observed LLM-era window is under two years — finance
AI use moved from 29.9% to 36.5% between June 2025 and April 2026 — which cannot
identify an S-curve saturation level. Fitting one would manufacture a visual
impression of precision the data does not support. This module therefore
reports the observed trajectory, a historically grounded prior, and an explicit
interval, and it *widens* rather than narrows when the two disagree.

This module deliberately knows nothing about task exposure. It imports no
scoring path, takes no exposure argument, and could not read one if asked.
Exposure answers "how much of this work is susceptible"; this answers "how long
until the reorganisation happens". They are different questions with different
evidence, and ``tests/test_independence.py`` enforces the separation
structurally.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Sequence

from scoring.schemas import LagInterval

LOG = logging.getLogger("scoring.lag")

LAG_MODEL_VERSION = "lag_v1_no_fit"

# ---------------------------------------------------------------------------
# Historical prior for general-purpose-technology lag, in years.
#
# Anchored to the electrification precedent carried in the project's frame:
# Devine records that whether to drive machines in groups or individually was
# still being argued in the technical literature a generation after the
# technology arrived; David and Wright attribute the delay to "the need for
# organizational and above all for conceptual changes in the ways tasks and
# products are defined and structured"; Brynjolfsson, Rock and Syverson
# quantify the same mechanism as complementary intangible investment.
#
# Wide on purpose. A narrow historical prior would be its own overclaim.
# ---------------------------------------------------------------------------
HISTORICAL_PRIOR_YEARS: tuple[float, float, float] = (5.0, 15.0, 30.0)

# The penetration level at which the reorganisation is treated as having
# happened. Not a prediction -- a stated reference point, so the number means
# something specific rather than "widespread".
REFERENCE_PENETRATION_PCT = 75.0

# Below this, a trajectory cannot support a narrow interval at all.
MIN_IDENTIFYING_WINDOW_YEARS = 2.0
MIN_WIDTH_ON_SHORT_WINDOW_YEARS = 15.0

# Beyond this gap, observed and historical evidence are treated as disagreeing
# and the interval is widened rather than averaged into false agreement.
DISAGREEMENT_THRESHOLD_YEARS = 10.0


def _floor2(value: float) -> float:
    """Round down to 2dp. Used for the lower bound only."""
    return math.floor(value * 100.0) / 100.0


def _ceil2(value: float) -> float:
    """Round up to 2dp. Used for the upper bound only."""
    return math.ceil(value * 100.0) / 100.0


class LagEvidenceError(ValueError):
    """The evidence supplied cannot support any lag statement."""


@dataclass(frozen=True)
class Trajectory:
    """What the adoption observations actually show. No inference yet."""

    first_date: date
    last_date: date
    first_value: float
    last_value: float
    n_observations: int

    @property
    def window_years(self) -> float:
        return (self.last_date - self.first_date).days / 365.25

    @property
    def points_per_year(self) -> float | None:
        """Observed change in percentage points per year, or None if unusable."""
        if self.window_years <= 0:
            return None
        return (self.last_value - self.first_value) / self.window_years

    @property
    def is_identifying(self) -> bool:
        return self.window_years >= MIN_IDENTIFYING_WINDOW_YEARS


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def summarise_trajectory(observations: Sequence[dict]) -> Trajectory:
    """Reduce adoption observations to the trajectory they describe.

    Rows without a value are dropped rather than zero-filled: a suppressed
    survey cell is missing information, and treating it as zero would invent a
    decline that never happened.
    """
    points: list[tuple[date, float]] = []
    for obs in observations:
        when = _as_date(obs.get("period_start") or obs.get("Period_Start"))
        raw = obs.get("value", obs.get("Value"))
        if when is None or raw is None:
            continue
        points.append((when, float(raw)))

    if len(points) < 2:
        raise LagEvidenceError(
            f"need at least two dated observations to describe a trajectory; "
            f"got {len(points)}")

    points.sort(key=lambda p: p[0])
    return Trajectory(
        first_date=points[0][0], last_date=points[-1][0],
        first_value=points[0][1], last_value=points[-1][1],
        n_observations=len(points),
    )


def implied_years_to_reference(trajectory: Trajectory,
                               reference_pct: float = REFERENCE_PENETRATION_PCT
                               ) -> float | None:
    """Years to the reference level if the observed rate simply continued.

    Explicitly a linear extrapolation, and explicitly not a forecast. It exists
    to be compared against the historical prior, not to stand alone: diffusion
    is not linear, and the whole point of declining to fit a curve is that we
    cannot say how it bends.
    """
    rate = trajectory.points_per_year
    if rate is None or rate <= 0:
        return None
    if trajectory.last_value >= reference_pct:
        return 0.0
    return (reference_pct - trajectory.last_value) / rate


def _claim_ids(claims: Iterable[dict]) -> list[str]:
    ids = []
    for claim in claims:
        cid = claim.get("claim_id") or claim.get("Claim_ID")
        if cid:
            ids.append(str(cid))
    return ids


def estimate_lag(observations: Sequence[dict],
                 claims: Sequence[dict],
                 *,
                 prior: tuple[float, float, float] = HISTORICAL_PRIOR_YEARS,
                 reference_pct: float = REFERENCE_PENETRATION_PCT) -> LagInterval:
    """Produce a lag interval from adoption evidence and historical precedent.

    ``claims`` supply the historical grounding and are recorded in the basis so
    the prior is attributable rather than asserted. They are not parsed for
    numbers: the extraction is keyword-based and noisy, so reading magnitudes
    out of it would be less reliable than the stated prior.
    """
    trajectory = summarise_trajectory(observations)
    implied = implied_years_to_reference(trajectory, reference_pct)
    p10_prior, p50_prior, p90_prior = prior

    notes: list[str] = [
        f"Observed trajectory: {trajectory.first_value:.1f}% "
        f"({trajectory.first_date.isoformat()}) to {trajectory.last_value:.1f}% "
        f"({trajectory.last_date.isoformat()}) across "
        f"{trajectory.n_observations} observations, "
        f"{trajectory.window_years:.2f} years.",
        f"Historical GPT prior: p10={p10_prior:g}, p50={p50_prior:g}, "
        f"p90={p90_prior:g} years, anchored to the electrification precedent.",
    ]

    if implied is None:
        p10, p50, p90 = p10_prior, p50_prior, p90_prior
        notes.append(
            "Observed rate is flat or negative, so no trajectory-implied "
            "estimate is available; the historical prior stands alone.")
    else:
        notes.append(
            f"Linear extrapolation of the observed rate "
            f"({trajectory.points_per_year:.2f} points/year) reaches "
            f"{reference_pct:g}% in {implied:.1f} years. This is a comparison "
            f"point, not a forecast: no curve is fitted.")
        p10 = min(p10_prior, implied)
        p90 = max(p90_prior, implied)
        p50 = statistics.fmean([p50_prior, implied])

        if abs(implied - p50_prior) > DISAGREEMENT_THRESHOLD_YEARS:
            notes.append(
                f"Observed and historical evidence disagree by "
                f"{abs(implied - p50_prior):.1f} years, beyond the "
                f"{DISAGREEMENT_THRESHOLD_YEARS:g}-year threshold, so the "
                f"interval is widened rather than averaged into agreement.")

    # Refuse over-precision on a window too short to identify curvature.
    if not trajectory.is_identifying:
        required = MIN_WIDTH_ON_SHORT_WINDOW_YEARS
        if (p90 - p10) < required:
            centre = p50
            half = required / 2.0
            p10, p90 = max(0.0, centre - half), centre + half
            notes.append(
                f"Observation window is {trajectory.window_years:.2f} years, "
                f"under the {MIN_IDENTIFYING_WINDOW_YEARS:g}-year minimum to "
                f"identify curvature, so the interval is held at least "
                f"{required:g} years wide. A narrower interval would claim "
                f"precision the evidence cannot support.")
        else:
            notes.append(
                f"Observation window is {trajectory.window_years:.2f} years, "
                f"under the {MIN_IDENTIFYING_WINDOW_YEARS:g}-year minimum to "
                f"identify curvature; the interval is already wide enough to "
                f"reflect that.")

    supporting = _claim_ids(claims)
    if supporting:
        notes.append("Historical grounding: " + ", ".join(supporting[:6]) +
                     (f" (+{len(supporting) - 6} more)" if len(supporting) > 6 else ""))
    else:
        notes.append("No historical claims supplied; the prior is stated but "
                     "not evidenced in this run.")

    p10, p50, p90 = sorted((max(0.0, p10), max(0.0, p50), max(0.0, p90)))

    # Round directionally: the lower bound floors and the upper bound ceils, so
    # rounding can only ever WIDEN the interval. Rounding p10 to nearest would
    # let presentation narrow an interval past a value it is meant to contain,
    # which is precisely the overclaim this model exists to avoid.
    interval = LagInterval(
        p10=max(0.0, _floor2(p10)), p50=round(p50, 2), p90=_ceil2(p90),
        basis=" ".join(notes),
        observation_window_years=round(trajectory.window_years, 4),
        curve_fitted=False,
    )
    LOG.info("model=%s status=ok p10=%.2f p50=%.2f p90=%.2f window_years=%.2f",
             LAG_MODEL_VERSION, interval.p10, interval.p50, interval.p90,
             interval.observation_window_years)
    return interval
