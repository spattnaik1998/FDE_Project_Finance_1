"""Token and cost accounting per run.

Token counts are facts the API reports and are always recorded. **Cost is
only reported when a price is configured**, because this project does not know
what ``gpt-6-astra`` costs — the model postdates its reference material — and
an invented price in a customer-facing spend figure would be worse than no
figure at all.

Prices come from the environment, in dollars per million tokens:

    PRICE_GPT_6_ASTRA_INPUT=...
    PRICE_GPT_6_ASTRA_OUTPUT=...
    PRICE_CLAUDE_OPUS_5_INPUT=...
    PRICE_CLAUDE_OPUS_5_OUTPUT=...

Unpriced models accumulate tokens with ``cost_usd`` left as ``None``, and the
ledger says which models were unpriced rather than quietly reporting a total
that excludes them.
"""

from __future__ import annotations

import logging
import threading
import os
import re
from dataclasses import dataclass, field

from providers.base import ModelResponse, Usage

LOG = logging.getLogger("providers.accounting")

PER_MILLION = 1_000_000


def _env_key(model: str) -> str:
    return "PRICE_" + re.sub(r"[^A-Z0-9]+", "_", model.upper()).strip("_")


def price_per_million(model: str) -> tuple[float, float] | None:
    """Configured (input, output) price per million tokens, or None."""
    base = _env_key(model)
    raw_in = os.environ.get(f"{base}_INPUT")
    raw_out = os.environ.get(f"{base}_OUTPUT")
    if raw_in is None or raw_out is None:
        return None
    try:
        return float(raw_in), float(raw_out)
    except ValueError:
        LOG.warning("model=%s status=bad_price_config input=%r output=%r",
                    model, raw_in, raw_out)
        return None


def cost_usd(model: str, usage: Usage) -> float | None:
    """Cost of one call, or ``None`` when the model has no configured price."""
    prices = price_per_million(model)
    if prices is None:
        return None
    price_in, price_out = prices
    return round(
        (usage.input_tokens / PER_MILLION) * price_in
        + (usage.output_tokens / PER_MILLION) * price_out, 6)


@dataclass
class ModelCall:
    """One recorded call, for the audit trail and the spend report."""

    provider: str
    model: str
    stage: str
    prompt_version: str
    usage: Usage
    duration_ms: int
    cost_usd: float | None
    status: str = "ok"


@dataclass
class Ledger:
    """Accumulated spend for one run.

    Reports unpriced models explicitly. A total that silently omits half the
    calls is a worse artefact than a total marked incomplete.
    """

    run_id: str | None = None
    calls: list[ModelCall] = field(default_factory=list)
    # The classifier fans out across threads, so several calls can land at once.
    # list.append happens to be atomic under CPython's GIL, but relying on an
    # implementation detail for an accounting record is the kind of thing that
    # is fine until it is not. The lock costs nothing and makes the guarantee
    # explicit rather than incidental.
    _lock: "threading.Lock" = field(default_factory=lambda: threading.Lock(),
                                    repr=False, compare=False)

    def record(self, response: ModelResponse, *, stage: str,
               prompt_version: str = "v1", status: str = "ok") -> ModelCall:
        call = ModelCall(
            provider=response.provider, model=response.model, stage=stage,
            prompt_version=prompt_version, usage=response.usage,
            duration_ms=response.duration_ms,
            cost_usd=cost_usd(response.model, response.usage), status=status)
        with self._lock:
            self.calls.append(call)
        return call

    # -- aggregates --------------------------------------------------------

    @property
    def total_usage(self) -> Usage:
        total = Usage()
        for call in self.calls:
            total = total + call.usage
        return total

    @property
    def unpriced_models(self) -> set[str]:
        return {c.model for c in self.calls if c.cost_usd is None}

    @property
    def total_cost_usd(self) -> float | None:
        """Total spend, or ``None`` if any call was unpriced."""
        if not self.calls or self.unpriced_models:
            return None
        return round(sum(c.cost_usd or 0.0 for c in self.calls), 6)

    @property
    def total_duration_ms(self) -> int:
        """Summed provider time across calls -- NOT elapsed wall clock.

        Named precisely because the difference misled a decision. With the
        classifier running concurrently, 26 calls of ~6s each still sum to ~160s
        while the run finishes in under 40, so reporting this as "duration" made
        a 5x speed-up look like no change at all. It is a useful number -- it is
        what the provider billed time against -- but it is not how long anyone
        waited.
        """
        return sum(c.duration_ms for c in self.calls)

    @property
    def max_duration_ms(self) -> int:
        """The slowest single call, a lower bound on any run's wall clock."""
        return max((c.duration_ms for c in self.calls), default=0)

    def by_stage(self) -> dict[str, Usage]:
        out: dict[str, Usage] = {}
        for call in self.calls:
            out[call.stage] = out.get(call.stage, Usage()) + call.usage
        return out

    def summary(self) -> dict:
        usage = self.total_usage
        cost = self.total_cost_usd
        return {
            "run_id": self.run_id,
            "calls": len(self.calls),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "total_tokens": usage.total_tokens,
            # Renamed from "duration_ms": it is summed provider time, not
            # elapsed time, and the old name invited exactly the wrong reading.
            "provider_time_ms": self.total_duration_ms,
            "slowest_call_ms": self.max_duration_ms,
            "cost_usd": cost,
            "cost_status": "complete" if cost is not None else (
                "unpriced_models: " + ", ".join(sorted(self.unpriced_models))
                if self.unpriced_models else "no_calls"),
        }
