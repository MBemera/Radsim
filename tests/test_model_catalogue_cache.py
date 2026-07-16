"""Security and in-memory caching tests for the OpenRouter catalogue."""

import json
import os
import time
from pathlib import Path

import pytest

import radsim.config
import radsim.openrouter_models as openrouter_models


@pytest.fixture
def catalogue_cache(tmp_path, monkeypatch):
    config_directory = tmp_path / ".radsim"
    config_directory.mkdir()
    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_directory)
    monkeypatch.setattr(openrouter_models, "_catalogue", None)
    monkeypatch.setattr(openrouter_models, "_catalogue_key", None)
    monkeypatch.setattr(openrouter_models, "_catalogue_fetched_at", 0.0)
    return config_directory / "models_cache.json"


def write_cache(cache_path, models):
    payload = {"fetched_at": time.time(), "models": models}
    cache_path.write_text(json.dumps(payload))


def test_second_lookup_does_not_reread_unchanged_file(
    catalogue_cache, monkeypatch
):
    write_cache(catalogue_cache, [{"id": "cached/model", "name": "Cached"}])
    original_read_text = Path.read_text
    read_calls = 0

    def counting_read_text(path, *args, **kwargs):
        nonlocal read_calls
        read_calls += 1
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    first_models = openrouter_models.get_openrouter_models(allow_network=False)
    second_models = openrouter_models.get_openrouter_models(allow_network=False)

    assert first_models == second_models
    assert read_calls == 1


def test_changed_cache_file_invalidates_memory(catalogue_cache):
    write_cache(catalogue_cache, [{"id": "vendor/model-a", "name": "Model A"}])
    first_models = openrouter_models.get_openrouter_models(allow_network=False)
    original_stat = catalogue_cache.stat()

    write_cache(catalogue_cache, [{"id": "vendor/model-b", "name": "Model B"}])
    changed_mtime = max(time.time_ns(), original_stat.st_mtime_ns + 1_000_000)
    os.utime(catalogue_cache, ns=(changed_mtime, changed_mtime))
    second_models = openrouter_models.get_openrouter_models(allow_network=False)

    assert first_models[0]["id"] == "vendor/model-a"
    assert second_models[0]["id"] == "vendor/model-b"


def test_context_limit_never_fetches_for_malformed_cache(
    catalogue_cache, monkeypatch
):
    catalogue_cache.write_text("{malformed")
    monkeypatch.setattr(
        openrouter_models,
        "_fetch_from_api",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected network call")),
    )

    context_limit = radsim.config.get_context_limit("unknown/model", default=321)

    assert context_limit == 321


@pytest.mark.parametrize(
    "payload",
    [
        {"fetched_at": time.time(), "models": "not-a-list"},
        {"fetched_at": time.time(), "models": [{"id": "", "name": "Missing ID"}]},
        {
            "fetched_at": time.time(),
            "models": [{"id": "vendor/model", "name": "x" * 513}],
        },
        {
            "fetched_at": time.time(),
            "models": [{"id": "vendor/model", "context_length": -1}],
        },
        {
            "fetched_at": time.time(),
            "models": [{"id": "vendor/model", "input_price": True}],
        },
    ],
)
def test_invalid_cache_payloads_fail_validation(payload):
    assert openrouter_models._is_valid_cache(payload) is False


def test_cache_write_is_atomic_and_leaves_no_temp_file(catalogue_cache):
    models = [{"id": "cached/model", "name": "Cached"}]

    openrouter_models._save_cache(models)

    saved_payload = json.loads(catalogue_cache.read_text())
    temp_files = list(catalogue_cache.parent.glob(".models_cache.json.*.tmp"))
    assert saved_payload["models"] == models
    assert temp_files == []
