"""Every client-facing sentence, written for the person making the decision.

The previous copy was a methods appendix. It said "Acemoglu–Autor cell score",
"Polanyi penalty", "p10 / median / p90", "rank correlation -0.245" and
"unidentifiable comparison". All of those are accurate and none of them is
readable by a research director deciding next year's headcount. The charter asks
for a prototype a non-engineer stakeholder can reason about, and jargon on the
front page fails that test no matter how sound the arithmetic behind it.

Three rules, applied throughout:

**Every section heading is the question the reader actually has.** Not "Exposure"
but "How much of this job could software already do?" A heading that names the
metric assumes the reader knows why the metric matters.

**The answer comes before the method.** One sentence a reader can repeat in a
meeting, then the caveat that stops them over-reading it, then the workings
behind a disclosure. Someone who wants the rubric can open it; nobody has to
read it to get the point.

**Say what the number is not.** The most expensive misreading of this analysis is
"38% of these jobs disappear". Exposure is technical possibility, not a
forecast, and the copy says so next to the figure rather than in a footnote.

Numbers in these sentences are interpolated from the view model, which carries
only figures the report's registry traced to a hashed source. Prose here cannot
introduce a quantity of its own.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Headings: the reader's question, not the metric's name
# ---------------------------------------------------------------------------

HEADINGS = {
    "standing": "How much weight can you put on this?",
    "exposure": "How much of this job could software already do?",
    "lag": "How long before it actually changes the cost line?",
    "calibration": "Did an independent source agree?",
    "direction": "Does this replace people or make them faster?",
    "tasks": "Which parts of the job, specifically",
    "limits": "Where this analysis stops being reliable",
    "provenance": "Where every number came from",
}

# ---------------------------------------------------------------------------
# Standing: what the reader should do about the result
# ---------------------------------------------------------------------------
#
# Keyed by persisted status. The tag is what a reader sees first, so it states a
# usability verdict rather than a pipeline state: "review_required" means nothing
# to someone outside this system.

STANDING = {
    "passed": (
        "Checked and consistent",
        "An independent published source agrees with this estimate. You can use "
        "the figures below as they stand."),
    "review_required": (
        "Independent check inconclusive",
        "The figures below are our own estimate. We tried to confirm them "
        "against published research and the comparison could not settle it, so "
        "treat the headline number as a considered estimate rather than an "
        "externally verified one. The task-by-task reasoning and the timetable "
        "are unaffected."),
    "gate_rejected": (
        "Not fit to use",
        "This run failed its own quality checks. The figures are kept for "
        "diagnosis and should not inform a decision."),
    "failed": (
        "Incomplete",
        "The analysis did not finish, so anything shown may be partial."),
}

# The specific reason calibration could not settle it, in business terms. This is
# the sentence that most needed rewriting: the original talked about ranks within
# distributions, which is the mechanism, not the consequence.
WHY_INCONCLUSIVE = (
    "We compare our estimate against a published academic index of AI exposure, "
    "by Felten, Raj and Seamans. That index was built to separate very "
    "different occupations across the whole economy — a software engineer from a "
    "lorry driver. Inside a single family of finance roles it barely varies, so "
    "it cannot tell us whether we have ranked *these twelve finance jobs* "
    "correctly relative to each other. That is a limitation of the available "
    "benchmark, not a sign the estimate is wrong — and it is why we show it as "
    "unconfirmed rather than quietly presenting it as validated."
)

# The other way the check can fail to settle: not an under-powered benchmark but
# no comparison at all, because a single scored occupation has no rank.
WHY_UNIDENTIFIABLE = (
    "Confirming the estimate means asking whether we rank this role the same "
    "way published research does. Ranking needs something to rank against, and "
    "this run covered one role on its own, so there was no comparison to make — "
    "not a disagreement, an absence. Assessing several roles together resolves "
    "it, and the figures below do not depend on it."
)


def exposure_answer(view) -> str:
    """One sentence a reader can repeat, then the misreading it prevents."""
    return (
        f"The exposed work is drafting, summarising, pulling and formatting "
        f"data, and routine valuation — **{view.exposure_share_text} of the "
        f"role's published tasks**. What is left is the part that depends on "
        f"reading a management team, judging which number in a filing matters, "
        f"and being in the room.")


EXPOSURE_NOT = (
    "This is not a forecast that those jobs disappear, and it is not a "
    "timetable. It measures what the technology can do, not what firms will "
    "choose to do with it, and the same capability can just as easily make an "
    "analyst faster. When it lands, and which way it cuts, are the next two "
    "sections."
)


def lag_answer(view) -> str:
    return (
        f"Most likely **around {view.lag_p50} years**, and realistically "
        f"anywhere between **{view.lag_p10} and {view.lag_p90}**.")


LAG_WHY = (
    "The gap is not about how good the technology is. It is how long firms take "
    "to reorganise around it — new processes, new roles, new controls. When "
    "factories electrified, the machines arrived decades before the productivity "
    "did, because the gain came from redesigning the factory floor rather than "
    "from the motor. We deliberately give a wide range rather than a single date: "
    "the observable evidence covers less than a year of the current wave, which "
    "is not enough to justify a precise answer."
)


def direction_answer(view) -> str:
    total = view.tasks_scored
    if view.direction_substitute == "0" and view.direction_augment != "0":
        return (
            f"**Makes people faster, on the evidence so far.** Of "
            f"{total} tasks examined, {view.direction_augment} look like work "
            f"AI would assist rather than take over, and **none** looked like "
            f"outright replacement. The remaining {view.direction_unclear} were "
            f"genuinely ambiguous and we have left them that way rather than "
            f"forcing a call.")
    return (
        f"Of {total} tasks examined: {view.direction_augment} where AI would "
        f"assist the person, {view.direction_substitute} where it could replace "
        f"the task, and {view.direction_unclear} too ambiguous to call.")


DIRECTION_WHY = (
    "Which one happens is a management decision, not a property of the "
    "technology. It is worth noting that among finance firms that have actually "
    "adopted AI, far more reported their workforce becoming more skilled than "
    "reported it shrinking."
)

TASKS_INTRO = (
    "Each task is scored on two things: how routine and rule-based it is, and "
    "how much it depends on judgement that nobody can write down. Routine work "
    "scores high. Work that rests on tacit judgement — reading a management "
    "team, knowing which number in a filing is the one that matters — is "
    "discounted, because software cannot be given a rule that was never "
    "written."
)

TASK_COLUMNS = {
    "statement": "Task",
    "raw": "Routine",
    "tacit": "Judgement discount",
    "adjusted": "Net exposure",
    "direction": "Effect",
    "confidence": "Confidence",
}

LIMITS_INTRO = (
    "These are properties of the available public data, not defects in the "
    "analysis. They are listed because anyone acting on the figures should know "
    "where they stop being load-bearing."
)

PROVENANCE_INTRO = (
    "Every figure above traces back to a specific published file, identified by "
    "a cryptographic fingerprint. Nothing here was estimated by a language model "
    "and left unsourced — if a number could not be traced to a source this run "
    "actually read, it is not shown at all."
)


def provenance_summary(view) -> str:
    return (
        f"**{view.trace_figures} figures** on this page, every one traced to a "
        f"source file below.")


# ---------------------------------------------------------------------------
# The request form
# ---------------------------------------------------------------------------

FORM_HEADING = "Ask about another role"
FORM_INTRO = (
    "Describe the role in your own words. If we do not hold the task data to "
    "answer properly, you get told so — not an answer about a role that merely "
    "looks similar."
)
FORM_LABEL = "Which role should we assess?"
FORM_SUBMIT = "Run the analysis"
FORM_CONFIRM = "I understand this runs a live analysis"
FORM_CONFIRM_PROMPT = (
    "Tick the box first. A button that quietly spends money is not one to trust."
)

COVERAGE_INTRO = (
    "These are the roles we hold published task data for. Anything else is "
    "refused rather than approximated, and a refusal costs a run."
)


def form_cost(cost) -> str:
    """Stated beside the button, not inside a disclosure.

    Cost is decision information, and the decision is made at the button. Two
    sentences: what it costs, and the reassurance that makes the cost bearable
    --- the result is saved, so nobody pays twice to look at it again.
    """
    return (f"One run takes {cost.duration_text} and queries AI models about "
            f"{cost.calls} times. The result is saved, so you can come back to "
            f"it without paying for it twice.")


REFUSAL_HEADING = "We cannot answer that one yet"

# ---------------------------------------------------------------------------
# Method text: behind a disclosure, in the reader's terms where it can be
# ---------------------------------------------------------------------------
#
# None of this is removed. It moves one level down, because a reader who wants
# to know whether to trust the number asks a different question from a reader
# who wants to know what the number is, and the page should answer the second
# one first.

METHOD_LABEL = "How this was worked out"

EXPOSURE_METHOD = (
    "We take the role's published task list and ask, task by task, how much of "
    "it is rule-following work a language model can already do, then subtract "
    "the part that depends on judgement nobody has written down. The share "
    "above is the average across every task, weighting them equally.\n\n"
    "It deliberately says nothing about timing. The timetable in the next "
    "section is computed on a separate path that cannot see this number, so a "
    "high share here cannot quietly pull the timetable forward."
)

LAG_METHOD = (
    "We do not fit a curve. There is under a year of observable data on how "
    "fast finance firms are actually adopting these tools, which is not enough "
    "to project a saturation point — drawing a smooth S-curve through it would "
    "manufacture precision the evidence cannot support. Instead we report the "
    "observed trajectory alongside the historical range for comparable "
    "technology shifts, and give a wide interval on purpose."
)

# The three calibration figures are percentile ranks, and the labels have to say
# so. "Our estimate ranks at 4.17" gives a reader a number with no unit and no
# scale; a percentile within a named cohort of twelve is a statement they can
# check against their own intuition.
CALIBRATION_LABELS = {
    "ours": "Our percentile rank",
    "benchmark": "Benchmark's percentile rank",
    "delta": "Gap, in percentile points",
}

CALIBRATION_SCALE = (
    "Both ranks are percentiles within the same twelve finance occupations, so "
    "0 is the least exposed of the twelve and 100 the most. Ranking our score "
    "against a population we did not assess would not be a comparison."
)

CALIBRATION_ANSWER_YES = (
    "Yes — our ranking of this role agrees with the published index closely "
    "enough to pass the check."
)


def calibration_answer_inconclusive(view) -> str:
    return (
        "Not conclusively. We rank this role against eleven neighbouring "
        "finance roles and compare that ranking to a published academic index. "
        f"That index places the role at the {view.benchmark_percentile} "
        f"position and our own estimate places it at {view.our_percentile}, "
        "but the index barely distinguishes between finance roles at all, so "
        "the disagreement tells us little either way. Treat the figures as a "
        "considered estimate, not an externally confirmed one.")


CALIBRATION_NOT_IDENTIFIABLE = (
    "There was nothing to compare against. Confirming a ranking requires "
    "several roles; this run covered one."
)

TASKS_METHOD = (
    "**Routine** is how rule-based and repeatable the task is — the kind of "
    "work that can be specified precisely. **Judgement discount** is how much "
    "of it rests on tacit skill: reading a management team, knowing which line "
    "in a filing actually matters. **Net exposure** is what remains after the "
    "discount, and it is that column that feeds the headline share.\n\n"
    "The discount direction matters. Work whose rules nobody can articulate is "
    "work software cannot be given, so tacit judgement lowers exposure rather "
    "than raising it."
)

PROVENANCE_METHOD = (
    "Each source listed was actually read during this run — recorded at the "
    "moment a query returned a row from it, not merely present in our "
    "database. The fingerprint identifies the exact file content, so if a "
    "publisher revises a dataset the change is visible rather than silent."
)

CLAIMS_INTRO = (
    "Where a figure rests on a sentence from a paper or a book rather than a "
    "dataset, the exact sentence and page are recorded, never a summary of it, "
    "so you can check the source says what we report it saying."
)

CLAIMS_GRANULARITY = (
    "We record which document each figure came from, not which individual "
    "sentence within it. The trace is document-level, and we say so rather "
    "than implying more precision than we have."
)


# ---------------------------------------------------------------------------
# The bottom line: the whole answer, above the fold
# ---------------------------------------------------------------------------
#
# A client demo is won or lost in the first ten seconds. Everything below this
# panel is the defence of it; this is the finding. Three lines, in the order the
# decision needs them: what, when, and which way.

BOTTOM_LINE_LABEL = "The bottom line"


def bottom_line(view) -> str:
    """The finding in one repeatable sentence.

    Conditional on the direction counts rather than asserting augmentation. The
    augmentation reading is what this run found, not a house view, and a summary
    that stated it unconditionally would keep saying it on a run that found the
    opposite -- which is the one run where the summary matters most.
    """
    if view.direction_substitute == "0" and view.direction_augment != "0":
        direction = ("On the evidence so far that shows up as **people working "
                     "faster, not fewer people** — no task in this role looked "
                     "like outright replacement.")
    else:
        direction = (f"Of those, {view.direction_substitute} tasks could be "
                     f"taken over outright and {view.direction_augment} would "
                     f"more likely be assisted.")
    return (
        f"About **{view.exposure_share_text} of this role's tasks** are already "
        f"within reach of current AI tools. {direction} Expect it to start "
        f"moving the cost line in **roughly {view.lag_p50} years**, not next "
        f"quarter.")


def bottom_line_action(view) -> str:
    if view.direction_substitute == "0" and view.direction_augment != "0":
        return (
            "**What to do with that.** Plan for the same headcount doing more, "
            "not less headcount. The near-term decision is which tasks to hand "
            "over and what review sits around them — not a reduction.")
    return (
        "**What to do with that.** The near-term decision is which tasks to "
        "hand over and what review sits around them. See the task table for "
        "which ones, and the timetable for when.")


MASTHEAD_EYEBROW = "Task exposure & adoption lag"
MASTHEAD_QUESTION = (
    "Which of our cost lines are exposed to AI substitution, and on what "
    "timetable?"
)
MASTHEAD_NOTE = (
    "How much AI could do, and how long before it shows up in the cost line, "
    "reported as two separate answers. They are worked out independently and "
    "never blended into one score, because a capability existing and a business "
    "being reorganised around it are different events years apart."
)


# ---------------------------------------------------------------------------
# Vocabulary: machine identifiers, said in English
# ---------------------------------------------------------------------------
#
# Nineteen identifiers were reaching the page --- `review_required`,
# `provisional_v2_cohort`, `felten_aioe_language_modeling`,
# `brynjolfsson_productivity_j_curve` --- in captions, in the caveat list, and as
# the "used for" and "subject" columns of the provenance tables. Every one is a
# key in our own schema. A client reads them as noise, and they are the single
# thing that made the report look machine-generated rather than written.
#
# This is a vocabulary map, not a rewrite. The underlying findings are untouched
# and the technical report still carries the identifiers verbatim, because a
# figure that a reader may need to trace back to a row should be traceable by its
# real key. What changes is which vocabulary the *page* speaks.
#
# A named phrase where the identifier deserves one, and a general fallback for
# the rest, because a bare `.replace("_", " ")` gives "Not prediction" and "J
# curve definition" --- readable, and not written.

def lag_grounding_note(view) -> str:
    return (f"The historical comparison rests on {view.lag_grounding_count} "
            f"passages from the published record. Each one is quoted in full, "
            f"with its page, at the end of this report.")


# No year and no population count in this sentence, and that is not an oversight.
# Both were in the first draft and the traceability check rejected them: a figure
# on the page has to trace to a source this run actually consumed, and a citation
# year typed into a copy string traces to nothing. The provenance table carries
# the publisher and the digest, which is where a reader should get it from.
BENCHMARK_ON_FILE = (
    "The benchmark we compare against is the AI Occupational Exposure index "
    "published by Felten, Raj and Seamans, which scores US occupations for "
    "exposure to language modelling. It is listed in the sources below."
)

USED_FOR = {
    "task_source": "The role's task list",
    "exposure_benchmark": "Independent benchmark",
    "claim_evidence": "Quoted evidence",
    "adoption_evidence": "Adoption rates",
    "industry_metric": "Industry statistics",
    "lag_evidence": "Timetable evidence",
}

CLAIM_SUBJECT = {
    "lag_length": "How long the lag runs",
    "j_curve_definition": "Why gains arrive late",
    "not_prediction": "Why no date is forecast",
    "exposure_definition": "What exposure measures",
    "exposure_share": "Share of work exposed",
    "occupation_level": "Evidence at the job level",
    "intangible_complement": "The investment that must come first",
    "btos_sector": "How fast finance is adopting",
    "productivity_paradox": "Why measured gains lag",
    "task_content": "What the work consists of",
    "tacit_knowledge": "Judgement that cannot be written down",
    "skill_bias": "Who gains and who loses",
}

# Statuses and versions. The first two are the ones a client actually sees.
STATUS_WORDS = {
    "passed": "checked and consistent",
    "review_required": "independent check inconclusive",
    "gate_rejected": "failed its own quality checks",
    "failed": "did not finish",
}

POLICY_WORDS = {
    "provisional_v1": "provisional, single-occupation",
    "provisional_v2_cohort": "provisional, compared within a finance cohort",
}


def humanise(identifier: str) -> str:
    """A snake_case key as a readable phrase. Sentence case, no underscores."""
    words = str(identifier).replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else words


def used_for(key: str) -> str:
    return USED_FOR.get(key, humanise(key))


def claim_subject(key: str) -> str:
    return CLAIM_SUBJECT.get(key, humanise(key))


def plain_status(status: str) -> str:
    return STATUS_WORDS.get(status, humanise(status))


def plain_policy(version: str) -> str:
    return POLICY_WORDS.get(version, humanise(version))


def plain_caveat(caveat: str) -> str:
    """A persisted caveat with our status vocabulary translated.

    The caveat text itself is a finding and is not rewritten --- the presentation
    tier has no business editing one. What it does is swap the status token for
    the phrase that means the same thing, so a client-facing limitation does not
    open with `review_required:`.
    """
    text = str(caveat)
    for token, phrase in STATUS_WORDS.items():
        text = text.replace(f"{token}:", f"{phrase} —")
        text = text.replace(f" {token}", f" {phrase}")
    for token, phrase in POLICY_WORDS.items():
        text = text.replace(token, phrase)
    return text

