"""Provider selection by stage.

The mapping is the cross-provider independence property from TDD 2: the Review
Gate grading the classifier's work must be a different vendor from the one that
produced it. That is a design commitment, so it gets a test rather than a
comment.
"""

from __future__ import annotations

import pytest

from providers import registry
from providers.anthropic_provider import AnthropicProvider
from providers.base import ModelProvider
from providers.openai_provider import OpenAIProvider
from providers.registry import Stage


@pytest.fixture(autouse=True)
def clear_cache():
    registry.reset()
    yield
    registry.reset()


def test_every_stage_has_a_provider():
    for stage in Stage:
        assert stage in registry.STAGE_PROVIDERS


def test_the_review_gate_is_not_the_same_vendor_as_the_classifier():
    """The independence property: the gate must not grade its own homework."""
    mapping = registry.cross_provider_stages()
    assert mapping[Stage.REVIEW_GATE.value] != mapping[Stage.TASK_CLASSIFIER.value]


def test_intent_and_gate_run_on_anthropic():
    mapping = registry.cross_provider_stages()
    assert mapping[Stage.INTENT_SCOPE.value] == "anthropic"
    assert mapping[Stage.REVIEW_GATE.value] == "anthropic"


def test_classifier_and_writer_run_on_openai():
    mapping = registry.cross_provider_stages()
    assert mapping[Stage.TASK_CLASSIFIER.value] == "openai"
    assert mapping[Stage.SYNTHESIS.value] == "openai"


def test_for_stage_returns_the_right_adapter_type():
    assert isinstance(registry.for_stage(Stage.REVIEW_GATE), AnthropicProvider)
    assert isinstance(registry.for_stage(Stage.TASK_CLASSIFIER), OpenAIProvider)


def test_every_stage_resolves_to_the_shared_interface():
    for stage in Stage:
        assert isinstance(registry.for_stage(stage), ModelProvider)


def test_providers_are_cached_per_stage():
    assert registry.for_stage(Stage.SYNTHESIS) is registry.for_stage(Stage.SYNTHESIS)


def test_reset_clears_the_cache():
    first = registry.for_stage(Stage.SYNTHESIS)
    registry.reset()
    assert registry.for_stage(Stage.SYNTHESIS) is not first


def test_model_names_come_from_config(monkeypatch):
    """The charter forbids hardcoding model names deep in business logic."""
    import config
    monkeypatch.setattr(config, "MODEL_CLASSIFIER", "some-other-model")
    registry.reset()
    assert registry.for_stage(Stage.TASK_CLASSIFIER).model == "some-other-model"


def test_unknown_vendor_is_refused():
    with pytest.raises(registry.ProviderNotConfigured, match="Unknown provider"):
        registry._build("bedrock", "some-model")
