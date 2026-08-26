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
    monkeypatch.setattr(openrouter_models, "_catalogue", None)
    monkeypatch.setattr(openrouter_models, "_catalogue_key", None)
    monkeypatch.setattr(openrouter_models, "_catalogue_fetched_at", 0.0)
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
        "pricing": {
            "prompt": "0.000003",
            "completion": "0.000015",
            "input_cache_read": "0.0000003",
            "input_cache_write": "0.00000375",
        },
        "supported_parameters": [
            "tools",
            "reasoning",
            "reasoning_effort",
            "temperature",
            "top_p",
            "seed",
        ],
        "reasoning": {
            "mandatory": True,
            "default_effort": "high",
            "supported_efforts": ["max", "high", "low"],
        },
    }
    normalized = openrouter_models._normalize_model(raw)
    assert normalized["id"] == "vendor/model"
    assert normalized["context_length"] == 128000
    assert normalized["supports_reasoning"] is True
    assert normalized["supports_tools"] is True
    assert normalized["input_price"] == pytest.approx(0.000003)
    assert normalized["cache_read_price"] == pytest.approx(0.0000003)
    assert normalized["cache_write_price"] == pytest.approx(0.00000375)
    assert normalized["request_parameters"] == ["temperature", "top_p", "seed"]
    assert normalized["reasoning_efforts"] == ["low", "high", "max"]
    assert normalized["default_reasoning_effort"] == "high"
    assert normalized["reasoning_mandatory"] is True


@pytest.mark.parametrize("reasoning", ["invalid", {"supported_efforts": "high"}])
def test_normalize_model_rejects_malformed_reasoning_metadata_safely(reasoning):
    normalized = openrouter_models._normalize_model(
        {
            "id": "vendor/model",
            "supported_parameters": ["reasoning"],
            "reasoning": reasoning,
        }
    )
    assert normalized["reasoning_efforts"] == []
    assert normalized["default_reasoning_effort"] is None


def test_static_fallback_contains_requested_models(fake_home):
    expected_models = {
        "z-ai/glm-5.3",
        "z-ai/glm-5.3-flash",
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "google/gemini-3.7-flash",
        "x-ai/grok-4.6",
        "qwen/qwen3.8-max",
        "bytedance-seed/seed-2.0-code",
        "moonshotai/kimi-k3",
        "anthropic/claude-fable-5",
        "openai/gpt-5.6-luna",
        "openai/gpt-5.6-luna-pro",
        "openai/gpt-5.6-terra",
        "openai/gpt-5.6-terra-pro",
        "openai/gpt-5.6-sol",
        "openai/gpt-5.6-sol-pro",
    }
    fallback_models = {
        model["id"] for model in openrouter_models.get_openrouter_models(allow_network=False)
    }
    assert expected_models <= fallback_models


def test_static_model_metadata_survives_an_older_live_cache(fake_home):
    fake_home.mkdir()
    cached = {
        "fetched_at": time.time(),
        "models": [{"id": "older/model", "name": "Older"}],
    }
    (fake_home / "models_cache.json").write_text(json.dumps(cached))

    model = openrouter_models.find_model("moonshotai/kimi-k3")

    assert model["reasoning_efforts"] == ["low", "high", "max"]
    assert openrouter_models.model_supports_reasoning("moonshotai/kimi-k3") is True


def test_stale_cache_is_explicitly_labelled(fake_home):
    fake_home.mkdir()
    cached = {
        "fetched_at": time.time() - openrouter_models.CACHE_TTL_SECONDS - 1,
        "models": [{"id": "vendor/model", "name": "Stale"}],
    }
    (fake_home / "models_cache.json").write_text(json.dumps(cached))

    _models, status = openrouter_models.get_openrouter_catalogue(allow_network=False)

    assert status.source == "stale-catalogue-cache"
    assert status.stale is True
    assert status.fetched_at.endswith("Z")


def test_catalogue_pricing_takes_precedence_over_static_fallback(fake_home):
    fake_home.mkdir()
    cached = {
        "fetched_at": time.time(),
        "models": [
            {
                "id": "z-ai/glm-5.2",
                "name": "GLM",
                "input_price": 0.0000008,
                "output_price": 0.0000025,
                "cache_read_price": 0.0000002,
            }
        ],
    }
    (fake_home / "models_cache.json").write_text(json.dumps(cached))

    pricing = radsim.config.get_model_pricing("z-ai/glm-5.2", "openrouter")

    assert str(pricing.input_per_million_usd) == "0.8000000"
    assert pricing.source == "catalogue-cache"
    assert pricing.stale is False


def test_malformed_catalogue_price_fails_to_labelled_static_fallback(fake_home):
    fake_home.mkdir()
    cached = {
        "fetched_at": time.time(),
        "models": [
            {
                "id": "z-ai/glm-5.2",
                "name": "GLM",
                "input_price": None,
                "output_price": 0.0000025,
            }
        ],
    }
    (fake_home / "models_cache.json").write_text(json.dumps(cached))

    pricing = radsim.config.get_model_pricing("z-ai/glm-5.2", "openrouter")

    assert pricing.source == "static-fallback"
    assert pricing.stale is True


def test_static_glm_capabilities_cover_verified_sampling_parameters(fake_home):
    assert openrouter_models.get_model_request_parameters("z-ai/glm-5.3-flash") == (
        "temperature",
        "top_p",
        "seed",
    )


def test_static_catalogue_records_the_verified_snapshot_date():
    assert radsim.config.OPENROUTER_CATALOGUE_SNAPSHOT_DATE == "2026-08-28"


def _catalogue_entry(model_id, created, **overrides):
    entry = {
        "id": model_id,
        "name": overrides.get("name", model_id),
        "created": created,
        "architecture": {
            "input_modalities": overrides.get("inputs", ["text"]),
            "output_modalities": overrides.get("outputs", ["text"]),
        },
        "supported_parameters": overrides.get("parameters", ["tools"]),
    }
    return entry


def test_normalize_model_keeps_release_date_and_text_support():
    normalized = openrouter_models._normalize_model(
        _catalogue_entry("vendor/model", 1_750_000_000)
    )

    assert normalized["created"] == 1_750_000_000
    assert normalized["supports_text"] is True


def test_normalize_model_flags_non_text_and_undated_models():
    image_only = openrouter_models._normalize_model(
        _catalogue_entry("vendor/image", 10, outputs=["image"])
    )
    undated = openrouter_models._normalize_model(
        _catalogue_entry("vendor/undated", "not-a-timestamp")
    )

    assert image_only["supports_text"] is False
    assert undated["created"] == 0


def test_selectable_models_are_tool_capable_text_models_newest_first(fake_home, monkeypatch):
    catalogue = [
        openrouter_models._normalize_model(entry)
        for entry in (
            _catalogue_entry("vendor/older", 10),
            _catalogue_entry("vendor/latest", 30, name="Latest"),
            _catalogue_entry("vendor/queued:batch", 50),
            _catalogue_entry("vendor/no-tools", 40, parameters=["temperature"]),
            _catalogue_entry("vendor/image", 60, outputs=["image"]),
        )
    ]
    monkeypatch.setattr(openrouter_models, "_fetch_from_api", lambda: catalogue)

    selectable = openrouter_models.list_selectable_models()

    assert [model["id"] for model in selectable] == ["vendor/latest", "vendor/older"]


def test_selectable_models_keep_static_fallback_when_offline(fake_home, monkeypatch):
    def fail():
        raise TimeoutError("offline")

    monkeypatch.setattr(openrouter_models, "_fetch_from_api", fail)

    selectable = {model["id"] for model in openrouter_models.list_selectable_models()}

    assert "anthropic/claude-opus-5" in selectable
    assert "z-ai/glm-5.3" in selectable


def test_full_openrouter_picker_lists_the_newest_models_first(fake_home, monkeypatch):
    catalogue = [
        openrouter_models._normalize_model(entry)
        for entry in (
            _catalogue_entry("vendor/older", 10, name="Older"),
            _catalogue_entry("vendor/newest", 90, name="Newest"),
            _catalogue_entry("vendor/no-tools", 95, parameters=["temperature"]),
        )
    ]
    monkeypatch.setattr(openrouter_models, "_fetch_from_api", lambda: catalogue)

    choices = radsim.config._build_openrouter_choices(top_only=False)

    assert [model_id for model_id, _label in choices] == ["vendor/newest", "vendor/older"]


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_exception):
        return False

    def read(self, size):
        return self._body[:size]


def test_fetch_keeps_the_catalogue_when_one_model_is_priced_variably(monkeypatch):
    payload = {
        "data": [
            _catalogue_entry("vendor/priced", 20)
            | {"pricing": {"prompt": "0.000003", "completion": "0.000015"}},
            _catalogue_entry("openrouter/auto", 10)
            | {"pricing": {"prompt": "-1", "completion": "-1"}},
        ]
    }
    monkeypatch.setattr(
        openrouter_models.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(payload),
    )

    models = openrouter_models._fetch_from_api()

    assert [model["id"] for model in models] == ["vendor/priced", "openrouter/auto"]
    assert models[1]["input_price"] is None


def test_fetch_rejects_a_catalogue_with_no_usable_models(monkeypatch):
    payload = {"data": [{"id": "", "name": "Nameless"}]}
    monkeypatch.setattr(
        openrouter_models.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(payload),
    )

    with pytest.raises(ValueError):
        openrouter_models._fetch_from_api()


def test_curated_openrouter_list_offers_the_current_frontier_models():
    curated = {model_id for model_id, _label in radsim.config.PROVIDER_MODELS["openrouter"]}

    assert {
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "z-ai/glm-5.3",
        "x-ai/grok-4.6",
        "google/gemini-3.7-flash",
    } <= curated
