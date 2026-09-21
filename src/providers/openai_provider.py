"""OpenAI adapter, on ``/v1/responses``.

The endpoint choice is not stylistic. Probing the live API established that
``gpt-6-astra`` **does not support function tools on /v1/chat/completions**,
and that the documented workaround — ``reasoning_effort: 'none'`` — is itself
rejected for this model. ``/v1/responses`` supports both tools and strict
structured outputs, so the project standardises on it and has one code path
rather than two with different capabilities.

``gpt-6-astra`` is a reasoning model: effort is one of low / medium / high /
xhigh, defaulting to medium.
"""

from __future__ import annotations

import logging
import time

from config import OPENAI_RESPONSES_URL, REASONING_EFFORT
from providers.base import (
    CallContext,
    ModelProvider,
    ModelRefused,
    ModelResponse,
    SchemaViolation,
    Usage,
    parse_structured,
    request_with_retry,
)

LOG = logging.getLogger("providers.openai")

VALID_EFFORTS = ("low", "medium", "high", "xhigh")


class OpenAIProvider(ModelProvider):
    """Wraps the Responses API behind the shared interface."""

    name = "openai"

    def __init__(self, api_key: str, model: str,
                 reasoning_effort: str = REASONING_EFFORT,
                 url: str = OPENAI_RESPONSES_URL, timeout: int = 180):
        if not api_key:
            raise ValueError("OpenAIProvider requires an API key")
        if reasoning_effort not in VALID_EFFORTS:
            raise ValueError(
                f"reasoning_effort must be one of {VALID_EFFORTS}; got "
                f"{reasoning_effort!r}. Note 'none' is rejected by this model.")

        self.model = model
        self._api_key = api_key
        self._effort = reasoning_effort
        self._url = url
        self._timeout = timeout

    # -- internals ---------------------------------------------------------

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"}

    def _payload(self, prompt: str, system: str | None, max_tokens: int) -> dict:
        payload: dict = {
            "model": self.model,
            "input": prompt,
            "reasoning": {"effort": self._effort},
            "max_output_tokens": max_tokens,
        }
        if system:
            payload["instructions"] = system
        return payload

    @staticmethod
    def _usage(raw: dict) -> Usage:
        usage = raw.get("usage") or {}
        details = usage.get("output_tokens_details") or {}
        return Usage(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cached_input_tokens=int(
                (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0),
            reasoning_tokens=int(details.get("reasoning_tokens") or 0),
        )

    @staticmethod
    def _text(raw: dict) -> str | None:
        """Concatenate message text, skipping reasoning blocks."""
        chunks: list[str] = []
        for item in raw.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") in ("output_text", "text"):
                    chunks.append(content.get("text", ""))
        joined = "".join(chunks).strip()
        return joined or None

    @staticmethod
    def _refusal(raw: dict) -> str | None:
        for item in raw.get("output", []):
            for content in item.get("content", []) or []:
                if content.get("type") == "refusal":
                    return content.get("refusal") or "model refused"
        if raw.get("status") == "incomplete":
            reason = (raw.get("incomplete_details") or {}).get("reason")
            return f"incomplete response: {reason}"
        return None

    # -- interface ---------------------------------------------------------

    def complete(self, prompt: str, *, system: str | None = None,
                 max_tokens: int = 1024,
                 context: CallContext | None = None) -> ModelResponse:
        started = time.perf_counter()
        raw = request_with_retry("POST", self._url, provider=self.name,
                                 headers=self._headers,
                                 payload=self._payload(prompt, system, max_tokens),
                                 timeout=self._timeout)
        duration_ms = int((time.perf_counter() - started) * 1000)

        refusal = self._refusal(raw)
        if refusal:
            raise ModelRefused(f"{self.name}: {refusal}", provider=self.name)

        ctx = context or CallContext()
        LOG.info("provider=%s stage=%s model=%s status=ok tokens_in=%s tokens_out=%s "
                 "duration_ms=%s run_id=%s", self.name, ctx.stage, self.model,
                 self._usage(raw).input_tokens, self._usage(raw).output_tokens,
                 duration_ms, ctx.run_id)

        return ModelResponse(provider=self.name, model=self.model,
                             text=self._text(raw), structured=None,
                             usage=self._usage(raw), duration_ms=duration_ms,
                             stop_reason=raw.get("status"), raw=raw)

    def structured(self, prompt: str, schema: dict, *, schema_name: str,
                   system: str | None = None, max_tokens: int = 2048,
                   context: CallContext | None = None) -> ModelResponse:
        payload = self._payload(prompt, system, max_tokens)
        payload["text"] = {"format": {"type": "json_schema", "name": schema_name,
                                      "strict": True, "schema": schema}}

        started = time.perf_counter()
        raw = request_with_retry("POST", self._url, provider=self.name,
                                 headers=self._headers, payload=payload,
                                 timeout=self._timeout)
        duration_ms = int((time.perf_counter() - started) * 1000)

        refusal = self._refusal(raw)
        if refusal:
            raise ModelRefused(f"{self.name}: {refusal}", provider=self.name)

        text = self._text(raw)
        if not text:
            # A reasoning model that spends its whole budget thinking returns
            # no message. Saying so beats returning an empty classification.
            raise SchemaViolation(
                f"{self.name}: no message content returned; the reasoning "
                f"budget may have been exhausted before any output "
                f"(max_output_tokens={max_tokens})",
                provider=self.name, payload=raw)

        structured = parse_structured(text, provider=self.name,
                                      required=list(schema.get("required", [])))

        ctx = context or CallContext()
        usage = self._usage(raw)
        LOG.info("provider=%s stage=%s model=%s status=ok schema=%s tokens_in=%s "
                 "tokens_out=%s reasoning=%s duration_ms=%s run_id=%s",
                 self.name, ctx.stage, self.model, schema_name,
                 usage.input_tokens, usage.output_tokens, usage.reasoning_tokens,
                 duration_ms, ctx.run_id)

        return ModelResponse(provider=self.name, model=self.model, text=text,
                             structured=structured, usage=usage,
                             duration_ms=duration_ms,
                             stop_reason=raw.get("status"), raw=raw)
