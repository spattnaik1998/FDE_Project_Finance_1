"""The typed request/response contract between the presentation and
orchestration tiers.

TDD 1.1 draws this arrow explicitly:

    PRESENTATION TIER
            ▲
            │ typed request / RoleVerdict response
    ORCHESTRATION TIER

Until now only the response direction existed. The UI read persisted runs and a
CLI script drove orchestration, so the presentation tier could not initiate
anything and the arrow was one-way in practice. That was the build's most
material divergence from the architecture, and this module is the missing half.

Two properties the contract has to preserve, because they are what the tier
split is for:

* **The UI sends a request, not a query.** A :class:`RunRequest` carries the
  customer's question and nothing else — no SQL, no SOC code it resolved
  itself, no scoring parameters. Resolving free text to an occupation is the
  Intent & Scope node's job, and letting the UI pre-resolve it would move a
  model's judgment into the presentation tier.
* **The UI receives a typed response, never a handle.** A
  :class:`SubmissionResult` is plain values. It cannot be used to reach the
  warehouse or a provider, so the presentation tier still holds no credential
  and computes nothing.

A refusal is a first-class outcome here, not an exception. The Intent node halts
on an occupation the warehouse does not publish rather than substituting a
neighbour, and the customer needs to see *that* rather than a stack trace.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# A run costs roughly this much, measured across the live runs to date. Shown to
# the customer before they spend it, because a button that quietly issues 28
# model calls is not a button anyone should trust.
TYPICAL_CALLS = 28
TYPICAL_TOKENS = 31_100
# Wall clock, measured -- 39s on the run that set this figure. It was ~190s
# until the classifier stopped issuing its 26 calls one at a time. Stated as
# elapsed time rather than summed provider time, which is ~160s and is what
# made the speed-up invisible in the ledger for a while.
TYPICAL_SECONDS = 40


class RunCost(BaseModel):
    """What a run costs, pre-formatted for display.

    The duration arrives as a string rather than as seconds because
    ``app/blocks.py`` is forbidden from doing arithmetic -- a presentation layer
    that can compute can produce a figure that is on no source, and
    ``test_no_block_performs_arithmetic`` enforces it. Formatting the value here
    keeps that rule intact instead of carving an exception into it.
    """

    calls: int = TYPICAL_CALLS
    tokens: int = TYPICAL_TOKENS
    duration_text: str = "under a minute"

    model_config = {"frozen": True}

MAX_QUESTION_CHARS = 500


class RunRequest(BaseModel):
    """What the presentation tier may ask for.

    Deliberately minimal. There is no ``soc_code`` field: if the UI could name
    the occupation, the Intent & Scope node's verification against the published
    catalogue would be bypassed, and a confident answer about the wrong role is
    the worst failure this system can produce.
    """

    question: str = Field(min_length=10, max_length=MAX_QUESTION_CHARS)
    is_customer_deliverable: bool = False

    model_config = {"frozen": True}

    @field_validator("question")
    @classmethod
    def _not_a_sql_statement(cls, value: str) -> str:
        """Refuse anything that looks like a query rather than a question.

        The UI has no business sending SQL, and the orchestration tier has no
        business accepting it. Defence in depth: the tools already whitelist
        their objects, but a request is the wrong place for a statement.
        """
        lowered = value.lower()
        # Whitespace-insensitive where it matters: "; --" is as much a comment
        # injection as ";--", and the first spelling is the one a person types.
        collapsed = " ".join(lowered.split())
        for token in ("select ", "insert ", "update ", "delete ", "drop ",
                      "; --", ";--", "union all"):
            if token in collapsed:
                raise ValueError(
                    "A request carries a question, not a statement. The "
                    "orchestration tier resolves scope itself.")
        for token in ():
            if token in lowered:
                raise ValueError(
                    "A request carries a question, not a statement. The "
                    "orchestration tier resolves scope itself.")
        return value.strip()


class RefusalReason(BaseModel):
    """Why a request produced no analysis.

    Separate from an error. "That occupation is not published" is a correct
    answer to a reasonable question, and the customer should read it as one.
    """

    code: str
    message: str
    in_scope_hint: tuple[str, ...] = ()

    model_config = {"frozen": True}


class SubmissionResult(BaseModel):
    """The response half of the contract.

    Carries either a run id whose verdict was persisted, or a refusal. Never
    both, and never a database handle or a live object.
    """

    accepted: bool
    run_id: str | None = None
    status: str | None = None
    refusal: RefusalReason | None = None
    calls: int = 0
    tokens: int = 0
    # Summed provider time, not elapsed. Named on the contract the way the
    # ledger names it, so a consumer cannot mistake it for how long they waited.
    provider_time_ms: int = 0

    model_config = {"frozen": True}

    @property
    def produced_a_verdict(self) -> bool:
        return self.accepted and self.run_id is not None
