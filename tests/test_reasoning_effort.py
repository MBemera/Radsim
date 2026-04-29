"""Tests for global reasoning_effort persistence and threading into API client."""

import json
from pathlib import Path

import pytest

import radsim.config as config_module
from radsim.api_client import OpenRouterClient
from radsim.config import (
    DEFAULT_REASONING_EFFORT,
    REASONING_EFFORT_LEVELS,
    load_reasoning_effort,
    load_config,
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


def test_levels_constant_matches_documented_set():
    assert REASONING_EFFORT_LEVELS == ("low", "medium", "high")
