"""Tests for radsim.openrouter_models — caching and fallback."""

import json
import time
from pathlib import Path

import pytest

import radsim.config
import radsim.openrouter_models as openrouter_models


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / ".radsim"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    return config_dir


def test_get_models_uses_fresh_cache(fake_home, monkeypatch):
    fake_home.mkdir()
    cached = {
        "fetched_at": time.time(),
        "models": [{"id": "cached/model", "name": "Cached", "supports_reasoning": False}],
    }
    (fake_home / "models_cache.json").write_text(json.dumps(cached))

    def boom():
        raise AssertionError("Should not call API when cache is fresh")

    monkeypatch.setattr(openrouter_models, "_fetch_from_api", boom)
    models = openrouter_models.get_openrouter_models()
    assert models == cached["models"]


def test_get_models_refetches_when_stale(fake_home, monkeypatch):
    fake_home.mkdir()
    stale = {
        "fetched_at": time.time() - openrouter_models.CACHE_TTL_SECONDS - 1,
        "models": [{"id": "stale/model", "name": "Stale"}],
    }
    (fake_home / "models_cache.json").write_text(json.dumps(stale))

    fresh = [{"id": "live/model", "name": "Live", "supports_reasoning": True}]
    monkeypatch.setattr(openrouter_models, "_fetch_from_api", lambda: fresh)

    models = openrouter_models.get_openrouter_models()
    assert models == fresh

    saved = json.loads((fake_home / "models_cache.json").read_text())
    assert saved["models"] == fresh


def test_falls_back_to_static_when_no_cache_and_no_network(fake_home, monkeypatch):
    def fail():
        raise TimeoutError("offline")

    monkeypatch.setattr(openrouter_models, "_fetch_from_api", fail)
    models = openrouter_models.get_openrouter_models()
    assert models, "expected static fallback to be non-empty"
    assert all("id" in m for m in models)


def test_model_supports_reasoning_lookup(fake_home, monkeypatch):
    fake_home.mkdir()
    cached = {
        "fetched_at": time.time(),
        "models": [
            {"id": "with-reasoning", "name": "x", "supports_reasoning": True},
            {"id": "without-reasoning", "name": "y", "supports_reasoning": False},
        ],
    }
    (fake_home / "models_cache.json").write_text(json.dumps(cached))

    assert openrouter_models.model_supports_reasoning("with-reasoning") is True
    assert openrouter_models.model_supports_reasoning("without-reasoning") is False
    assert openrouter_models.model_supports_reasoning("missing") is False


def test_normalize_model_extracts_supported_params():
    raw = {
        "id": "vendor/model",
        "name": "Vendor Model",
        "context_length": 128000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "supported_parameters": ["tools", "reasoning"],
    }
    normalized = openrouter_models._normalize_model(raw)
    assert normalized["id"] == "vendor/model"
    assert normalized["context_length"] == 128000
    assert normalized["supports_reasoning"] is True
    assert normalized["supports_tools"] is True
    assert normalized["input_price"] == pytest.approx(0.000003)
