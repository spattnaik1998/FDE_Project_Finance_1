"""Cohort-relative calibration: the comparison that is actually identified.

Calibration was unreachable for seven workstreams, and the reason was not a
missing occupation. It was two separate problems:

1. **A percentile needs a distribution.** ``percentile_within`` refuses fewer
   than ten points, correctly: two scores do not make a rank.
2. **Ranks in different populations are not comparable.** Felten/Raj/Seamans
   place Financial Analysts at the 87th percentile of *774 occupations*. Our
   index, ranked among the handful of occupations we scored, is a percentile of
   a different population. Comparing the two numbers would look like
   calibration and measure nothing.

The fix is to rank **both** series within the **same cohort**. Score N
occupations, rank our index among those N, rank the published benchmark among
those same N, and compare those. Both percentiles then describe the same
reference set and the comparison is identified.

This is also the statistically right comparison for two different estimands.
AIOE is a standardised relative index built from work activities; ours is a
task-level rubric with an explicit tacitness discount. Their *levels* are not
commensurable and never were --- so a level comparison was always going to be
noise. What is meaningful is whether the two orderings agree, which is a rank
question. The cohort-wide statistic is therefore Spearman's rho, and the
per-occupation percentile delta is the local view of it.

The honest limits, both reported rather than buried:

* **Granularity.** A cohort of N resolves to 100/N percentile points. With 12
  occupations that is 8.3 points against a ±15 tolerance --- finer than the
  tolerance, but not by much, and a single position change moves the delta by
  more than half the tolerance.
* **Cohort dependence.** A percentile within a chosen cohort is a statement
  about that cohort. This one is the finance family (SOC 13-2*), which is the
  right frame for the customer question and the wrong frame for any claim about
  the whole economy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

LOG = logging.getLogger("scoring.cohort")

# Same floor as ``calibration.percentile_within``. Below this a rank is not a
# statistic, and the two modules must not disagree about where that line sits.
COHORT_MIN = 10

# When the benchmark barely varies inside the cohort, its ordering carries
# little information and a rank comparison against it is under-powered. AIOE's
# standard deviation across the finance family is a fifth of its
# full-population standard deviation -- it was built to separate occupations
# across the whole economy, not within one family. Below this ratio the
# comparison is reported as weakly informative, because a negative rho against
# a benchmark that does not discriminate is not the same evidence as a negative
# rho against one that does.
NARROW_SPREAD_RATIO = 0.35

COHORT_TOO_SMALL = (
    "Cohort of {n} occupations is below the minimum of {minimum} needed to "
    "define a percentile. A rank within fewer points is not a statistic, so "
    "the comparison is held rather than computed."
)


def _average_ranks(values: list[float]) -> list[float]:
    """Ranks, 1-based, with ties sharing their average rank.

    Ties matter here: two occupations can carry the same published benchmark
    value (any two detail codes under one 6-digit SOC do), and assigning them
    arbitrary adjacent ranks would invent an ordering the source does not make.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        stop = position
        while (stop + 1 < len(order)
               and values[order[stop + 1]] == values[order[position]]):
            stop += 1
        shared = (position + stop) / 2.0 + 1.0
        for index in range(position, stop + 1):
            ranks[order[index]] = shared
        position = stop + 1
    return ranks


def spearman(left: list[float], right: list[float]) -> float | None:
    """Rank correlation between two series. ``None`` if undefined.

    Implemented here rather than pulled from scipy so the tie handling is
    visible and the scoring package keeps its dependency surface small.
    """
    if len(left) != len(right) or len(left) < 3:
        return None
    left_ranks, right_ranks = _average_ranks(left), _average_ranks(right)
    n = len(left_ranks)
    mean_left = sum(left_ranks) / n
    mean_right = sum(right_ranks) / n
    covariance = sum((a - mean_left) * (b - mean_right)
                     for a, b in zip(left_ranks, right_ranks))
    var_left = sum((a - mean_left) ** 2 for a in left_ranks)
    var_right = sum((b - mean_right) ** 2 for b in right_ranks)
    if var_left == 0 or var_right == 0:
        return None            # a constant series has no ordering to correlate
    return round(covariance / ((var_left * var_right) ** 0.5), 4)


def percentile_of_rank(rank: float, n: int) -> float:
    """Convert a 1-based average rank into a percentile in [0, 100].

    Uses the midpoint convention: the lowest of n occupations sits at
    ``100 * 0.5 / n`` rather than at 0, and the highest at
    ``100 * (n - 0.5) / n`` rather than at 100. Mapping the extremes to 0 and
    100 would assert that the bottom-ranked occupation has zero exposure
    relative to its cohort, which the ordering does not say.
    """
    return round(100.0 * (rank - 0.5) / n, 2)


@dataclass
class CohortCalibration:
    """Both percentiles, computed within one reference set."""

    target_soc: str
    cohort_size: int
    our_percentile: float | None
    benchmark_percentile: float | None
    rank_correlation: float | None
    granularity_points: float | None
    members: tuple[str, ...] = ()
    explanation: str | None = None
    detail: dict = field(default_factory=dict)
    benchmark_spread_ratio: float | None = None

    @property
    def benchmark_discriminates(self) -> bool:
        """Whether the benchmark varies enough inside the cohort to order it.

        ``True`` when unknown: absence of the diagnostic must not be read as
        a finding about the benchmark.
        """
        if self.benchmark_spread_ratio is None:
            return True
        return self.benchmark_spread_ratio >= NARROW_SPREAD_RATIO

    @property
    def is_identified(self) -> bool:
        return (self.our_percentile is not None
                and self.benchmark_percentile is not None)

    @property
    def delta(self) -> float | None:
        if not self.is_identified:
            return None
        return round(self.our_percentile - self.benchmark_percentile, 2)

    def summary(self) -> dict:
        return {
            "target_soc": self.target_soc,
            "cohort_size": self.cohort_size,
            "our_percentile": self.our_percentile,
            "benchmark_percentile": self.benchmark_percentile,
            "delta": self.delta,
            "rank_correlation": self.rank_correlation,
            "granularity_points": self.granularity_points,
            "identified": self.is_identified,
        }


def _population_sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def benchmark_spread_ratio(cohort_values: list[float],
                           population_values: list[float]) -> float | None:
    """How much of the benchmark's dispersion the cohort actually spans.

    The ratio of standard deviations. A low value means the benchmark treats
    the whole cohort as roughly equivalent, so its ordering inside the cohort
    is driven by small differences and a rank comparison against it is
    under-powered.

    **Both series must be in the same units.** A subset cannot be more
    dispersed than the population containing it, so a ratio above 1 means the
    two sides were measured differently -- which is how the original unit
    mismatch here was caught. The guard below refuses rather than reporting a
    number that cannot be true.
    """
    population_sd = _population_sd(population_values)
    if population_sd == 0 or len(cohort_values) < 2:
        return None
    ratio = round(_population_sd(cohort_values) / population_sd, 4)
    if ratio > 1.05:
        # Not a finding about the benchmark: a mismatch in how the two series
        # were measured. Reporting it as a spread would assert the impossible.
        LOG.warning("spread_ratio=%.4f status=rejected reason=unit_mismatch "
                    "cohort_sd=%.4f population_sd=%.4f", ratio,
                    _population_sd(cohort_values), population_sd)
        return None
    return ratio


def calibrate_within_cohort(target_soc: str,
                            our_scores: dict[str, float],
                            benchmark_values: dict[str, float],
                            *, minimum: int = COHORT_MIN,
                            population_values: list[float] | None = None
                            ) -> CohortCalibration:
    """Rank our index and the benchmark within the same cohort.

    ``our_scores`` and ``benchmark_values`` are keyed by the same occupation
    identifier. Only occupations present in **both** enter the cohort: an
    occupation we scored but the benchmark does not cover cannot contribute to
    a comparison, and including it on one side would shift that side's ranks
    against a reference set the other side never saw.
    """
    members = sorted(set(our_scores) & set(benchmark_values))
    cohort_size = len(members)

    if target_soc not in members:
        return CohortCalibration(
            target_soc=target_soc, cohort_size=cohort_size,
            our_percentile=None, benchmark_percentile=None,
            rank_correlation=None, granularity_points=None,
            members=tuple(members),
            explanation=(
                f"{target_soc} is not in the comparable cohort: it is missing "
                f"from {'our scores' if target_soc not in our_scores else 'the published benchmark'}. "
                f"No percentile can be computed for it."))

    if cohort_size < minimum:
        return CohortCalibration(
            target_soc=target_soc, cohort_size=cohort_size,
            our_percentile=None, benchmark_percentile=None,
            rank_correlation=None, granularity_points=None,
            members=tuple(members),
            explanation=COHORT_TOO_SMALL.format(n=cohort_size,
                                                minimum=minimum))

    ours = [our_scores[soc] for soc in members]
    theirs = [benchmark_values[soc] for soc in members]

    our_ranks = _average_ranks(ours)
    their_ranks = _average_ranks(theirs)
    index = members.index(target_soc)

    our_percentile = percentile_of_rank(our_ranks[index], cohort_size)
    their_percentile = percentile_of_rank(their_ranks[index], cohort_size)
    rho = spearman(ours, theirs)
    granularity = round(100.0 / cohort_size, 2)

    result = CohortCalibration(
        target_soc=target_soc, cohort_size=cohort_size,
        our_percentile=our_percentile, benchmark_percentile=their_percentile,
        rank_correlation=rho, granularity_points=granularity,
        members=tuple(members),
        benchmark_spread_ratio=(
            benchmark_spread_ratio(theirs, population_values)
            if population_values else None),
        detail={soc: {"ours": our_scores[soc],
                      "our_rank": our_ranks[i],
                      "benchmark": benchmark_values[soc],
                      "benchmark_rank": their_ranks[i]}
                for i, soc in enumerate(members)})

    LOG.info("cohort=%s target=%s ours=%.2f theirs=%.2f delta=%+.2f rho=%s "
             "granularity=%.2f", cohort_size, target_soc, our_percentile,
             their_percentile, result.delta, rho, granularity)
    return result


def cohort_explanation(result: CohortCalibration) -> str:
    """The methodological statement that accompanies a cohort comparison.

    A disagreement inside a cohort this small is a finding for a human rather
    than proof of an error, and the reasons are structural: the two indices are
    different estimands, and the resolution is coarse. Stating them is what
    makes ``review_required`` distinguishable from ``gate_rejected``.
    """
    if not result.is_identified:
        return result.explanation or "Cohort comparison is not identified."

    narrow = ""
    if not result.benchmark_discriminates:
        narrow = (
            f" The benchmark barely varies inside this cohort: its standard "
            f"deviation here is {result.benchmark_spread_ratio} of its "
            f"full-population standard deviation. AIOE was built to separate "
            f"occupations across the whole economy, not within one family, so "
            f"its ordering inside the finance family is driven by small "
            f"differences and this rank comparison is under-powered. A "
            f"disagreement against a benchmark that does not discriminate "
            f"here is weak evidence about our rubric, not strong evidence "
            f"against it — and it is not evidence for it either."
        )

    return (
        f"Both percentiles are ranks within the same cohort of "
        f"{result.cohort_size} finance occupations (SOC 13-2*), not within the "
        f"benchmark's full population of 774 — ranking our index against a "
        f"population we did not score would not be a comparison. Cohort "
        f"resolution is {result.granularity_points} percentile points, so a "
        f"single position change moves the delta by more than half the "
        f"tolerance. Rank correlation across the cohort is "
        f"{result.rank_correlation}, which is the aggregate signal; the "
        f"per-occupation delta is its local view. The two indices are "
        f"different estimands — AIOE is a standardised index over work "
        f"activities, ours is a task rubric with a tacitness discount — so "
        f"agreement in ordering is the meaningful test, not agreement in level."
        + narrow
    )


# ---------------------------------------------------------------------------
# The persisted reference set
# ---------------------------------------------------------------------------
#
# The cohort costs one model call per task across every member, so it is
# computed once and stored. A graph run reads it and ranks itself inside it.
# That is what makes calibration reachable in an interactive run without
# rescoring eleven occupations to answer a question about one.

DEFAULT_COHORT = "finance_13_2"


def persist_cohort(cursor, *, cohort_name: str, classifier: str,
                   rubric_version: str, indices: dict[str, float],
                   task_counts: dict[str, int],
                   source_run_id: str | None = None) -> int:
    """Write or refresh the reference set for one (cohort, classifier, rubric).

    Overwrites in place rather than appending, unlike ``core.*``. That is
    deliberate and the distinction matters: ``core`` holds *facts about the
    world*, which must never be rewritten because a past run's evidence has to
    stay resolvable. This table holds a *derived reference distribution* under a
    named classifier and rubric, and the run that used it records its own
    percentile in ``score.calibration``. Re-deriving it under the same key is
    the same computation, not a new fact.
    """
    written = 0
    for soc_code, index in sorted(indices.items()):
        cursor.execute("""
            DELETE FROM score.cohort_index
            WHERE cohort_name = ? AND classifier = ? AND rubric_version = ?
              AND soc_code = ?""",
            cohort_name, classifier, rubric_version, soc_code)
        cursor.execute("""
            INSERT INTO score.cohort_index
                (cohort_name, classifier, rubric_version, soc_code,
                 exposure_index, tasks_scored, source_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            cohort_name, classifier, rubric_version, soc_code,
            round(float(index), 3), int(task_counts.get(soc_code, 1)),
            source_run_id)
        written += 1
    LOG.info("cohort=%s classifier=%s rubric=%s rows=%s", cohort_name,
             classifier, rubric_version, written)
    return written


def load_cohort(cursor, *, cohort_name: str = DEFAULT_COHORT,
                classifier: str, rubric_version: str) -> dict[str, float]:
    """Read a persisted reference set. Empty dict when none exists."""
    rows = cursor.execute("""
        SELECT soc_code, exposure_index FROM score.cohort_index
        WHERE cohort_name = ? AND classifier = ? AND rubric_version = ?
        ORDER BY soc_code""",
        cohort_name, classifier, rubric_version).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def load_benchmarks(cursor, *, socs, measure: str) -> dict[str, float]:
    """Published benchmark values for the cohort, keyed as the cohort is.

    AIOE keys on the 6-digit SOC while task statements carry O*NET's 8-digit
    detail code, so the join truncates. The mapping is many-to-one and the
    cohort loader already guarantees one detail code per 6-digit SOC, so no
    benchmark value can enter the distribution twice.
    """
    if not socs:
        return {}
    bases = {soc: soc.split(".")[0] for soc in socs}
    placeholders = ",".join("?" for _ in set(bases.values()))
    rows = cursor.execute(f"""
        SELECT SOC_Code, Percentile FROM dbo.VW_EXPOSURE_BENCHMARK
        WHERE Measure = ? AND SOC_Code IN ({placeholders})""",
        measure, *sorted(set(bases.values()))).fetchall()
    by_base = {r[0]: float(r[1]) for r in rows if r[1] is not None}
    return {soc: by_base[base] for soc, base in bases.items()
            if base in by_base}


def load_population(cursor, *, measure: str) -> list[float]:
    """Every published **percentile** for a measure, for the spread diagnostic.

    Percentiles, not raw values, because the cohort side of the ratio is built
    from percentiles. The first cut of this read ``Value`` while the cohort
    used ``Percentile``, which produced a spread ratio of 4.21 -- a subset
    cannot be four times as dispersed as the population it belongs to, and that
    impossibility is what exposed the unit mismatch. The two series in a ratio
    have to be measured the same way.
    """
    rows = cursor.execute("""
        SELECT Percentile FROM dbo.VW_EXPOSURE_BENCHMARK WHERE Measure = ?""",
        measure).fetchall()
    return [float(r[0]) for r in rows if r[0] is not None]
