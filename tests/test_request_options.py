"""Offline request-shape contracts for explicit sampling controls."""

from dataclasses import FrozenInstanceError

import pytest

from radsim.api_client import ClaudeClient, OpenAIClient, OpenRouterClient
from radsim.request_options import RequestOptions


def build_client(client_class, model="test-model"):
    client = client_class.__new__(client_class)
    client.model = model
    client.reasoning_effort = None
    return client


def test_request_options_are_immutable_and_filter_without_changing_values():
    options = RequestOptions(temperature=0.25, top_p=0.9, seed=42)

    assert options.for_supported({"temperature", "seed"}) == {
        "temperature": 0.25,
        "seed": 42,
    }
    with pytest.raises(FrozenInstanceError):
        options.seed = 43


@pytest.mark.parametrize(
    "overrides",
    [
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"temperature": float("nan")},
        {"top_p": -0.1},
        {"top_p": 1.1},
        {"top_p": float("inf")},
        {"seed": -1},
        {"seed": 2**32},
        {"seed": True},
    ],
)
def test_invalid_request_options_fail_before_provider_io(overrides):
    with pytest.raises(ValueError):
        RequestOptions(**overrides)


def test_claude_sends_supported_options_and_omits_seed():
    client = build_client(ClaudeClient, "claude-sonnet-4-6")
    options = RequestOptions(temperature=0.2, top_p=0.8, seed=42)

    kwargs = client._build_request_kwargs(
        [{"role": "user", "content": "hello"}],
        request_options=options,
    )

    assert kwargs["temperature"] == 0.2
    assert kwargs["top_p"] == 0.8
    assert "seed" not in kwargs


def test_openai_omits_options_without_validated_model_capabilities():
    client = build_client(OpenAIClient, "gpt-5.4")
    options = RequestOptions(temperature=0.2, top_p=0.8, seed=42)

    kwargs = client._build_request_kwargs(
        [{"role": "user", "content": "hello"}],
        request_options=options,
    )

    assert not {"temperature", "top_p", "seed"} & kwargs.keys()


@pytest.mark.parametrize("stream", [False, True])
def test_openrouter_sends_supported_values_unchanged_for_chat_and_stream(stream):
    client = build_client(OpenRouterClient, "z-ai/glm-5.2")
    client._request_parameter_support = frozenset({"temperature", "top_p", "seed"})
    options = RequestOptions(temperature=0.0, top_p=1.0, seed=20260804)

    kwargs = client._build_request_kwargs(
        [{"role": "user", "content": "hello"}],
        stream=stream,
        request_options=options,
    )

    assert kwargs["temperature"] == 0.0
    assert kwargs["top_p"] == 1.0
    assert kwargs["seed"] == 20260804
    assert kwargs.get("stream", False) is stream


def test_openrouter_omits_each_unsupported_option():
    client = build_client(OpenRouterClient, "vendor/model")
    client._request_parameter_support = frozenset({"temperature"})

    kwargs = client._build_request_kwargs(
        [{"role": "user", "content": "hello"}],
        request_options=RequestOptions(temperature=0.3, top_p=0.7, seed=7),
    )

    assert kwargs["temperature"] == 0.3
    assert "top_p" not in kwargs
    assert "seed" not in kwargs


def test_capability_snapshot_records_requested_to_applied_resolution():
    client = build_client(OpenRouterClient, "vendor/model")
    client._request_parameter_support = frozenset({"temperature", "seed"})
    options = RequestOptions(temperature=0.3, top_p=0.7, seed=7)

    snapshot = client.request_options_snapshot(options)

    assert snapshot == {
        "supported_parameters": ["seed", "temperature"],
        "applied": {"temperature": 0.3, "seed": 7},
    }


def test_openrouter_capability_lookup_is_cached_per_client(monkeypatch):
    client = build_client(OpenRouterClient, "vendor/model")
    lookups = []
    monkeypatch.setattr(
        "radsim.openrouter_models.get_model_request_parameters",
        lambda model: lookups.append(model) or ("seed",),
    )

    first = client._supported_request_parameters()
    second = client._supported_request_parameters()

    assert first == second == frozenset({"seed"})
    assert lookups == ["vendor/model"]


def test_product_default_request_shape_is_unchanged():
    client = build_client(OpenRouterClient, "z-ai/glm-5.2")
    client._request_parameter_support = frozenset({"temperature", "top_p", "seed"})

    kwargs = client._build_request_kwargs([{"role": "user", "content": "hello"}])

    assert not {"temperature", "top_p", "seed"} & kwargs.keys()
