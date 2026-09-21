"""Live smoke tests: one call per provider, against the real API.

These exist because the mocked suite can only prove we parse the shapes we
*believe* the APIs return. Two of this project's findings came from probing
rather than from documentation — that ``gpt-6-astra`` has no function tools on
``/v1/chat/completions``, and that Anthropic has no ``json_schema`` response
format — so a thin live check is worth its cost.

Kept deliberately small: a handful of tokens each. Skips cleanly when
credentials are absent, and is marked ``live`` so it can be deselected:

    python -m pytest -m "not live"
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live

MINI_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict"],
    "properties": {"verdict": {"type": "string", "enum": ["ready", "not_ready"]}},
}


def _keys() -> dict:
    try:
        import config
        return config.load_keys(include_models=True)
    except Exception:
        return {}


KEYS = _keys()
HAS_OPENAI = bool(KEYS.get("OPENAI_API_KEY"))
HAS_ANTHROPIC = bool(KEYS.get("ANTHROPIC_API_KEY"))

needs_openai = pytest.mark.skipif(not HAS_OPENAI, reason="no OPENAI_API_KEY")
needs_anthropic = pytest.mark.skipif(not HAS_ANTHROPIC, reason="no ANTHROPIC_API_KEY")


@pytest.fixture(scope="module")
def openai_provider():
    import config
    from providers.openai_provider import OpenAIProvider
    return OpenAIProvider(KEYS["OPENAI_API_KEY"], config.MODEL_CLASSIFIER,
                          reasoning_effort="low")


@pytest.fixture(scope="module")
def anthropic_provider():
    import config
    from providers.anthropic_provider import AnthropicProvider
    return AnthropicProvider(KEYS["ANTHROPIC_API_KEY"], config.MODEL_REVIEW_GATE)


# --- OpenAI ------------------------------------------------------------------

@needs_openai
def test_openai_structured_call_returns_a_schema_valid_object(openai_provider):
    result = openai_provider.structured(
        "Reply with verdict 'ready'.", MINI_SCHEMA, schema_name="smoke",
        max_tokens=600)
    assert result.structured["verdict"] in ("ready", "not_ready")
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
    assert result.duration_ms > 0
    assert result.provider == "openai"


@needs_openai
def test_openai_reports_reasoning_tokens(openai_provider):
    """It is a reasoning model; the usage breakdown should say so."""
    result = openai_provider.complete("Reply with one word: ready.", max_tokens=400)
    details = (result.raw.get("usage") or {}).get("output_tokens_details") or {}
    assert "reasoning_tokens" in details


# --- Anthropic ---------------------------------------------------------------

@needs_anthropic
def test_anthropic_forced_tool_use_returns_a_schema_valid_object(anthropic_provider):
    """Anthropic's structured-output mechanism is a forced tool call."""
    result = anthropic_provider.structured(
        "Reply with verdict 'ready'.", MINI_SCHEMA, schema_name="smoke",
        max_tokens=300)
    assert result.structured["verdict"] in ("ready", "not_ready")
    assert result.stop_reason == "tool_use"
    assert result.usage.input_tokens > 0
    assert result.provider == "anthropic"


@needs_anthropic
def test_anthropic_plain_completion_works(anthropic_provider):
    result = anthropic_provider.complete("Reply with one word: ready.", max_tokens=16)
    assert result.text
    assert result.stop_reason in ("end_turn", "max_tokens")


# --- Both --------------------------------------------------------------------

@pytest.mark.skipif(not (HAS_OPENAI and HAS_ANTHROPIC),
                    reason="needs both credentials")
def test_both_providers_satisfy_the_same_contract(openai_provider,
                                                  anthropic_provider):
    """The point of the interface: a caller cannot tell them apart."""
    results = [
        provider.structured("Reply with verdict 'ready'.", MINI_SCHEMA,
                            schema_name="smoke", max_tokens=600)
        for provider in (openai_provider, anthropic_provider)
    ]
    for result in results:
        assert set(result.structured) == {"verdict"}
        assert result.usage.total_tokens > 0
    assert results[0].provider != results[1].provider


@pytest.mark.skipif(not (HAS_OPENAI and HAS_ANTHROPIC),
                    reason="needs both credentials")
def test_ledger_accumulates_across_providers(openai_provider, anthropic_provider):
    from providers.accounting import Ledger

    ledger = Ledger(run_id="live-smoke")
    ledger.record(anthropic_provider.complete("Say ready.", max_tokens=16),
                  stage="review_gate")
    ledger.record(openai_provider.complete("Say ready.", max_tokens=400),
                  stage="task_classifier")

    summary = ledger.summary()
    assert summary["calls"] == 2
    assert summary["total_tokens"] > 0
    # Prices are not configured for these models, so cost must be withheld
    # rather than guessed.
    assert summary["cost_usd"] is None
    assert "unpriced_models" in summary["cost_status"]
