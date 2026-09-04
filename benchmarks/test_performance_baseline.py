"""Repeatable local CPU and persistence baselines for RadSim."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from radsim.learning.events import LearningEvent, TaskOutcome
from radsim.learning.retrieval import rank_learning_events
from radsim.learning.store import LearningStore
from radsim.performance import PerformanceTelemetry, request_payload_metrics
from radsim.prompt_cache import plan_system_cache
from radsim.prompts import get_system_prompt
from radsim.tool_router import estimate_schema_tokens, route_tool_schemas
from radsim.tool_schema import canonicalize_tool_schemas
from radsim.tools import TOOL_DEFINITIONS

pytestmark = pytest.mark.benchmark


def _learning_events(count):
    created_at = datetime.now(timezone.utc).isoformat()
    return [
        LearningEvent.create(
            event_id=f"event-{index}",
            task_id=f"task-{index}",
            event_type="task_completion",
            task_category="bug_fix" if index % 2 else "feature",
            tool_name="run_tests" if index % 3 else "read_file",
            outcome=TaskOutcome.SUCCESSFUL,
            summary=(
                f"Fix Python validation failure {index} and run focused tests "
                "for tool schema handling"
            ),
            metadata={"tools_used": ["read_file", "run_tests"]},
            created_at=created_at,
        )
        for index in range(count)
    ]


def _fresh_events(count, offset):
    return [
        LearningEvent.create(
            event_id=f"write-{offset}-{index}",
            task_id=f"write-task-{offset}-{index}",
            event_type="tool_execution",
            task_category="test",
            tool_name="run_tests",
            outcome=TaskOutcome.SUCCESSFUL,
            summary="Run focused performance verification",
        )
        for index in range(count)
    ]


def test_warm_prompt_construction(benchmark):
    get_system_prompt()
    result = benchmark(get_system_prompt)
    assert result


def test_tool_schema_canonicalisation_cold(benchmark):
    from radsim.tool_schema import clear_schema_cache

    def canonicalise_uncached():
        clear_schema_cache()
        return canonicalize_tool_schemas(TOOL_DEFINITIONS)

    result = benchmark(canonicalise_uncached)
    assert len(result) == len(TOOL_DEFINITIONS)


def test_tool_schema_canonicalisation_warm(benchmark):
    canonicalize_tool_schemas(TOOL_DEFINITIONS)
    result = benchmark(canonicalize_tool_schemas, TOOL_DEFINITIONS)
    assert len(result) == len(TOOL_DEFINITIONS)


@pytest.mark.parametrize(
    "request_text",
    [
        "read the config and run the failing tests",
        "commit the branch then deploy the docker container",
    ],
)
def test_tool_schema_routing(benchmark, request_text):
    decision = benchmark(route_tool_schemas, TOOL_DEFINITIONS, request_text)
    assert decision.failed is False
    assert decision.schema_tokens < estimate_schema_tokens(list(TOOL_DEFINITIONS))


def test_system_cache_planning(benchmark):
    prompt = get_system_prompt()
    plan = benchmark(
        plan_system_cache,
        prompt,
        model="claude-opus-4-8",
        tool_schema_tokens=1_675,
    )
    assert plan.is_cached


def test_provider_payload_metrics(benchmark):
    prompt = get_system_prompt()
    result = benchmark(request_payload_metrics, prompt, TOOL_DEFINITIONS)
    assert result["tool_schema_count"] == len(TOOL_DEFINITIONS)


@pytest.mark.parametrize("event_count", [500, 2_000])
def test_fts5_candidate_retrieval(benchmark, tmp_path, event_count):
    from radsim.learning.retrieval import tokenize
    from radsim.learning.store import fts5_available

    if not fts5_available():
        pytest.skip("SQLite build has no FTS5 support")

    store = LearningStore(
        storage_dir=tmp_path / f"fts5-{event_count}",
        max_events=10_000,
        migrate_legacy=False,
    )
    store.append_many(_learning_events(event_count))
    terms = tokenize("fix validation failure and run tests")
    store.search_events(terms, event_types={"task_completion"}, limit=20)

    result = benchmark(
        store.search_events,
        terms,
        event_types={"task_completion"},
        limit=20,
    )
    assert len(result) <= 20


@pytest.mark.parametrize("event_count", [500, 2_000])
def test_learning_ranking(benchmark, event_count):
    events = _learning_events(event_count)
    result = benchmark(
        rank_learning_events,
        "fix validation failure and run tests",
        events,
        task_category="bug_fix",
        limit=5,
    )
    assert len(result) == 5


def test_twenty_individual_learning_writes(benchmark, tmp_path):
    store = LearningStore(
        storage_dir=tmp_path / "individual",
        max_events=10_000,
        migrate_legacy=False,
    )
    offset = 0

    def append_individually():
        nonlocal offset
        events = _fresh_events(20, offset)
        offset += 1
        for event in events:
            store.append(event)
        return len(events)

    result = benchmark.pedantic(append_individually, rounds=10, iterations=1)
    assert result == 20


def test_twenty_batched_learning_writes(benchmark, tmp_path):
    store = LearningStore(
        storage_dir=tmp_path / "batched",
        max_events=10_000,
        migrate_legacy=False,
    )
    offset = 0

    def append_batch():
        nonlocal offset
        events = _fresh_events(20, offset)
        offset += 1
        return store.append_many(events)

    result = benchmark.pedantic(append_batch, rounds=10, iterations=1)
    assert result == 20


def test_buffered_learning_writes(benchmark, tmp_path):
    from radsim.learning.buffer import LearningEventBuffer

    store = LearningStore(
        storage_dir=tmp_path / "buffered",
        max_events=10_000,
        migrate_legacy=False,
    )
    buffer = LearningEventBuffer(store, flush_threshold=1_000)
    offset = 0

    def buffer_and_flush():
        nonlocal offset
        events = _fresh_events(20, offset)
        offset += 1
        for event in events:
            buffer.add(event)
        return buffer.flush()

    result = benchmark.pedantic(buffer_and_flush, rounds=10, iterations=1)
    assert result == 20


def test_disabled_telemetry_emit(benchmark, tmp_path):
    telemetry = PerformanceTelemetry(tmp_path / "disabled.jsonl", enabled=False)
    result = benchmark(
        telemetry.emit,
        "tool_execution",
        turn_id="turn-1",
        tool_name="read_file",
        duration_ms=1.0,
        success=True,
    )
    assert result is False
