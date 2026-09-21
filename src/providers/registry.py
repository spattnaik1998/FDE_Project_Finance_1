"""Provider selection by stage, so callers never name a vendor.

The stage-to-provider mapping is the cross-provider independence property from
TDD 2: Intent & Scope and the Review Gate run on Anthropic, the classifier and
writer on OpenAI. The gate grading the classifier's work is therefore a
different model from the one that produced it.

Callers ask ``for_stage(Stage.REVIEW_GATE)``. If that mapping later changes,
it changes here and nowhere else.
"""

from __future__ import annotations

import logging
from enum import Enum
from functools import lru_cache

import config
from providers.anthropic_provider import AnthropicProvider
from providers.base import ModelProvider
from providers.openai_provider import OpenAIProvider

LOG = logging.getLogger("providers.registry")


class Stage(str, Enum):
    """The orchestration nodes that make model calls (TDD 2)."""

    INTENT_SCOPE = "intent_scope"
    TASK_CLASSIFIER = "task_classifier"
    REVIEW_GATE = "review_gate"
    SYNTHESIS = "synthesis"


# Which provider serves which stage, and with which configured model.
STAGE_PROVIDERS: dict[Stage, tuple[str, str]] = {
    Stage.INTENT_SCOPE: ("anthropic", "MODEL_ORCHESTRATOR"),
    Stage.REVIEW_GATE: ("anthropic", "MODEL_REVIEW_GATE"),
    Stage.TASK_CLASSIFIER: ("openai", "MODEL_CLASSIFIER"),
    Stage.SYNTHESIS: ("openai", "MODEL_WRITER"),
}


class ProviderNotConfigured(RuntimeError):
    """A stage was requested but its credential is absent."""


def _build(vendor: str, model: str) -> ModelProvider:
    keys = config.load_keys(include_models=True)
    if vendor == "anthropic":
        return AnthropicProvider(api_key=keys["ANTHROPIC_API_KEY"], model=model)
    if vendor == "openai":
        return OpenAIProvider(api_key=keys["OPENAI_API_KEY"], model=model)
    raise ProviderNotConfigured(f"Unknown provider vendor: {vendor!r}")


@lru_cache(maxsize=None)
def for_stage(stage: Stage) -> ModelProvider:
    """Return the provider configured for this stage."""
    if stage not in STAGE_PROVIDERS:
        raise ProviderNotConfigured(f"No provider mapped for stage {stage!r}")
    vendor, model_attr = STAGE_PROVIDERS[stage]
    model = getattr(config, model_attr)
    provider = _build(vendor, model)
    LOG.info("stage=%s provider=%s model=%s", stage.value, vendor, model)
    return provider


def reset() -> None:
    """Clear the cache. Used by tests that patch configuration."""
    for_stage.cache_clear()


def cross_provider_stages() -> dict[str, str]:
    """Which vendor serves each stage -- for asserting the independence holds."""
    return {stage.value: vendor for stage, (vendor, _) in STAGE_PROVIDERS.items()}
