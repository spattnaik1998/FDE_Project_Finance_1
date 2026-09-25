"""Front matter is not evidence.

Two of the 21 claims reaching the customer-facing provenance appendix were a
dedication line and a JEL code block. Both passed every filter the extractor
had -- the right length, the topic term present, reading as prose -- because
none of those filters was about front matter. The dedication matched
``intangible_complement`` for containing the word "intangibles".

A filter like this is only as good as its false-positive behaviour, so every
pattern is tested in both directions: it must reject the front matter that
actually appeared, and it must keep the claims the analysis depends on.
"""

from __future__ import annotations

import pytest

from documents.adapters.pdf import (CLAIM_EXTRACTOR_VERSION,
                                    FRONT_MATTER_PATTERNS,
                                    front_matter_reason)

# The two that actually reached a customer-facing document, verbatim.
OBSERVED_JUNK = [
    ("dedication",
     "We dedicate this paper to the memory of Shinkyu Yang, whose pioneering "
     "insights on the role of intangibles inspired us."),
    ("jel_codes",
     "D2,E01,E22,O3 ABSTRACT General purpose technologies (GPTs) such as AI "
     "enable and require significant complementary investments."),
]

OTHER_FRONT_MATTER = [
    ("series_header",
     "NBER WORKING PAPER SERIES Occupational exposure to artificial intelligence."),
    ("acknowledgement",
     "We gratefully acknowledge financial support from the Sloan Foundation."),
    ("acknowledgement",
     "We are grateful to seminar participants for helpful comments."),
    ("dedication",
     "This paper is dedicated to the memory of our colleague."),
]

# Claims the analysis actually rests on. If the filter rejects any of these it
# has traded a cosmetic problem for a substantive one.
MUST_SURVIVE = [
    "We find substantial and ongoing Productivity J-Curve effects for software "
    "in particular and computer hardware to a lesser extent.",
    "Our model generates a Productivity J-Curve that can explain the "
    "productivity slowdowns often accompanying the advent of GPTs.",
    "The implementation lag for a general purpose technology runs to years, "
    "not months, and the payoff arrives later still.",
    "We do not make predictions about the adoption timeline of these "
    "capabilities or their effect on employment.",
    "These complementary investments are often intangible and poorly measured "
    "in the national accounts.",
    "Around 80% of the U.S. workforce could have at least 10% of their work "
    "tasks affected by the introduction of large language models.",
    "We define exposure as a proxy for potential economic impact without "
    "distinguishing between labour-augmenting and labour-displacing effects.",
    "Accordingly, after an implementation lag period, AI might raise measured "
    "productivity growth.",
]


@pytest.mark.parametrize("expected,sentence", OBSERVED_JUNK)
def test_the_front_matter_that_reached_a_customer_is_rejected(expected, sentence):
    """Regression test on the exact text a client would have read."""
    assert front_matter_reason(sentence) == expected


@pytest.mark.parametrize("expected,sentence", OTHER_FRONT_MATTER)
def test_other_front_matter_is_rejected(expected, sentence):
    assert front_matter_reason(sentence) == expected


@pytest.mark.parametrize("sentence", MUST_SURVIVE)
def test_a_real_claim_survives_every_pattern(sentence):
    """The direction that matters more.

    A filter that quietly drops evidence is worse than one that lets a
    dedication through: the dedication is visibly silly, a missing claim is
    invisible.
    """
    reason = front_matter_reason(sentence)
    assert reason is None, (
        f"pattern {reason!r} rejected a substantive claim: {sentence[:70]}")


def test_the_rejection_names_its_reason():
    """A filter that drops text without saying why cannot be audited."""
    reason = front_matter_reason(OBSERVED_JUNK[0][1])
    assert isinstance(reason, str) and reason
    assert front_matter_reason("Ordinary prose about exposure and lag.") is None


def test_every_pattern_carries_a_reason_label():
    for pattern, reason in FRONT_MATTER_PATTERNS:
        assert reason and isinstance(reason, str)
        assert pattern.pattern, "an empty pattern would match nothing silently"


def test_no_pattern_matches_ordinary_prose():
    """Each pattern individually must leave normal sentences alone."""
    benign = ("The exposure index is 0.384 under equal weighting across 26 "
              "tasks, and the adoption lag spans five to thirty years.")
    for pattern, reason in FRONT_MATTER_PATTERNS:
        assert not pattern.search(benign), (
            f"pattern {reason!r} fires on ordinary prose")


def test_the_extractor_version_is_part_of_claim_identity():
    """Correcting the extractor must not collide with the old derivation.

    Without the version in claim_id, a re-derivation produces rows whose primary
    key says "same claim" while the quote says otherwise.
    """
    assert CLAIM_EXTRACTOR_VERSION
    from documents.adapters import pdf
    import inspect

    source = inspect.getsource(pdf.find_claims)
    assert "CLAIM_EXTRACTOR_VERSION" in source, (
        "claim_id must carry the extractor version")
