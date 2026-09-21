"""Anthropic adapter, on ``/v1/messages``.

Anthropic has **no ``json_schema`` response format**. Structure is obtained by
declaring a single tool whose ``input_schema`` is the contract and forcing its
use with ``tool_choice``; the model's tool input *is* the structured answer.
Verified by probing: ``stop_reason`` comes back as ``tool_use`` and the input
validates against the schema.

This provider serves Intent & Scope and the Review Gate. The split is
deliberate — the gate grading the classifier's work is a different model from
the one that produced it, which a single-provider setup loses.
"""

from __future__ import annotations

import logging
import time

from config import ANTHROPIC_MESSAGES_URL, ANTHROPIC_VERSION
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

LOG = logging.getLogger("providers.anthropic")

# Anthropic signals refusal through stop_reason rather than a content block.
REFUSAL_STOP_REASONS = {"refusal"}


class AnthropicProvider(ModelProvider):
    """Wraps the Messages API behind the shared interface."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str,
                 url: str = ANTHROPIC_MESSAGES_URL,
                 api_version: str = ANTHROPIC_VERSION, timeout: int = 180):
        if not api_key:
            raise ValueError("AnthropicProvider requires an API key")
        self.model = model
        self._api_key = api_key
        self._url = url
        self._version = api_version
        self._timeout = timeout

    # -- internals ---------------------------------------------------------

    @property
    def _headers(self) -> dict:
        return {"x-api-key": self._api_key,
                "anthropic-version": self._version,
                "content-type": "application/json"}

    def _payload(self, prompt: str, system: str | None, max_tokens: int) -> dict:
        payload: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        return payload

    @staticmethod
    def _usage(raw: dict) -> Usage:
        usage = raw.get("usage") or {}
        details = usage.get("output_tokens_details") or {}
        return Usage(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cached_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
            reasoning_tokens=int(details.get("thinking_tokens") or 0),
        )

    @staticmethod
    def _text(raw: dict) -> str | None:
        chunks = [block.get("text", "") for block in raw.get("content", [])
                  if block.get("type") == "text"]
        joined = "".join(chunks).strip()
        return joined or None

    @staticmethod
    def _tool_input(raw: dict, tool_name: str) -> dict | None:
        for block in raw.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == tool_name:
                return block.get("input")
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

        stop = raw.get("stop_reason")
        if stop in REFUSAL_STOP_REASONS:
            raise ModelRefused(f"{self.name}: model declined to answer "
                               f"(stop_reason={stop})", provider=self.name)

        usage = self._usage(raw)
        ctx = context or CallContext()
        LOG.info("provider=%s stage=%s model=%s status=ok tokens_in=%s tokens_out=%s "
                 "duration_ms=%s run_id=%s", self.name, ctx.stage, self.model,
                 usage.input_tokens, usage.output_tokens, duration_ms, ctx.run_id)

        return ModelResponse(provider=self.name, model=self.model,
                             text=self._text(raw), structured=None, usage=usage,
                             duration_ms=duration_ms, stop_reason=stop, raw=raw)

    def structured(self, prompt: str, schema: dict, *, schema_name: str,
                   system: str | None = None, max_tokens: int = 2048,
                   context: CallContext | None = None) -> ModelResponse:
        """Force a single tool call whose input schema *is* the contract."""
        payload = self._payload(prompt, system, max_tokens)
        payload["tools"] = [{
            "name": schema_name,
            "description": f"Emit the {schema_name} result. Use this tool only.",
            "input_schema": schema,
        }]
        payload["tool_choice"] = {"type": "tool", "name": schema_name}

        started = time.perf_counter()
        raw = request_with_retry("POST", self._url, provider=self.name,
                                 headers=self._headers, payload=payload,
                                 timeout=self._timeout)
        duration_ms = int((time.perf_counter() - started) * 1000)

        stop = raw.get("stop_reason")
        if stop in REFUSAL_STOP_REASONS:
            raise ModelRefused(f"{self.name}: model declined to answer "
                               f"(stop_reason={stop})", provider=self.name)

        tool_input = self._tool_input(raw, schema_name)
        if tool_input is None:
            # Forced tool use did not happen. Do not fall back to parsing prose:
            # a schema obtained by guessing at free text is not a schema.
            raise SchemaViolation(
                f"{self.name}: expected a forced tool call to {schema_name!r} "
                f"but none was returned (stop_reason={stop})",
                provider=self.name, payload=raw)

        structured = parse_structured(tool_input, provider=self.name,
                                      required=list(schema.get("required", [])))

        usage = self._usage(raw)
        ctx = context or CallContext()
        LOG.info("provider=%s stage=%s model=%s status=ok schema=%s tokens_in=%s "
                 "tokens_out=%s duration_ms=%s run_id=%s",
                 self.name, ctx.stage, self.model, schema_name,
                 usage.input_tokens, usage.output_tokens, duration_ms, ctx.run_id)

        return ModelResponse(provider=self.name, model=self.model,
                             text=self._text(raw), structured=structured,
                             usage=usage, duration_ms=duration_ms,
                             stop_reason=stop, raw=raw)
