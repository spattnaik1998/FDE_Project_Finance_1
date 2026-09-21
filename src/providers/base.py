"""One interface over both model providers.

The charter forbids provider SDK details leaking across the codebase. Callers
ask for a structured completion and get a :class:`ModelResponse`; they never
import ``openai`` or ``anthropic``, never learn that one provider uses
``response_format`` and the other uses forced tool use, and never see an
endpoint URL.

Both providers were characterised by probing the live API rather than from
memory, which mattered: ``gpt-6-astra`` does not support function tools on
``/v1/chat/completions`` at all, and Anthropic has no ``json_schema`` response
format, so structure is obtained through a forced tool call. Two different
mechanisms, one interface.
"""

from __future__ import annotations

import json
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

LOG = logging.getLogger("providers")

DEFAULT_TIMEOUT = 180
MAX_ATTEMPTS = 4
BACKOFF_BASE = 2.0
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


# ---------------------------------------------------------------------------
# Domain exceptions -- providers' own error shapes stop here
# ---------------------------------------------------------------------------

class ProviderError(RuntimeError):
    """A model call failed. Carries provider context, not an SDK traceback."""

    def __init__(self, message: str, *, provider: str, status: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.status = status


class ProviderUnavailable(ProviderError):
    """Transient failure that outlived the retry budget."""


class SchemaViolation(ProviderError):
    """The model returned something the schema does not admit.

    Raised rather than coerced. A classification that does not match its
    contract is not a classification, and silently repairing it would let a
    malformed judgment reach the scoring service looking well-formed.
    """

    def __init__(self, message: str, *, provider: str, payload: Any = None):
        super().__init__(message, provider=provider)
        self.payload = payload


class ModelRefused(ProviderError):
    """The model declined to answer. A legitimate outcome, not an error to hide."""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Usage:
    """Token counts, normalised across providers.

    Cost is deliberately absent: see :mod:`providers.accounting`. Token counts
    are facts the API reports; prices are configuration this project does not
    presume to know for a model released after its reference material.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


@dataclass(frozen=True)
class ModelResponse:
    """What a model call returns, whichever provider served it."""

    provider: str
    model: str
    text: str | None
    structured: dict | None
    usage: Usage
    duration_ms: int
    stop_reason: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def is_structured(self) -> bool:
        return self.structured is not None


@dataclass(frozen=True)
class CallContext:
    """Who is calling and on whose behalf, for the audit trail.

    Every model call carries this so ``audit.AgentAuditLog`` can attribute a
    figure to a run, a stage and a prompt version.
    """

    run_id: str | None = None
    stage: str = "unspecified"
    prompt_version: str = "v1"


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

def request_with_retry(method: str, url: str, *, provider: str,
                       headers: dict, payload: dict,
                       timeout: int = DEFAULT_TIMEOUT,
                       max_attempts: int = MAX_ATTEMPTS,
                       sleep: Callable[[float], None] | None = None) -> dict:
    """Issue one provider request, retrying only what retrying can fix.

    A 4xx other than rate limiting is a bad request and will be bad again, so
    it raises immediately with the provider's own message attached.

    ``sleep`` is resolved at call time, not bound as a default. A default of
    ``time.sleep`` would capture the function at import and make the backoff
    untestable -- patching ``time.sleep`` would have no effect and the suite
    would sit through every real delay while appearing to control them.
    """
    pause = sleep if sleep is not None else time.sleep
    last: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            response = requests.request(method, url, headers=headers,
                                        json=payload, timeout=timeout)
            duration_ms = int((time.perf_counter() - started) * 1000)

            if response.status_code == 200:
                LOG.info("provider=%s status=ok http=200 duration_ms=%s attempt=%s",
                         provider, duration_ms, attempt)
                return response.json()

            detail = response.text[:400]
            if response.status_code not in RETRYABLE_STATUS:
                raise ProviderError(
                    f"{provider}: HTTP {response.status_code}: {detail}",
                    provider=provider, status=response.status_code)

            LOG.warning("provider=%s status=retry http=%s attempt=%s duration_ms=%s",
                        provider, response.status_code, attempt, duration_ms)
            last = ProviderError(f"{provider}: HTTP {response.status_code}: {detail}",
                                 provider=provider, status=response.status_code)

        except requests.RequestException as exc:
            LOG.warning("provider=%s status=retry error=%s attempt=%s",
                        provider, type(exc).__name__, attempt)
            last = exc

        if attempt < max_attempts:
            # Jitter, so concurrent workers do not retry in lockstep.
            pause(BACKOFF_BASE ** attempt + random.uniform(0, 0.5))

    raise ProviderUnavailable(
        f"{provider}: exhausted {max_attempts} attempts for {url}",
        provider=provider) from last


# ---------------------------------------------------------------------------
# The interface
# ---------------------------------------------------------------------------

class ModelProvider(ABC):
    """A model that can answer in prose or against a JSON schema."""

    name: str
    model: str

    @abstractmethod
    def complete(self, prompt: str, *, system: str | None = None,
                 max_tokens: int = 1024,
                 context: CallContext | None = None) -> ModelResponse:
        """Free-text completion."""

    @abstractmethod
    def structured(self, prompt: str, schema: dict, *, schema_name: str,
                   system: str | None = None, max_tokens: int = 2048,
                   context: CallContext | None = None) -> ModelResponse:
        """Completion constrained to ``schema``.

        Implementations must raise :class:`SchemaViolation` rather than return
        a partially-valid object.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name} model={self.model}>"


def parse_structured(payload: Any, *, provider: str,
                     required: list[str] | None = None) -> dict:
    """Decode and check a structured payload, or raise.

    Handles the case where a model returns a JSON *string* instead of an
    object, which both providers do occasionally under load.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SchemaViolation(f"{provider}: response was not valid JSON: {exc}",
                                  provider=provider, payload=payload) from exc

    if not isinstance(payload, dict):
        raise SchemaViolation(
            f"{provider}: expected a JSON object, got {type(payload).__name__}",
            provider=provider, payload=payload)

    missing = [key for key in (required or []) if key not in payload]
    if missing:
        raise SchemaViolation(
            f"{provider}: structured response missing required field(s): "
            f"{', '.join(missing)}", provider=provider, payload=payload)

    return payload
