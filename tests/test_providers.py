"""Provider adapters: one interface, two very different mechanisms.

Everything here runs against recorded response shapes, so the suite is fast and
needs no credentials. The shapes are taken from real probes of both APIs —
including the reasoning-block structure of ``/v1/responses`` and the
``tool_use`` block Anthropic returns under forced tool choice — so a mocked
test still exercises the parsing the live call would.

Live smoke tests live in ``test_providers_live.py`` and skip without keys.
"""

from __future__ import annotations

import json

import pytest
import requests

from providers import accounting
from providers.anthropic_provider import AnthropicProvider
from providers.base import (
    CallContext,
    ModelProvider,
    ModelRefused,
    ModelResponse,
    ProviderError,
    ProviderUnavailable,
    SchemaViolation,
    Usage,
    parse_structured,
    request_with_retry,
)
from providers.openai_provider import OpenAIProvider

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["routine", "tacitness", "direction", "confidence"],
    "properties": {
        "routine": {"type": "string", "enum": ["routine", "non_routine"]},
        "tacitness": {"type": "string", "enum": ["low", "medium", "high"]},
        "direction": {"type": "string", "enum": ["augment", "substitute", "unclear"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}
ANSWER = {"routine": "non_routine", "tacitness": "high",
          "direction": "augment", "confidence": "high"}


# ---------------------------------------------------------------------------
# Recorded response shapes
# ---------------------------------------------------------------------------

def openai_response(text: str | None = None, *, reasoning_tokens: int = 72,
                    status: str = "completed", refusal: str | None = None) -> dict:
    output: list[dict] = [{"type": "reasoning", "summary": []}]
    content: list[dict] = []
    if refusal is not None:
        content.append({"type": "refusal", "refusal": refusal})
    elif text is not None:
        content.append({"type": "output_text", "text": text})
    if content:
        output.append({"type": "message", "content": content})
    return {
        "id": "resp_1", "model": "gpt-6-astra", "status": status, "output": output,
        "usage": {"input_tokens": 134, "output_tokens": 206,
                  "input_tokens_details": {"cached_tokens": 12},
                  "output_tokens_details": {"reasoning_tokens": reasoning_tokens}},
    }


def anthropic_response(*, tool_input: dict | None = None, text: str | None = None,
                       tool_name: str = "task_classification",
                       stop_reason: str = "tool_use") -> dict:
    content: list[dict] = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool_input is not None:
        content.append({"type": "tool_use", "id": "tu_1", "name": tool_name,
                        "input": tool_input})
    return {
        "id": "msg_1", "model": "claude-opus-5", "stop_reason": stop_reason,
        "content": content,
        "usage": {"input_tokens": 646, "output_tokens": 106,
                  "cache_read_input_tokens": 30,
                  "output_tokens_details": {"thinking_tokens": 0}},
    }


class FakeHTTP:
    """Stands in for ``requests.request``, recording what was sent."""

    def __init__(self, *responses):
        self.queue = list(responses)
        self.calls: list[dict] = []

    def __call__(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "payload": json, "timeout": timeout})
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        return item


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr("providers.base.time.sleep", lambda _s: None)


def patch_http(monkeypatch, *responses) -> FakeHTTP:
    fake = FakeHTTP(*responses)
    monkeypatch.setattr(requests, "request", fake)
    return fake


# ---------------------------------------------------------------------------
# The interface contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [OpenAIProvider, AnthropicProvider])
def test_both_providers_implement_the_interface(cls):
    assert issubclass(cls, ModelProvider)


@pytest.mark.parametrize("cls", [OpenAIProvider, AnthropicProvider])
def test_provider_requires_a_key(cls):
    with pytest.raises(ValueError, match="API key"):
        cls(api_key="", model="m")


def test_no_module_imports_a_vendor_sdk():
    """The charter forbids provider SDK details leaking across the codebase."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        if path.parent.name == "providers":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in {"openai", "anthropic"}:
                    offenders.append(f"{path.relative_to(src)}: {name}")
    assert not offenders, f"vendor SDK imported outside providers/: {offenders}"


def test_openai_rejects_the_reasoning_effort_the_model_refuses():
    """Probing established that gpt-6-astra rejects effort='none'."""
    with pytest.raises(ValueError, match="none"):
        OpenAIProvider(api_key="k", model="gpt-6-astra", reasoning_effort="none")


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh"])
def test_openai_accepts_every_valid_effort(effort):
    OpenAIProvider(api_key="k", model="gpt-6-astra", reasoning_effort=effort)


# ---------------------------------------------------------------------------
# OpenAI adapter
# ---------------------------------------------------------------------------

def test_openai_uses_the_responses_endpoint(monkeypatch):
    """Not chat/completions: function tools do not work there for this model."""
    fake = patch_http(monkeypatch, FakeResponse(200, openai_response("hello")))
    OpenAIProvider("k", "gpt-6-astra").complete("hi")
    assert fake.calls[0]["url"].endswith("/v1/responses")


def test_openai_sends_reasoning_effort(monkeypatch):
    fake = patch_http(monkeypatch, FakeResponse(200, openai_response("hi")))
    OpenAIProvider("k", "gpt-6-astra", reasoning_effort="xhigh").complete("hi")
    assert fake.calls[0]["payload"]["reasoning"] == {"effort": "xhigh"}


def test_openai_structured_sends_a_strict_json_schema(monkeypatch):
    fake = patch_http(monkeypatch,
                      FakeResponse(200, openai_response(json.dumps(ANSWER))))
    OpenAIProvider("k", "gpt-6-astra").structured(
        "classify", SCHEMA, schema_name="task_classification")
    fmt = fake.calls[0]["payload"]["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["schema"] == SCHEMA


def test_openai_structured_returns_the_parsed_object(monkeypatch):
    patch_http(monkeypatch, FakeResponse(200, openai_response(json.dumps(ANSWER))))
    result = OpenAIProvider("k", "gpt-6-astra").structured(
        "classify", SCHEMA, schema_name="task_classification")
    assert result.structured == ANSWER
    assert result.is_structured


def test_openai_skips_reasoning_blocks_when_reading_text(monkeypatch):
    """A reasoning model's output list leads with a block that is not content."""
    patch_http(monkeypatch, FakeResponse(200, openai_response("the answer")))
    assert OpenAIProvider("k", "gpt-6-astra").complete("hi").text == "the answer"


def test_openai_normalises_usage_including_reasoning_tokens(monkeypatch):
    patch_http(monkeypatch, FakeResponse(200, openai_response("hi",
                                                              reasoning_tokens=99)))
    usage = OpenAIProvider("k", "gpt-6-astra").complete("hi").usage
    assert usage.input_tokens == 134
    assert usage.output_tokens == 206
    assert usage.cached_input_tokens == 12
    assert usage.reasoning_tokens == 99
    assert usage.total_tokens == 340


def test_openai_refusal_raises_rather_than_returning_empty(monkeypatch):
    patch_http(monkeypatch,
               FakeResponse(200, openai_response(refusal="I cannot help with that.")))
    with pytest.raises(ModelRefused, match="cannot help"):
        OpenAIProvider("k", "gpt-6-astra").complete("hi")


def test_openai_empty_output_is_a_schema_violation_not_an_empty_answer(monkeypatch):
    """A reasoning model can spend its whole budget thinking. Say so."""
    patch_http(monkeypatch, FakeResponse(200, openai_response(None)))
    with pytest.raises(SchemaViolation, match="reasoning budget"):
        OpenAIProvider("k", "gpt-6-astra").structured(
            "classify", SCHEMA, schema_name="task_classification")


def test_openai_incomplete_status_raises(monkeypatch):
    payload = openai_response("partial")
    payload["status"] = "incomplete"
    payload["incomplete_details"] = {"reason": "max_output_tokens"}
    patch_http(monkeypatch, FakeResponse(200, payload))
    with pytest.raises(ModelRefused, match="incomplete"):
        OpenAIProvider("k", "gpt-6-astra").complete("hi")


def test_openai_passes_the_system_prompt_as_instructions(monkeypatch):
    fake = patch_http(monkeypatch, FakeResponse(200, openai_response("hi")))
    OpenAIProvider("k", "gpt-6-astra").complete("hi", system="Be terse.")
    assert fake.calls[0]["payload"]["instructions"] == "Be terse."


# ---------------------------------------------------------------------------
# Anthropic adapter
# ---------------------------------------------------------------------------

def test_anthropic_uses_the_messages_endpoint(monkeypatch):
    fake = patch_http(monkeypatch,
                      FakeResponse(200, anthropic_response(text="hello",
                                                           stop_reason="end_turn")))
    AnthropicProvider("k", "claude-opus-5").complete("hi")
    assert fake.calls[0]["url"].endswith("/v1/messages")
    assert fake.calls[0]["headers"]["anthropic-version"]


def test_anthropic_structured_forces_a_single_tool(monkeypatch):
    """There is no json_schema response format; forced tool use is the mechanism."""
    fake = patch_http(monkeypatch,
                      FakeResponse(200, anthropic_response(tool_input=ANSWER)))
    AnthropicProvider("k", "claude-opus-5").structured(
        "classify", SCHEMA, schema_name="task_classification")

    payload = fake.calls[0]["payload"]
    assert len(payload["tools"]) == 1
    assert payload["tools"][0]["input_schema"] == SCHEMA
    assert payload["tool_choice"] == {"type": "tool", "name": "task_classification"}


def test_anthropic_returns_the_tool_input_as_the_structured_answer(monkeypatch):
    patch_http(monkeypatch, FakeResponse(200, anthropic_response(tool_input=ANSWER)))
    result = AnthropicProvider("k", "claude-opus-5").structured(
        "classify", SCHEMA, schema_name="task_classification")
    assert result.structured == ANSWER


def test_anthropic_missing_tool_call_does_not_fall_back_to_prose(monkeypatch):
    """A schema obtained by guessing at free text is not a schema."""
    patch_http(monkeypatch, FakeResponse(
        200, anthropic_response(text=json.dumps(ANSWER), stop_reason="end_turn")))
    with pytest.raises(SchemaViolation, match="forced tool call"):
        AnthropicProvider("k", "claude-opus-5").structured(
            "classify", SCHEMA, schema_name="task_classification")


def test_anthropic_normalises_cache_read_tokens(monkeypatch):
    patch_http(monkeypatch, FakeResponse(200, anthropic_response(tool_input=ANSWER)))
    usage = AnthropicProvider("k", "claude-opus-5").structured(
        "classify", SCHEMA, schema_name="task_classification").usage
    assert usage.input_tokens == 646
    assert usage.cached_input_tokens == 30


def test_anthropic_refusal_raises(monkeypatch):
    patch_http(monkeypatch, FakeResponse(
        200, anthropic_response(text="no", stop_reason="refusal")))
    with pytest.raises(ModelRefused):
        AnthropicProvider("k", "claude-opus-5").complete("hi")


def test_anthropic_empty_text_on_budget_exhaustion_raises(monkeypatch):
    """A reasoning model can spend its whole budget thinking and return nothing.

    Observed live with claude-opus-5 at max_tokens=16: reasoning_tokens equalled
    output_tokens and text was None. Returning that silently would surface
    later as a mysteriously empty answer.
    """
    payload = anthropic_response(text=None, stop_reason="max_tokens")
    payload["usage"]["output_tokens_details"] = {"thinking_tokens": 16}
    patch_http(monkeypatch, FakeResponse(200, payload))
    with pytest.raises(ModelRefused, match="budget was exhausted"):
        AnthropicProvider("k", "claude-opus-5").complete("hi", max_tokens=16)


def test_anthropic_truncated_but_non_empty_text_is_returned(monkeypatch):
    """Truncation is not the same as no answer; a partial reply still returns."""
    patch_http(monkeypatch, FakeResponse(
        200, anthropic_response(text="ready", stop_reason="max_tokens")))
    result = AnthropicProvider("k", "claude-opus-5").complete("hi", max_tokens=16)
    assert result.text == "ready"
    assert result.stop_reason == "max_tokens"


def test_anthropic_passes_system_at_the_top_level(monkeypatch):
    fake = patch_http(monkeypatch, FakeResponse(
        200, anthropic_response(text="hi", stop_reason="end_turn")))
    AnthropicProvider("k", "claude-opus-5").complete("hi", system="Be terse.")
    assert fake.calls[0]["payload"]["system"] == "Be terse."


# ---------------------------------------------------------------------------
# Both adapters return the same shape
# ---------------------------------------------------------------------------

def test_both_providers_return_an_identical_response_shape(monkeypatch):
    patch_http(monkeypatch, FakeResponse(200, openai_response(json.dumps(ANSWER))))
    first = OpenAIProvider("k", "gpt-6-astra").structured(
        "classify", SCHEMA, schema_name="task_classification")

    patch_http(monkeypatch, FakeResponse(200, anthropic_response(tool_input=ANSWER)))
    second = AnthropicProvider("k", "claude-opus-5").structured(
        "classify", SCHEMA, schema_name="task_classification")

    assert type(first) is type(second) is ModelResponse
    assert first.structured == second.structured
    assert {f for f in vars(first)} == {f for f in vars(second)}


# ---------------------------------------------------------------------------
# Schema violations
# ---------------------------------------------------------------------------

def test_malformed_json_is_a_schema_violation(monkeypatch):
    patch_http(monkeypatch, FakeResponse(200, openai_response("{not json")))
    with pytest.raises(SchemaViolation, match="not valid JSON"):
        OpenAIProvider("k", "gpt-6-astra").structured(
            "classify", SCHEMA, schema_name="task_classification")


def test_missing_required_field_is_a_schema_violation(monkeypatch):
    partial = {k: v for k, v in ANSWER.items() if k != "confidence"}
    patch_http(monkeypatch, FakeResponse(200, openai_response(json.dumps(partial))))
    with pytest.raises(SchemaViolation, match="confidence"):
        OpenAIProvider("k", "gpt-6-astra").structured(
            "classify", SCHEMA, schema_name="task_classification")


def test_schema_violation_carries_the_offending_payload():
    """Needed to debug a bad response without re-running the call."""
    with pytest.raises(SchemaViolation) as exc:
        parse_structured("[]", provider="test", required=["a"])
    assert exc.value.payload is not None


def test_a_json_array_is_not_an_object():
    with pytest.raises(SchemaViolation, match="expected a JSON object"):
        parse_structured("[1, 2]", provider="test")


def test_a_json_string_payload_is_decoded():
    assert parse_structured(json.dumps(ANSWER), provider="test",
                            required=list(ANSWER)) == ANSWER


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

def test_transient_failure_is_retried_then_succeeds(monkeypatch, no_sleep):
    fake = patch_http(monkeypatch,
                      FakeResponse(503, text="unavailable"),
                      FakeResponse(200, openai_response("recovered")))
    result = OpenAIProvider("k", "gpt-6-astra").complete("hi")
    assert result.text == "recovered"
    assert len(fake.calls) == 2


def test_rate_limit_is_retried(monkeypatch, no_sleep):
    fake = patch_http(monkeypatch,
                      FakeResponse(429, text="slow down"),
                      FakeResponse(200, openai_response("ok")))
    OpenAIProvider("k", "gpt-6-astra").complete("hi")
    assert len(fake.calls) == 2


def test_bad_request_is_not_retried(monkeypatch, no_sleep):
    """A 400 will be 400 again; retrying wastes the budget and the wall clock."""
    fake = patch_http(monkeypatch, FakeResponse(400, text="invalid schema"))
    with pytest.raises(ProviderError) as exc:
        OpenAIProvider("k", "gpt-6-astra").complete("hi")
    assert exc.value.status == 400
    assert len(fake.calls) == 1


def test_auth_failure_is_not_retried(monkeypatch, no_sleep):
    fake = patch_http(monkeypatch, FakeResponse(401, text="bad key"))
    with pytest.raises(ProviderError):
        OpenAIProvider("k", "gpt-6-astra").complete("hi")
    assert len(fake.calls) == 1


def test_retry_budget_is_finite(monkeypatch, no_sleep):
    fake = patch_http(monkeypatch, FakeResponse(503, text="down"))
    with pytest.raises(ProviderUnavailable, match="exhausted"):
        OpenAIProvider("k", "gpt-6-astra").complete("hi")
    assert len(fake.calls) == 4


def test_network_error_is_retried(monkeypatch, no_sleep):
    fake = patch_http(monkeypatch,
                      requests.ConnectionError("reset"),
                      FakeResponse(200, openai_response("ok")))
    OpenAIProvider("k", "gpt-6-astra").complete("hi")
    assert len(fake.calls) == 2


def test_provider_error_carries_vendor_context(monkeypatch, no_sleep):
    patch_http(monkeypatch, FakeResponse(400, text="nope"))
    with pytest.raises(ProviderError) as exc:
        AnthropicProvider("k", "claude-opus-5").complete("hi")
    assert exc.value.provider == "anthropic"


def test_retry_sleeps_with_increasing_backoff(monkeypatch):
    delays: list[float] = []
    patch_http(monkeypatch, FakeResponse(503, text="down"))
    monkeypatch.setattr("providers.base.time.sleep", delays.append)
    with pytest.raises(ProviderUnavailable):
        OpenAIProvider("k", "gpt-6-astra").complete("hi")
    assert len(delays) == 3
    assert delays == sorted(delays), "backoff must not decrease"


# ---------------------------------------------------------------------------
# Logging carries run_id
# ---------------------------------------------------------------------------

def test_call_context_run_id_reaches_the_log(monkeypatch, caplog):
    patch_http(monkeypatch, FakeResponse(200, openai_response("hi")))
    with caplog.at_level("INFO"):
        OpenAIProvider("k", "gpt-6-astra").complete(
            "hi", context=CallContext(run_id="run-123", stage="task_classifier"))
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "run-123" in joined
    assert "task_classifier" in joined
