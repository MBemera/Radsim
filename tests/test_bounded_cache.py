"""Hit-rate, invalidation, and bounding tests for the long-lived caches."""

from __future__ import annotations

import json

import pytest

from radsim import user_hooks
from radsim.bounded_cache import DEFAULT_MAX_ENTRIES, MISSING, BoundedCache, path_signature
from radsim.performance import (
    PerformanceTelemetry,
    bind_performance_context,
    reset_performance_context,
)
from radsim.runtime_context import MAX_CACHE_ENTRIES, RuntimeContext
from radsim.tool_schema import (
    canonicalize_tool_schemas,
    clear_schema_cache,
    schema_cache_stats,
)
from radsim.tools import TOOL_DEFINITIONS, registry_version


def test_a_miss_returns_the_sentinel():
    cache = BoundedCache()

    assert cache.get("absent") is MISSING
    assert cache.stats()["misses"] == 1
    assert cache.stats()["hits"] == 0


def test_a_stored_value_is_returned():
    cache = BoundedCache()
    cache.set("key", "value")

    assert cache.get("key") == "value"
    assert cache.stats()["hits"] == 1


def test_the_hit_rate_is_reported():
    cache = BoundedCache()
    cache.set("key", 1)
    cache.get("key")
    cache.get("key")
    cache.get("absent")

    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_rate"] == pytest.approx(2 / 3, abs=1e-4)


def test_the_hit_rate_is_zero_before_any_lookup():
    assert BoundedCache().stats()["hit_rate"] == 0.0


def test_the_hit_rate_keeps_four_decimal_places():
    cache = BoundedCache()
    cache.set("key", 1)
    cache.get("key")
    cache.get("key")
    cache.get("absent")

    assert cache.stats()["hit_rate"] == 0.6667


def test_stats_reports_the_configured_bound():
    assert BoundedCache(max_entries=7).stats()["max_entries"] == 7


def test_the_least_recently_used_entry_is_evicted():
    cache = BoundedCache(max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")
    cache.set("c", 3)

    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.get("b") is MISSING
    assert cache.stats()["evictions"] == 1
    assert cache.stats()["entries"] == 2


def test_overwriting_a_key_does_not_grow_the_cache():
    cache = BoundedCache(max_entries=2)
    cache.set("a", 1)
    cache.set("a", 2)

    assert cache.get("a") == 2
    assert cache.stats()["entries"] == 1
    assert cache.stats()["evictions"] == 0


def test_the_bound_is_never_below_one():
    cache = BoundedCache(max_entries=0)
    cache.set("a", 1)
    cache.set("b", 2)

    assert cache.max_entries == 1
    assert cache.stats()["entries"] == 1


def test_clear_drops_entries_but_keeps_counters():
    cache = BoundedCache()
    cache.set("a", 1)
    cache.get("a")

    cache.clear()

    assert cache.get("a") is MISSING
    assert cache.stats()["entries"] == 0
    assert cache.stats()["hits"] == 1


def test_path_signature_changes_with_content(tmp_path):
    target = tmp_path / "file.json"
    target.write_text("one")
    first = path_signature(target)
    target.write_text("a much longer body than before")

    assert path_signature(target) != first


def test_path_signature_distinguishes_a_missing_file(tmp_path):
    target = tmp_path / "absent.json"

    missing = path_signature(target)
    target.write_text("now here")

    assert missing == (str(target), False, None, None)
    assert path_signature(target)[0] == str(target)
    assert path_signature(target)[1] is True
    assert path_signature(None) is None


def test_two_missing_files_have_different_signatures(tmp_path):
    first = path_signature(tmp_path / "one.json")
    second = path_signature(tmp_path / "two.json")

    assert first != second


def test_schema_canonicalisation_is_cached():
    clear_schema_cache()
    before = schema_cache_stats()["hits"]

    first = canonicalize_tool_schemas(TOOL_DEFINITIONS)
    second = canonicalize_tool_schemas(TOOL_DEFINITIONS)

    assert first == second
    assert schema_cache_stats()["hits"] == before + 1


def test_a_cached_schema_list_cannot_be_corrupted_by_a_caller():
    clear_schema_cache()
    first = canonicalize_tool_schemas(TOOL_DEFINITIONS)
    first.append({"name": "injected"})

    second = canonicalize_tool_schemas(TOOL_DEFINITIONS)

    assert len(second) == len(TOOL_DEFINITIONS)
    assert all(tool["name"] != "injected" for tool in second)


def test_a_different_tool_set_is_a_different_entry():
    clear_schema_cache()

    everything = canonicalize_tool_schemas(TOOL_DEFINITIONS)
    subset = canonicalize_tool_schemas(TOOL_DEFINITIONS[:10])

    assert len(everything) == len(TOOL_DEFINITIONS)
    assert len(subset) == 10


def test_a_registry_change_invalidates_the_cache(monkeypatch):
    clear_schema_cache()
    canonicalize_tool_schemas(TOOL_DEFINITIONS)
    before = schema_cache_stats()["misses"]

    monkeypatch.setattr("radsim.tools.registry_version", lambda: registry_version() + 1)

    canonicalize_tool_schemas(TOOL_DEFINITIONS)

    assert schema_cache_stats()["misses"] == before + 1


def test_duplicate_names_still_raise_through_the_cache():
    clear_schema_cache()
    duplicated = [
        {"name": "read_file", "input_schema": {}},
        {"name": "read_file", "input_schema": {}},
    ]

    with pytest.raises(ValueError):
        canonicalize_tool_schemas(duplicated)


def test_unkeyable_input_still_canonicalises():
    clear_schema_cache()

    result = canonicalize_tool_schemas([{"name": "beta"}, {"name": "alpha"}])

    assert [tool["name"] for tool in result] == ["alpha", "beta"]


def _write_hooks(path, names):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "name": name,
                    "event": "pre_tool",
                    "matcher": "*",
                    "command": "echo hi",
                    "timeout": 5,
                    "enabled": True,
                }
                for name in names
            ]
        )
    )


def test_hook_discovery_is_cached(tmp_path, monkeypatch):
    hooks_file = tmp_path / "hooks.json"
    _write_hooks(hooks_file, ["first"])
    monkeypatch.setattr(user_hooks, "HOOKS_FILE", hooks_file)
    user_hooks.clear_hook_cache()
    before = user_hooks.hook_cache_stats()["hits"]

    first = user_hooks.load_user_hooks()
    second = user_hooks.load_user_hooks()

    assert [hook.name for hook in first] == ["first"]
    assert [hook.name for hook in second] == ["first"]
    assert user_hooks.hook_cache_stats()["hits"] == before + 1


def test_an_external_edit_invalidates_the_hook_cache(tmp_path, monkeypatch):
    hooks_file = tmp_path / "hooks.json"
    _write_hooks(hooks_file, ["first"])
    monkeypatch.setattr(user_hooks, "HOOKS_FILE", hooks_file)
    user_hooks.clear_hook_cache()
    user_hooks.load_user_hooks()

    _write_hooks(hooks_file, ["first", "second"])

    assert [hook.name for hook in user_hooks.load_user_hooks()] == ["first", "second"]


def test_a_created_hooks_file_invalidates_the_cache(tmp_path, monkeypatch):
    hooks_file = tmp_path / "hooks.json"
    monkeypatch.setattr(user_hooks, "HOOKS_FILE", hooks_file)
    user_hooks.clear_hook_cache()

    assert user_hooks.load_user_hooks() == []

    _write_hooks(hooks_file, ["appeared"])

    assert [hook.name for hook in user_hooks.load_user_hooks()] == ["appeared"]


def test_saving_hooks_invalidates_the_cache(tmp_path, monkeypatch):
    hooks_file = tmp_path / "hooks.json"
    _write_hooks(hooks_file, ["first"])
    monkeypatch.setattr(user_hooks, "HOOKS_FILE", hooks_file)
    user_hooks.clear_hook_cache()
    loaded = user_hooks.load_user_hooks()

    user_hooks.save_user_hooks(loaded[:0])

    assert user_hooks.load_user_hooks() == []


def test_a_caller_cannot_mutate_the_cached_hook_list(tmp_path, monkeypatch):
    hooks_file = tmp_path / "hooks.json"
    _write_hooks(hooks_file, ["first"])
    monkeypatch.setattr(user_hooks, "HOOKS_FILE", hooks_file)
    user_hooks.clear_hook_cache()

    user_hooks.load_user_hooks().clear()

    assert len(user_hooks.load_user_hooks()) == 1


def test_the_runtime_context_caches_are_bounded():
    context = RuntimeContext()

    for index in range(MAX_CACHE_ENTRIES + 10):
        context.get_cached_prompt_fragment(f"key-{index}", [], lambda: "content")

    stats = context.cache_stats()["prompt_fragment"]
    assert stats["entries"] == MAX_CACHE_ENTRIES
    assert stats["evictions"] == 10


def test_a_prompt_fragment_is_rebuilt_when_its_file_changes(tmp_path):
    context = RuntimeContext()
    source = tmp_path / "fragment.md"
    source.write_text("first body")
    builds = []

    def build():
        builds.append(source.read_text())
        return builds[-1]

    assert context.get_cached_prompt_fragment("fragment", [source], build) == "first body"
    assert context.get_cached_prompt_fragment("fragment", [source], build) == "first body"

    source.write_text("a replacement body of different length")

    assert "replacement" in context.get_cached_prompt_fragment("fragment", [source], build)
    assert len(builds) == 2


def test_project_detection_results_are_isolated_copies(tmp_path):
    context = RuntimeContext()

    first = context.get_cached_project_detection("kind", [], lambda: {"type": "python"})
    first["type"] = "mutated"
    second = context.get_cached_project_detection("kind", [], lambda: {"type": "python"})

    assert second["type"] == "python"


def test_cache_stats_reports_every_cache():
    stats = RuntimeContext().cache_stats()

    assert set(stats) == {"project_detection", "prompt_fragment", "tool_schema", "user_hooks"}
    for entry in stats.values():
        assert {"entries", "hits", "misses", "evictions", "hit_rate"} <= set(entry)


def test_clear_all_empties_every_cache():
    context = RuntimeContext()
    context.get_cached_prompt_fragment("key", [], lambda: "content")
    canonicalize_tool_schemas(TOOL_DEFINITIONS)

    context.clear_all()

    stats = context.cache_stats()
    assert stats["prompt_fragment"]["entries"] == 0
    assert stats["tool_schema"]["entries"] == 0


def test_the_default_bound_is_documented():
    assert DEFAULT_MAX_ENTRIES == 64


def test_turn_cache_statistics_are_emitted(tmp_path):
    from radsim.agent_conversation import _emit_cache_stats

    path = tmp_path / "cache.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)
    token = bind_performance_context(telemetry, "turn-1")
    try:
        _emit_cache_stats(telemetry, "turn-1")
    finally:
        reset_performance_context(token)

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {record["cache_name"] for record in records} == {
        "project_detection",
        "prompt_fragment",
        "tool_schema",
        "user_hooks",
    }
    for record in records:
        assert record["event"] == "cache_stats"
        assert record["cache_entries"] >= 0


def test_disabled_telemetry_records_no_cache_statistics(tmp_path):
    from radsim.agent_conversation import _emit_cache_stats

    path = tmp_path / "off.jsonl"
    _emit_cache_stats(PerformanceTelemetry(path, enabled=False), "turn-1")

    assert not path.exists()
