"""Tests for global reasoning_effort persistence and threading into API client."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import radsim.config as config_module
from radsim.agent_conversation import AgentConversationMixin
from radsim.api_client import OpenRouterClient
from radsim.config import (
    DEFAULT_REASONING_EFFORT,
    REASONING_EFFORT_LEVELS,
    _maybe_prompt_reasoning_effort,
    get_reasoning_effort_options,
    load_config,
    load_reasoning_effort,
    resolve_reasoning_effort,
    save_reasoning_effort,
)


@pytest.fixture
def fake_settings(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / ".radsim"
    config_dir.mkdir()
    settings_file = config_dir / "settings.json"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(config_module, "ENV_FILE", config_dir / ".env")
    return settings_file


def test_save_and_load_reasoning_effort(fake_settings):
    save_reasoning_effort("low")
    assert load_reasoning_effort() == "low"

    save_reasoning_effort("high")
    assert load_reasoning_effort() == "high"

    saved = json.loads(fake_settings.read_text())
    assert saved["reasoning_effort"] == "high"


def test_invalid_effort_rejected(fake_settings):
    with pytest.raises(ValueError):
        save_reasoning_effort("extreme")


def test_load_default_when_missing(fake_settings):
    assert load_reasoning_effort() == DEFAULT_REASONING_EFFORT


def test_load_default_when_corrupt(fake_settings):
    fake_settings.write_text(json.dumps({"reasoning_effort": "bogus"}))
    assert load_reasoning_effort() == DEFAULT_REASONING_EFFORT


def test_config_threads_reasoning_effort(fake_settings, monkeypatch):
    monkeypatch.setenv("RADSIM_API_KEY", "test-key")
    save_reasoning_effort("low")
    cfg = load_config(provider_override="openai")
    assert cfg.reasoning_effort == "low"


def test_openrouter_client_skips_reasoning_for_unsupported_model(monkeypatch):
    # Stub openai SDK so we don't make real calls
    class _Dummy:
        def __init__(self, **_):
            pass

    monkeypatch.setattr(
        "openai.OpenAI",
        lambda **_: type("C", (), {"chat": None})(),
    )

    client = OpenRouterClient(
        api_key="x",
        model="vendor/no-reasoning",
        reasoning_effort="high",
    )
    monkeypatch.setattr(
        "radsim.openrouter_models.model_supports_reasoning",
        lambda model_id: False,
    )
    kwargs = {"model": client.model, "messages": []}
    client._apply_reasoning(kwargs)
    assert "extra_body" not in kwargs


def test_openrouter_client_attaches_reasoning_for_supported_model(monkeypatch):
    monkeypatch.setattr(
        "openai.OpenAI",
        lambda **_: type("C", (), {"chat": None})(),
    )

    client = OpenRouterClient(
        api_key="x",
        model="vendor/with-reasoning",
        reasoning_effort="low",
    )
    monkeypatch.setattr(
        "radsim.openrouter_models.model_supports_reasoning",
        lambda model_id: True,
    )
    kwargs = {"model": client.model, "messages": []}
    client._apply_reasoning(kwargs)
    assert kwargs["extra_body"]["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_openrouter_chat_sends_selected_reasoning_to_sdk(monkeypatch, effort):
    captured = {}

    def create_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    sdk_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_completion),
        )
    )
    monkeypatch.setattr("openai.OpenAI", lambda **_: sdk_client)
    monkeypatch.setattr(
        "radsim.openrouter_models.model_supports_reasoning",
        lambda model_id: True,
    )
    client = OpenRouterClient(
        api_key="test-key",
        model="openai/gpt-5.6-sol",
        reasoning_effort=effort,
    )

    client.chat([{"role": "user", "content": "test"}])

    assert captured["extra_body"] == {"reasoning": {"effort": effort}}


def test_openrouter_stream_sends_selected_reasoning_to_sdk(monkeypatch):
    captured = {}

    def create_stream(**kwargs):
        captured.update(kwargs)
        return iter(())

    sdk_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_stream),
        )
    )
    monkeypatch.setattr("openai.OpenAI", lambda **_: sdk_client)
    monkeypatch.setattr(
        "radsim.openrouter_models.model_supports_reasoning",
        lambda model_id: True,
    )
    client = OpenRouterClient(
        api_key="test-key",
        model="anthropic/claude-fable-5",
        reasoning_effort="xhigh",
    )

    list(client.stream_chat([{"role": "user", "content": "test"}]))

    assert captured["stream"] is True
    assert captured["extra_body"] == {"reasoning": {"effort": "xhigh"}}


def test_switch_rebuilds_client_with_saved_reasoning(monkeypatch):
    captured = {}
    agent = SimpleNamespace(
        config=SimpleNamespace(
            provider="openrouter",
            api_key="old-key",
            model="z-ai/glm-5.2",
            reasoning_effort="medium",
        )
    )

    def create_client(provider, api_key, model, reasoning_effort=None):
        captured.update(
            provider=provider,
            api_key=api_key,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        return "new-client"

    monkeypatch.setattr("radsim.agent_conversation.create_client", create_client)
    monkeypatch.setattr(config_module, "load_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(
        config_module,
        "resolve_reasoning_effort",
        lambda provider, model, effort: effort,
    )
    monkeypatch.setattr(config_module, "save_config", lambda *args: None)
    monkeypatch.setattr("radsim.agent_conversation.print_success", lambda *args: None)

    AgentConversationMixin.update_config(
        agent,
        "openrouter",
        "new-key",
        "anthropic/claude-fable-5",
    )

    assert captured["reasoning_effort"] == "xhigh"
    assert agent.config.reasoning_effort == "xhigh"
    assert agent.client == "new-client"


def test_requested_models_expose_live_reasoning_levels():
    assert get_reasoning_effort_options(
        "openrouter",
        "moonshotai/kimi-k3",
    ) == ("low", "high", "max")
    assert get_reasoning_effort_options(
        "openrouter",
        "anthropic/claude-fable-5",
    ) == ("low", "medium", "high", "xhigh", "max")
    assert get_reasoning_effort_options(
        "openrouter",
        "openai/gpt-5.6-sol",
    ) == ("none", "low", "medium", "high", "xhigh", "max")


def test_kimi_k3_keeps_a_supported_saved_effort():
    assert resolve_reasoning_effort(
        "openrouter",
        "moonshotai/kimi-k3",
        "low",
    ) == "low"


def test_kimi_k3_selector_persists_the_catalogue_default(fake_settings, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    _maybe_prompt_reasoning_effort("openrouter", "moonshotai/kimi-k3")
    assert load_reasoning_effort() == "max"


def test_levels_constant_matches_documented_set():
    assert REASONING_EFFORT_LEVELS == (
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
