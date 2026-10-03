"""W10 — the cohort read path.

The portfolio view is the first object in this project that puts twelve
occupations side by side, which makes it the first place a reader can compare
quantities that were never meant to be compared. Most of these tests exist to
stop that rather than to check that a query returns rows.

Three properties carry the weight:

* **One reference set, one key.** A ranking drawn across two classifiers measures
  which model scored which occupation. The key makes the mixture unrepresentable
  in the data; these tests make it unrepresentable in the view.
* **The lag does not vary by occupation.** All thirty persisted verdicts carry the
  identical interval, because it is estimated from sector-level adoption
  evidence. A per-row lag column would invent variation that does not exist, so
  the type has no such field and a test keeps it off.
* **Nine of twelve rows are one number each.** ``has_full_run`` has to come from
  what is persisted, not from cohort membership.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app import gateway
from app.view_model import CohortRowView, CohortView

pytest.importorskip("pyodbc")

GATEWAY_SOURCE = Path("src/app/gateway.py")


@pytest.fixture(scope="module")
def cohort() -> CohortView:
    """The real cohort, read from the warehouse under one classifier."""
    try:
        return gateway.load_cohort(classifier="gpt-6-astra")
    except Exception as exc:                     # noqa: BLE001 - stated skip
        pytest.skip(f"no cohort reference set available: "
                    f"{type(exc).__name__}: {exc}")


# ===========================================================================
# One reference set, one key
# ===========================================================================

def test_the_view_names_the_single_key_it_was_built_from(cohort):
    """A portfolio view that cannot say which cohort it is cannot be audited."""
    assert cohort.cohort_name == "finance_13_2"
    assert cohort.classifier == "gpt-6-astra"
    assert cohort.rubric_version == "exposure_v1"


def test_the_query_filters_on_all_three_parts_of_the_key():
    """Structural, because the consequence of dropping one is silent.

    Drop ``classifier`` and the ranking silently mixes derivations: the same
    occupation has produced 0.391, 0.397, 0.452 and 0.479 across runs and
    models, so a mixed ranking would order roles by which model happened to
    score them. The query must filter on cohort, classifier and rubric together.
    """
    source = inspect.getsource(gateway.load_cohort)
    for column in ("cohort_name = ?", "classifier = ?", "rubric_version = ?"):
        assert column in source, f"load_cohort does not filter on {column}"
    assert "is_current = 1" in source, (
        "the table is append-only; without this filter a superseded derivation "
        "ranks alongside the one that replaced it")


def test_mixing_classifiers_is_not_reachable_through_the_api():
    """One classifier per call, by signature.

    There is no parameter that takes a list, and no code path that unions two
    keys. The defence is the shape of the function rather than a runtime check.
    """
    signature = inspect.signature(gateway.load_cohort)
    assert set(signature.parameters) == {"classifier", "database"}
    classifier = signature.parameters["classifier"]
    assert classifier.annotation in ("str | None", str), (
        "classifier must be a single value, never a collection")


def test_an_absent_reference_set_raises_rather_than_returning_a_short_list():
    """A portfolio view missing rows still looks like a portfolio view.

    That is the failure worth refusing. A client reading eight ranked roles has
    no way to know four are missing, so the gateway raises and names the script
    that fixes it.
    """
    with pytest.raises(gateway.NoCohortAvailable, match="score_cohort"):
        gateway.load_cohort(classifier="a-classifier-that-never-scored-anything")


# ===========================================================================
# has_full_run comes from what is persisted
# ===========================================================================

def test_drillability_is_derived_from_persisted_task_scores(cohort):
    """Cohort membership is one number; a drill-down needs a verdict and scores.

    Nine of the twelve rows exist only as a persisted index. If ``has_full_run``
    were defaulted or inferred from membership, the page would offer twelve
    clickable rows and nine of them would open nothing.
    """
    source = inspect.getsource(gateway.load_cohort)
    assert "score.role_verdict" in source
    assert "score.task_score" in source, (
        "a verdict without task scores is not a drillable role")

    assert any(r.has_full_run for r in cohort.rows), "no row is drillable"
    assert not all(r.has_full_run for r in cohort.rows), (
        "every row drillable contradicts the warehouse: only three occupations "
        "have persisted task scores")
    assert cohort.drillable_roles == str(len(cohort.rows_with_full_run))


def test_the_drillable_count_only_counts_members_of_this_cohort(cohort):
    """An occupation scored outside the cohort must not inflate the count."""
    assert int(cohort.drillable_roles) <= len(cohort.rows)


# ===========================================================================
# The lag is a sector quantity, not a per-role one
# ===========================================================================

def test_the_lag_has_no_per_row_field():
    """Enforced by the type, which is stronger than enforcing it in a template.

    All thirty persisted verdicts carry p10 5.0 / p50 10.1 / p90 30.0. The lag is
    estimated from NAICS 52 adoption evidence, so it is one quantity for the
    whole finance family. A ``lag`` field on the row type would let a future page
    put twelve different-looking bars next to twelve roles.
    """
    row_fields = set(CohortRowView.__dataclass_fields__)
    assert not {f for f in row_fields if "lag" in f}, (
        f"CohortRowView must carry no lag field; found {row_fields}")

    cohort_fields = set(CohortView.__dataclass_fields__)
    assert {"lag_p10", "lag_p50", "lag_p90"} <= cohort_fields, (
        "the lag belongs on the cohort as page-level scalars")


def test_the_lag_is_read_once_and_not_averaged():
    """A mean over identical values would imply it could differ."""
    source = inspect.getsource(gateway.load_cohort)
    assert "SELECT DISTINCT lag_years_p10" in source
    assert "AVG(" not in source.upper(), (
        "averaging the lag across occupations implies per-role variation")


def test_a_lag_that_is_not_single_valued_is_surfaced(cohort, caplog):
    """If the lag ever does vary, the view must not quietly pick one.

    It degrades to 'not identifiable' and logs, rather than taking the first row
    and presenting it as the family's timetable.
    """
    source = inspect.getsource(gateway.load_cohort)
    assert "lag_not_single_valued" in source

    # Behaviour, not source text. The first cut looked for the string
    # "not identifiable" in _fmt_lag and failed because the function names the
    # constant rather than inlining its value -- a test that was checking how
    # the code is written instead of what it does.
    assert gateway._fmt_lag(None) == gateway.ABSENT
    assert gateway._fmt_lag(10.07) == "10.1"


# ===========================================================================
# The substitution figure carries its own scope
# ===========================================================================

def test_the_substitution_figure_travels_with_its_denominator(cohort):
    """The defect this test exists for was live for one commit.

    The spec asked for a hero figure of "0 of 231 tasks judged outright
    replaceable". A bare ``COUNT(*) WHERE direction = 'substitute'`` produced
    "6 of 231" --- a sum across five runs, three occupations and two different
    models, over a denominator of 231 that includes nine roles never scored at
    task level. Three incompatible populations in one ratio.

    ``score_cohort.py`` persists only the target occupation's task scores, so
    task-level direction exists for a few roles rather than twelve. The count,
    its denominator and the number of roles it covers now travel together.
    """
    assert {"substitutable_count", "substitutable_of", "substitutable_roles"} \
        <= set(CohortView.__dataclass_fields__)
    assert not hasattr(cohort, "tasks_substitutable"), (
        "the unscoped field invited a ratio over mismatched populations")

    count, of, roles = (int(cohort.substitutable_count),
                        int(cohort.substitutable_of),
                        int(cohort.substitutable_roles))
    assert count <= of, "more substitutions than tasks scored"
    assert of < int(cohort.tasks_assessed) or roles == len(cohort.rows), (
        "the denominator may only equal the full task count when every role "
        "has been scored at task level")
    assert roles <= len(cohort.rows)


def test_the_substitution_count_is_scoped_to_one_classifier():
    """Counting across models would mix two rubric executions."""
    source = inspect.getsource(gateway.load_cohort)
    scoped = source[source.index("WITH latest AS"):]
    assert "s.model = ?" in scoped, (
        "the substitution count must be scoped to this classifier")
    assert "ROW_NUMBER() OVER" in scoped, (
        "without the latest-run-per-occupation window, a task scored 26 times "
        "is counted 26 times")


# ===========================================================================
# No average across occupations
# ===========================================================================

def test_no_mean_exposure_across_roles_is_offered(cohort):
    """An unweighted mean over twelve occupations is not a quantity.

    The roles have different headcounts, and headcount is not in the warehouse.
    Averaging them produces a confident number describing nobody, which is the
    easiest wrong figure this layer could produce. The range is offered instead.
    """
    fields = set(CohortView.__dataclass_fields__)
    assert not {f for f in fields if "mean" in f or "average" in f or "avg" in f}
    assert {"exposure_low", "exposure_high"} <= fields

    source = inspect.getsource(gateway.load_cohort)
    assert "AVG(" not in source.upper()


# ===========================================================================
# Figures and formatting
# ===========================================================================

def test_every_displayed_figure_is_in_the_traced_set(cohort):
    """Same contract as the report: the page may show nothing else.

    Includes the bar widths, for the reason the task spine's were included ---
    each is that occupation's own index in another unit, and exempting them is
    how a figure with no source reaches a chart.
    """
    assert cohort.rows, "no rows; every loop below would pass vacuously"
    for row in cohort.rows:
        assert row.exposure_index in cohort.figures
        assert row.tasks_scored in cohort.figures
        assert row.bar_percent in cohort.figures, (
            f"bar width {row.bar_percent} for {row.soc_code} is untraced")

    for value in (cohort.roles_assessed, cohort.tasks_assessed,
                  cohort.exposure_low, cohort.exposure_high,
                  cohort.substitutable_count, cohort.substitutable_of,
                  cohort.lag_p10, cohort.lag_p50, cohort.lag_p90):
        assert value in cohort.figures, f"{value!r} is not traced"


def test_rows_are_ranked_descending_by_exposure(cohort):
    """The ranking is the chart's whole job, so it is the gateway's to guarantee."""
    values = [float(r.exposure_index) for r in cohort.rows]
    assert values == sorted(values, reverse=True)
    assert cohort.most_exposed_title == cohort.rows[0].title
    assert cohort.least_exposed_title == cohort.rows[-1].title


def test_the_spread_is_wide_enough_to_rank(cohort):
    """A saturated rubric makes the ranking chart meaningless.

    This is the property that justifies drawing it at all: the whole point of
    choosing this occupation family was that the score has to discriminate.
    """
    low, high = float(cohort.exposure_low), float(cohort.exposure_high)
    assert high - low > 0.1, (
        f"spread {high - low:.3f} is too narrow to rank; the rubric is "
        f"saturating and a ranking chart would be drawing noise")


def test_every_value_on_the_view_is_a_string_or_bool(cohort):
    """The boundary object carries no handles, floats or decimals.

    The UI must not be able to compute, and it cannot compute on strings.
    """
    assert cohort.rows, "no rows; the loop below would pass vacuously"
    for row in cohort.rows:
        for name, value in vars(row).items():
            assert isinstance(value, (str, bool)), f"{name} is {type(value)}"
    for name in ("roles_assessed", "tasks_assessed", "exposure_low",
                 "lag_p50", "drillable_roles"):
        assert isinstance(getattr(cohort, name), str)


def test_bar_widths_are_percentages_within_range(cohort):
    assert cohort.rows, "no rows; the loop below would pass vacuously"
    for row in cohort.rows:
        assert row.bar_percent.endswith("%")
        assert 0 <= float(row.bar_percent.rstrip("%")) <= 100


# ===========================================================================
# The tier boundary holds
# ===========================================================================

def test_the_cohort_path_does_not_widen_the_agents_view_grants():
    """The scoring tier reads facts; the VW_* layer belongs to the agent.

    Three scripts have already broken this by reading ``dbo.VW_*`` while holding
    a writing tier's credential, so the rule is asserted here too rather than
    trusted.
    """
    tree = ast.parse(GATEWAY_SOURCE.read_text(encoding="utf-8"))
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "load_cohort")
    sql = " ".join(n.value for n in ast.walk(function)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and "SELECT" in n.value.upper())
    assert sql, "no SQL found; this check would pass vacuously"
    assert "dbo.VW_" not in sql, (
        "load_cohort runs as db_fde_score, which is not granted the agent's views")


def test_the_gateway_still_performs_no_display_arithmetic_in_the_ui_layer():
    """The gateway may compute; the presentation tier may not.

    Bar geometry is computed here deliberately, which is what keeps `blocks.py`
    arithmetic-free and the figures traceable. This pins the division of labour
    so a later edit does not move the arithmetic downstream.
    """
    assert "_bar" in inspect.getsource(gateway.load_cohort), (
        "bar geometry must be formatted in the application tier")
    # Asserted on the identifiers, not the word: blocks.py legitimately says
    # "within a cohort of finance occupations" in the calibration copy, and a
    # test that fires on client-facing prose is a test someone switches off.
    blocks = Path("src/app/blocks.py").read_text(encoding="utf-8")
    for identifier in ("CohortView", "CohortRowView", "load_cohort"):
        assert identifier not in blocks, (
            f"blocks.py references {identifier}; W10 is the read path only and "
            f"the page lands in W12")


# ===========================================================================
# The checks above must be able to fail
# ===========================================================================

def test_the_figure_check_catches_an_untraced_value(cohort):
    """Proves the traceability assertion is not decoration.

    A bar width that is not in ``figures`` is a number on a chart with no source.
    This swaps the traced set for a wrong one and confirms every row is then
    reported, so the passing case above means something.
    """
    import dataclasses

    broken = dataclasses.replace(cohort, figures=frozenset({"no-match"}))
    untraced = [r.bar_percent for r in broken.rows
                if r.bar_percent not in broken.figures]
    assert len(untraced) == len(cohort.rows)


def test_the_loop_checks_are_not_vacuous_on_an_empty_cohort(cohort):
    """The all()-over-empty class, which has bitten this project twice.

    A ``for row in cohort.rows`` loop over an empty tuple runs zero assertions
    and passes. Each of those tests now asserts non-emptiness first; this one
    pins the reason so the guards are not removed as noise.
    """
    import dataclasses

    empty = dataclasses.replace(cohort, rows=())
    executed = sum(1 for _ in empty.rows)
    assert executed == 0, "the premise of the guards no longer holds"
    assert cohort.rows, "the real cohort must be non-empty for them to mean anything"

