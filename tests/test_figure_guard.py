"""The fabrication guard: no figure the evidence does not support.

This is the test the whole provenance chain exists for. Everything upstream —
SHA-256 digests, the foreign key to `ref.source_document`, quote-plus-page
extraction, the run-source binding — is in service of one customer-facing
promise: no number in the output was invented. This is where that promise is
mechanically checked.

The guard has to be calibrated in both directions. Too loose and a fluent
report with one invented percentage sails through. Too tight and it fires on
"one of three caveats", gets switched off, and catches nothing.
"""

from __future__ import annotations

import pytest

from nodes import figure_guard
from scoring.schemas import (
    CalibrationOutcome,
    CalibrationResult,
    Confidence,
    Direction,
    LagInterval,
    RoleVerdict,
    TaskScore,
    WeightingBound,
)


@pytest.fixture
def verdict():
    return RoleVerdict(
        soc_code="13-2051.00",
        exposure_index=0.541,
        primary_weighting=WeightingBound(weight_source="equal", lower=0.541,
                                         upper=0.541, note="Equal weighting."),
        sensitivity_weighting=WeightingBound(weight_source="adjacent_soc",
                                             lower=0.498, upper=0.584,
                                             note="Bound."),
        lag=LagInterval(p10=5.0, p50=10.07, p90=30.0, basis="Observed 29.9% to 36.5%.",
                        observation_window_years=0.88),
        augmentation_share=0.0,
        unclear_share=1.0,
        calibration=CalibrationResult(
            benchmark_measure="AIOE_language_modeling",
            benchmark_percentile=86.82, our_percentile=None, delta=None,
            within_tolerance=False,
            outcome=CalibrationOutcome.REVIEW_REQUIRED,
            explanation="Not identifiable from one occupation."),
        caveats=["Adoption evidence is NAICS 52 while the cost line is 523."])


@pytest.fixture
def scores():
    return [
        TaskScore(task_id="t1", source_doc_id="d1", exposure_raw=0.90,
                  tacitness_penalty=0.0, exposure_adjusted=0.90,
                  direction=Direction.UNCLEAR, confidence=Confidence.LOW,
                  rationale="r"),
        TaskScore(task_id="t2", source_doc_id="d1", exposure_raw=0.90,
                  tacitness_penalty=0.55, exposure_adjusted=0.405,
                  direction=Direction.UNCLEAR, confidence=Confidence.LOW,
                  rationale="r"),
    ]


@pytest.fixture
def claims():
    return [{"Claim_ID": "eloundou:not_prediction:1:0", "Page": 1,
             "Publisher": "arXiv",
             "Quote": "We do not make predictions about the adoption timeline."}]


# ===========================================================================
# It catches fabrication
# ===========================================================================

def test_an_invented_percentage_is_caught(verdict, scores):
    narrative = ("Roughly 42.7% of analyst work is exposed, on our reading.")
    report = figure_guard.check(narrative, verdict, scores)
    assert not report.clean
    assert any(f.literal.startswith("42.7") for f in report.fabrications)


def test_an_invented_dollar_figure_is_caught(verdict, scores):
    narrative = "This implies a saving of 850000 dollars per desk."
    report = figure_guard.check(narrative, verdict, scores)
    assert not report.clean


def test_an_invented_year_is_caught(verdict, scores):
    """A model reaching for a plausible-sounding date."""
    narrative = "Electrification took until 1935 to show up in productivity."
    report = figure_guard.check(narrative, verdict, scores)
    assert not report.clean
    assert any("1935" in f.literal for f in report.fabrications)


def test_an_invented_task_count_is_caught(verdict, scores):
    narrative = "We scored 147 distinct tasks for this occupation."
    report = figure_guard.check(narrative, verdict, scores)
    assert not report.clean


def test_the_report_names_the_offending_figure_with_context(verdict, scores):
    narrative = "Exposure sits at 0.541, and adoption will reach 88.4% by then."
    report = figure_guard.check(narrative, verdict, scores)
    assert not report.clean
    fabrication = report.fabrications[0]
    assert "88.4" in fabrication.literal
    assert "adoption" in fabrication.context
    assert "88.4" in report.message()


def test_multiple_fabrications_are_all_reported(verdict, scores):
    narrative = "Exposure is 0.77, the lag is 3.5 years, and 61.2% of firms agree."
    report = figure_guard.check(narrative, verdict, scores)
    assert len(report.fabrications) >= 3


# ===========================================================================
# It does not fire on legitimate prose
# ===========================================================================

def test_figures_drawn_from_the_verdict_pass(verdict, scores):
    narrative = ("The exposure index is 0.541 under equal weighting, with a "
                 "sensitivity bound of 0.498 to 0.584. The adoption lag runs "
                 "from 5.0 to 30.0 years, with a median of 10.07.")
    report = figure_guard.check(narrative, verdict, scores)
    assert report.clean, report.message()


def test_figures_drawn_from_task_scores_pass(verdict, scores):
    narrative = "The most exposed task scores 0.9; the least scores 0.405."
    assert figure_guard.check(narrative, verdict, scores).clean


def test_a_share_written_as_a_percentage_passes(verdict, scores):
    """1.0 stored as a share should be citable as 100%."""
    narrative = "All of the tasks, 100%, were carried forward as unclear."
    assert figure_guard.check(narrative, verdict, scores).clean


def test_rounding_within_tolerance_passes(verdict, scores):
    """A writer rounding 0.541 to 0.54 is rounding, not inventing."""
    narrative = "Exposure is approximately 0.54."
    assert figure_guard.check(narrative, verdict, scores).clean


def test_structural_small_integers_pass(verdict, scores):
    """A guard that fires on 'the three caveats' would be switched off."""
    narrative = ("There are 3 findings and 2 open questions. See section 1 for "
                 "the first of 4 caveats.")
    assert figure_guard.check(narrative, verdict, scores).clean


def test_figures_from_evidence_rows_pass(verdict, scores):
    """The adoption trajectory is legitimate material to quote."""
    adoption = [{"Period_Label": "202618", "Value": 36.5, "Source_Doc_ID": "d1"},
                {"Period_Label": "202524", "Value": 29.9, "Source_Doc_ID": "d1"}]
    narrative = "Finance AI use moved from 29.9% to 36.5% across the window."
    assert figure_guard.check(narrative, verdict, scores, adoption).clean


def test_a_benchmark_percentile_from_evidence_passes(verdict, scores):
    narrative = "The published benchmark places the occupation at 86.82."
    assert figure_guard.check(narrative, verdict, scores).clean


def test_prose_with_no_numbers_is_clean(verdict, scores):
    report = figure_guard.check("Exposure is high but the timetable is long.",
                                verdict, scores)
    assert report.clean
    assert report.checked == 0


# ===========================================================================
# Number extraction
# ===========================================================================

@pytest.mark.parametrize("text,expected", [
    ("0.541", 0.541),
    ("36.5%", 36.5),
    ("1,234", 1234.0),
    ("30", 30.0),
])
def test_numbers_are_extracted(text, expected):
    values = [v for _literal, v in figure_guard._numbers_in(text)]
    assert expected in values


def test_a_percentage_also_admits_its_share_form():
    values = [v for _l, v in figure_guard._numbers_in("36.5%")]
    assert 36.5 in values and pytest.approx(0.365) in values


@pytest.mark.parametrize("text", ["provisional_v1", "exposure_v1",
                                  "VW_ROLE_TASKS", "lag_v1_no_fit"])
def test_digits_inside_word_identifiers_are_not_quantitative_claims(text):
    """A version identifier is not a figure a customer could act on.

    The guard ignores a digit preceded by a word character, so 'provisional_v1'
    contributes nothing. Treating it as the figure 1 would add noise to the
    allow-set and let a stray '1' through elsewhere.
    """
    assert figure_guard._numbers_in(text) == []


@pytest.mark.parametrize("name,digits", [("gpt-6-astra", [6.0]),
                                         ("claude-opus-5", [5.0])])
def test_hyphenated_model_names_contribute_only_structural_integers(name, digits):
    """A hyphen is not a word character, so the digit is extracted.

    Left as-is deliberately. Every such digit is small enough to fall inside
    the structural allowance, so it cannot cause a false fabrication report,
    and tightening the pattern to exclude identifier hyphens would also exclude
    legitimate forms like 'NAICS-52'. Narrow the guard only where it changes an
    outcome.
    """
    assert [v for _l, v in figure_guard._numbers_in(name)] == digits
    assert all(d <= figure_guard.STRUCTURAL_MAX for d in digits)


def test_a_decimal_is_read_as_one_number_not_two():
    values = [v for _l, v in figure_guard._numbers_in("the index is 0.541 today")]
    assert 0.541 in values
    assert 541.0 not in values


# ===========================================================================
# The allow-set
# ===========================================================================

def test_allow_set_reaches_into_nested_structures():
    allowed = figure_guard.build_allow_set(
        {"a": [{"b": 12.34}], "c": ("x", {"d": 99})})
    assert 12.34 in allowed
    assert 99.0 in allowed


def test_allow_set_reads_pydantic_models(verdict):
    allowed = figure_guard.build_allow_set(verdict)
    assert 0.541 in allowed
    assert 30.0 in allowed
    assert 86.82 in allowed


def test_allow_set_harvests_numbers_out_of_prose_fields(verdict):
    """The lag basis carries the observed trajectory in its text."""
    allowed = figure_guard.build_allow_set(verdict)
    assert 29.9 in allowed and 36.5 in allowed


def test_booleans_are_not_harvested_as_numbers():
    """True would otherwise admit the figure 1."""
    allowed = figure_guard.build_allow_set({"curve_fitted": False,
                                            "deliverable": True})
    assert allowed == set() or 1.0 not in (allowed - {0.0})


# ===========================================================================
# Citations
# ===========================================================================

def test_a_supported_citation_is_recognised(claims):
    supported, invented = figure_guard.citations_in(
        "As stated [eloundou:not_prediction:1:0], no timeline is forecast.",
        {c["Claim_ID"] for c in claims})
    assert supported == {"eloundou:not_prediction:1:0"}
    assert not invented


def test_an_invented_citation_is_caught(claims):
    supported, invented = figure_guard.citations_in(
        "As shown in [smith:made_up:9:0].",
        {c["Claim_ID"] for c in claims})
    assert invented == {"smith:made_up:9:0"}
    assert not supported


def test_prose_without_citations_yields_nothing(claims):
    supported, invented = figure_guard.citations_in(
        "No citation here.", {c["Claim_ID"] for c in claims})
    assert not supported and not invented
