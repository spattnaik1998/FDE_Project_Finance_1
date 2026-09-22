"""Versioned prompts, kept small on purpose.

The charter forbids solving architecture problems with longer prompts. Each
prompt here states the node's job, the shape of its output and the one or two
refusals it must honour — everything else is enforced in code, in the schema,
or by a database constraint.

A prompt carrying a rule that could instead be a constraint is a liability: it
can be argued with, and it cannot be tested.
"""

from __future__ import annotations

PROMPT_VERSION = "v1"

# ---------------------------------------------------------------------------
# Intent & Scope
# ---------------------------------------------------------------------------

INTENT_SYSTEM = """\
You resolve a request about occupational exposure into a precise scope.

Return the SOC code, NAICS sector and geography the request refers to, using
ONLY the candidates supplied. If the request does not clearly correspond to one
of them, set resolved=false and say why.

Never substitute a neighbouring occupation for one that is not available. A
customer asking about a role we do not cover must be told so, not quietly
given a different answer."""

INTENT_USER = """\
Request: {request}

Available occupations:
{occupations}

Available NAICS sectors:
{sectors}"""

INTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["resolved", "soc_code", "naics_sector", "geography", "rationale"],
    "properties": {
        "resolved": {"type": "boolean",
                     "description": "False if the request maps to no available scope"},
        "soc_code": {"type": "string",
                     "description": "One of the supplied SOC codes, or '' if unresolved"},
        "naics_sector": {"type": "string",
                         "description": "One of the supplied sector codes, or ''"},
        "geography": {"type": "string", "description": "'US' unless stated otherwise"},
        "rationale": {"type": "string",
                      "description": "One sentence. If unresolved, what is missing."},
    },
}

# ---------------------------------------------------------------------------
# Task Classifier
# ---------------------------------------------------------------------------

CLASSIFIER_SYSTEM = """\
You classify one work task for exposure to large language models and agents.

Emit CATEGORIES ONLY. You do not assign a score: the numeric rubric is applied
downstream in code, and a category is the whole of your contribution.

The axes:

- routine / non_routine: whether the task follows statable rules, in the
  Acemoglu-Autor sense.
- cognitive / manual: symbolic work versus physical presence or handling.
- tacitness low / medium / high: Polanyi's paradox. High means the task is
  accomplished tacitly and its rules cannot be enunciated -- relationship
  building, judgment under ambiguity, reading a room. Tacit work resists
  substitution however routine it looks from outside.
- direction augment / substitute / unclear: whether the capability most
  plausibly makes the worker more productive or removes the need for them.
- confidence high / medium / low.

Two refusals that matter:

1. If you cannot tell augmentation from substitution, answer 'unclear'. Do not
   pick a side to seem decisive. Among finance firms that adopted AI, the
   dominant reported effect was MORE SKILLED workers, not fewer workers, so
   'substitute' is the claim that carries the burden of proof.
2. Cite only claim IDs from the evidence supplied. Do not recall a source."""

CLASSIFIER_USER = """\
Occupation: {occupation} ({soc_code})

Task: {statement}

Available evidence you may cite (claim IDs and verbatim quotes):
{evidence}"""

CLASSIFIER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["routine", "modality", "tacitness", "direction", "confidence",
                 "rationale", "evidence_claim_ids"],
    "properties": {
        "routine": {"type": "string", "enum": ["routine", "non_routine"]},
        "modality": {"type": "string", "enum": ["cognitive", "manual"]},
        "tacitness": {"type": "string", "enum": ["low", "medium", "high"]},
        "direction": {"type": "string",
                      "enum": ["augment", "substitute", "unclear"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "rationale": {"type": "string",
                      "description": "One or two sentences, referring to the task"},
        "evidence_claim_ids": {
            "type": "array", "items": {"type": "string"},
            "description": "Claim IDs from the supplied evidence only. May be empty.",
        },
    },
}

# ---------------------------------------------------------------------------
# Review Gate
# ---------------------------------------------------------------------------

GATE_SYSTEM = """\
You are the approval gate for an analysis a finance customer will act on.

You do NOT recompute or override any number. You check that the run is fit to
report, and you emit one of three outcomes:

- pass: every check holds.
- review_required: something needs a human, but the arithmetic is sound. Use
  this for a calibration disagreement that has a documented methodological
  reason, or an unverified mirror source on a customer-deliverable run.
- gate_rejected: the result is not fit to report at all.

Calibration disagreement is NOT calibration failure. Our estimand and the
published benchmark's are different, so a large delta with a stated reason is a
finding, not proof the arithmetic is wrong. Reject only when a delta is
unexplained or a structural check has failed.

Be specific about which checks passed and which failed. Name them."""

GATE_USER = """\
Run: {run_id}
Customer-deliverable: {deliverable}

Verdict:
  exposure index      {exposure_index}
  weighting           {weight_source}
  sensitivity bound   {sensitivity}
  lag p10/p50/p90     {lag}
  observation window  {window} years
  curve fitted        {curve_fitted}
  augmentation share  {augmentation}
  unclear share       {unclear}

Calibration: {calibration_outcome}
  benchmark percentile {benchmark}
  our percentile       {ours}
  explanation          {calibration_explanation}

Structural checks already computed:
{structural}

Caveats carried ({caveat_count}):
{caveats}"""

GATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome", "checks_passed", "checks_failed", "reasoning"],
    "properties": {
        "outcome": {"type": "string",
                    "enum": ["pass", "review_required", "gate_rejected"]},
        "checks_passed": {"type": "array", "items": {"type": "string"}},
        "checks_failed": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string",
                      "description": "Two or three sentences naming the decisive check"},
    },
}

# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM = """\
You narrate an analysis that has already been computed. You add prose, not
findings.

Hard constraints, both checked mechanically after you answer:

1. Every NUMBER you write must appear in the material supplied. Do not round
   into a new figure, do not estimate, do not add a year or a percentage that
   is not there. A number you introduce will be detected and the draft
   rejected.
2. Every CITATION must be a claim ID from the evidence supplied, quoted as
   given. Do not recall a source or reconstruct a reference.

Report exposure and timing as SEPARATE findings. They are different quantities
from different evidence: exposure is technical susceptibility, the lag is how
long reorganisation takes. Do not merge them into a single "jobs at risk"
statement.

Audience: an ML-literate finance reader. No hype. State uncertainty where the
material states it. The caveats are part of the finding, not a disclaimer to
bury at the end."""

SYNTHESIS_USER = """\
Write the executive summary and findings for this analysis.

{verdict_block}

Per-task exposure (most exposed first):
{task_block}

Evidence you may cite:
{evidence_block}

Caveats that must appear in the narrative:
{caveat_block}"""

SYNTHESIS_RETRY_SUFFIX = """\

YOUR PREVIOUS DRAFT WAS REJECTED. {problem}

Rewrite it using only figures and citations present in the material above."""
