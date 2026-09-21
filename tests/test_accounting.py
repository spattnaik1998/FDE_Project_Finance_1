"""Token and cost accounting.

The load-bearing property is a refusal: **cost is reported only when a price is
configured.** ``gpt-6-astra`` postdates this project's reference material, so
its price is not known here, and a guessed number inside a customer-facing
spend figure would be worse than no figure. The ledger therefore says
"unpriced" rather than producing a total that quietly omits half the calls.
"""

from __future__ import annotations

import pytest

from providers import accounting
from providers.accounting import Ledger
from providers.base import ModelResponse, Usage

PRICED_MODEL = "test-priced-model"


def response(model: str = PRICED_MODEL, *, tokens_in: int = 1000,
             tokens_out: int = 500, provider: str = "openai",
             duration_ms: int = 1200) -> ModelResponse:
    return ModelResponse(
        provider=provider, model=model, text="x", structured=None,
        usage=Usage(input_tokens=tokens_in, output_tokens=tokens_out),
        duration_ms=duration_ms)


@pytest.fixture
def priced(monkeypatch):
    """$3 per million input, $15 per million output."""
    base = accounting._env_key(PRICED_MODEL)
    monkeypatch.setenv(f"{base}_INPUT", "3.0")
    monkeypatch.setenv(f"{base}_OUTPUT", "15.0")


# --- Usage arithmetic --------------------------------------------------------

def test_usage_adds_componentwise():
    total = (Usage(input_tokens=10, output_tokens=5, cached_input_tokens=2,
                   reasoning_tokens=1)
             + Usage(input_tokens=3, output_tokens=7, cached_input_tokens=1,
                     reasoning_tokens=4))
    assert (total.input_tokens, total.output_tokens) == (13, 12)
    assert total.cached_input_tokens == 3
    assert total.reasoning_tokens == 5


def test_total_tokens_excludes_reasoning_double_counting():
    """Reasoning tokens are already inside output_tokens; do not add twice."""
    usage = Usage(input_tokens=100, output_tokens=200, reasoning_tokens=150)
    assert usage.total_tokens == 300


def test_usage_is_immutable():
    with pytest.raises(Exception):
        Usage(input_tokens=1).input_tokens = 2


# --- Pricing ----------------------------------------------------------------

def test_env_key_normalises_a_model_name():
    assert accounting._env_key("gpt-6-astra") == "PRICE_GPT_6_ASTRA"
    assert accounting._env_key("claude-opus-5") == "PRICE_CLAUDE_OPUS_5"


def test_unpriced_model_yields_no_cost():
    assert accounting.cost_usd("model-with-no-configured-price",
                               Usage(input_tokens=1000, output_tokens=1000)) is None


def test_priced_model_computes_cost(priced):
    cost = accounting.cost_usd(PRICED_MODEL,
                               Usage(input_tokens=1_000_000, output_tokens=1_000_000))
    assert cost == pytest.approx(18.0)


def test_cost_scales_with_tokens(priced):
    cost = accounting.cost_usd(PRICED_MODEL,
                               Usage(input_tokens=1000, output_tokens=500))
    assert cost == pytest.approx(3.0 / 1000 + 15.0 / 2000)


def test_half_configured_price_is_treated_as_unpriced(monkeypatch):
    """An input price with no output price cannot produce a real total."""
    monkeypatch.setenv(f"{accounting._env_key(PRICED_MODEL)}_INPUT", "3.0")
    monkeypatch.delenv(f"{accounting._env_key(PRICED_MODEL)}_OUTPUT", raising=False)
    assert accounting.price_per_million(PRICED_MODEL) is None


def test_malformed_price_is_treated_as_unpriced(monkeypatch, caplog):
    base = accounting._env_key(PRICED_MODEL)
    monkeypatch.setenv(f"{base}_INPUT", "three dollars")
    monkeypatch.setenv(f"{base}_OUTPUT", "15.0")
    with caplog.at_level("WARNING"):
        assert accounting.price_per_million(PRICED_MODEL) is None
    assert any("bad_price_config" in r.getMessage() for r in caplog.records)


# --- The ledger -------------------------------------------------------------

def test_ledger_records_every_call():
    ledger = Ledger(run_id="run-1")
    ledger.record(response(), stage="task_classifier")
    ledger.record(response(), stage="review_gate")
    assert len(ledger.calls) == 2
    assert ledger.total_usage.input_tokens == 2000


def test_ledger_aggregates_by_stage():
    ledger = Ledger()
    ledger.record(response(tokens_in=100), stage="task_classifier")
    ledger.record(response(tokens_in=300), stage="task_classifier")
    ledger.record(response(tokens_in=50), stage="synthesis")
    by_stage = ledger.by_stage()
    assert by_stage["task_classifier"].input_tokens == 400
    assert by_stage["synthesis"].input_tokens == 50


def test_ledger_sums_duration():
    ledger = Ledger()
    ledger.record(response(duration_ms=1000), stage="a")
    ledger.record(response(duration_ms=250), stage="b")
    assert ledger.total_duration_ms == 1250


def test_ledger_total_cost_is_none_when_any_model_is_unpriced(priced):
    """A total that silently omits calls is worse than one marked incomplete."""
    ledger = Ledger()
    ledger.record(response(PRICED_MODEL), stage="a")
    ledger.record(response("gpt-6-astra"), stage="b")

    assert ledger.total_cost_usd is None
    assert ledger.unpriced_models == {"gpt-6-astra"}
    assert "unpriced_models" in ledger.summary()["cost_status"]
    assert "gpt-6-astra" in ledger.summary()["cost_status"]


def test_ledger_total_cost_is_reported_when_everything_is_priced(priced):
    ledger = Ledger()
    ledger.record(response(PRICED_MODEL, tokens_in=1000, tokens_out=500), stage="a")
    ledger.record(response(PRICED_MODEL, tokens_in=1000, tokens_out=500), stage="b")
    assert ledger.total_cost_usd == pytest.approx(2 * (0.003 + 0.0075))
    assert ledger.summary()["cost_status"] == "complete"


def test_empty_ledger_reports_no_calls():
    summary = Ledger().summary()
    assert summary["calls"] == 0
    assert summary["cost_usd"] is None
    assert summary["cost_status"] == "no_calls"


def test_ledger_summary_always_reports_token_counts():
    """Tokens are facts the API returns; they are never withheld for want of a price."""
    ledger = Ledger(run_id="run-9")
    ledger.record(response("gpt-6-astra", tokens_in=134, tokens_out=206), stage="a")
    summary = ledger.summary()
    assert summary["input_tokens"] == 134
    assert summary["output_tokens"] == 206
    assert summary["total_tokens"] == 340
    assert summary["run_id"] == "run-9"
    assert summary["cost_usd"] is None


def test_ledger_records_a_failed_call_with_its_status():
    ledger = Ledger()
    call = ledger.record(response(), stage="review_gate", status="schema_violation")
    assert call.status == "schema_violation"
    assert len(ledger.calls) == 1


def test_recorded_call_carries_the_prompt_version():
    ledger = Ledger()
    call = ledger.record(response(), stage="synthesis", prompt_version="v3")
    assert call.prompt_version == "v3"
