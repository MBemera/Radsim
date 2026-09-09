"""Transaction, order, atomicity, and bounding tests for batched learning writes."""

from __future__ import annotations

import json
import sqlite3
import threading
import time

import pytest

from radsim.learning.buffer import (
    DEFAULT_FLUSH_THRESHOLD,
    LearningEventBuffer,
)
from radsim.learning.events import LearningEvent, TaskOutcome
from radsim.learning.retrieval import ToolOptimizer
from radsim.learning.store import LearningStore
from radsim.performance import (
    PerformanceTelemetry,
    bind_performance_context,
    reset_performance_context,
)


def _store(tmp_path, name="events"):
    return LearningStore(storage_dir=tmp_path / name, max_events=10_000, migrate_legacy=False)


def _event(index, *, event_type="tool_execution"):
    return LearningEvent.create(
        event_id=f"event-{index:04d}",
        task_id=f"task-{index}",
        event_type=event_type,
        task_category="test",
        tool_name="read_file",
        outcome=TaskOutcome.SUCCESSFUL,
        summary=f"buffered event {index}",
    )


def _stored_ids(store):
    return [event.event_id for event in store.query(limit=1_000)]


def test_add_queues_without_writing(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)

    assert buffer.add(_event(0)) is True

    assert buffer.pending_count == 1
    assert store.count() == 0


def test_flush_writes_every_queued_event(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)
    for index in range(5):
        buffer.add(_event(index))

    assert buffer.flush() == 5
    assert buffer.pending_count == 0
    assert store.count() == 5


def test_flush_uses_a_single_transaction(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)
    commits = []
    original_connect = store._connect

    def counting_connect():
        connection = original_connect()
        commits.append(connection)
        return connection

    store._connect = counting_connect
    for index in range(10):
        buffer.add(_event(index))
    buffer.flush()

    assert len(commits) == 1
    assert store.count() == 10


def test_flush_preserves_insertion_order(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)
    for index in range(25):
        buffer.add(_event(index))
    buffer.flush()

    assert _stored_ids(store) == sorted(_stored_ids(store))
    with sqlite3.connect(store.db_path) as connection:
        rowids = connection.execute(
            "SELECT event_id FROM learning_events ORDER BY rowid"
        ).fetchall()
    assert [row[0] for row in rowids] == [f"event-{index:04d}" for index in range(25)]


def test_add_auto_flushes_at_the_threshold(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store, flush_threshold=4)

    for index in range(3):
        buffer.add(_event(index))
    assert store.count() == 0

    buffer.add(_event(3))

    assert store.count() == 4
    assert buffer.pending_count == 0


def test_empty_flush_writes_nothing(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)

    assert buffer.flush() == 0
    assert store.count() == 0


def test_repeated_flush_is_idempotent(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)
    buffer.add(_event(0))

    assert buffer.flush() == 1
    assert buffer.flush() == 0
    assert store.count() == 1


def test_duplicate_event_ids_are_ignored_not_duplicated(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)
    buffer.add(_event(0))
    buffer.add(_event(0))

    assert buffer.flush() == 1
    assert store.count() == 1


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        "not an event",
        {"event_id": "x"},
        42,
    ],
)
def test_malformed_events_are_rejected_before_the_transaction(tmp_path, candidate):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)

    assert buffer.add(candidate) is False
    assert buffer.pending_count == 0


@pytest.mark.parametrize("missing_field", ["event_id", "event_type", "created_at"])
def test_events_missing_identity_are_rejected(tmp_path, missing_field):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)
    event = _event(0)
    object.__setattr__(event, missing_field, "")

    assert buffer.add(event) is False
    assert buffer.pending_count == 0


def test_one_malformed_event_does_not_block_a_good_batch(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)

    buffer.add(_event(0))
    buffer.add("garbage")
    buffer.add(_event(1))

    assert buffer.flush() == 2
    assert store.count() == 2


class _FailingStore:
    """Store double whose batch write always fails after writing nothing."""

    def __init__(self):
        self.calls = 0

    def append_many(self, events):
        self.calls += 1
        raise sqlite3.OperationalError("database is locked")


def test_a_failed_flush_writes_nothing_and_keeps_the_batch(tmp_path):
    store = _FailingStore()
    buffer = LearningEventBuffer(store)
    for index in range(3):
        buffer.add(_event(index))

    assert buffer.flush() == 0
    assert buffer.pending_count == 3
    assert store.calls == 1


def test_a_requeued_batch_is_written_on_the_next_successful_flush(tmp_path):
    real_store = _store(tmp_path)
    buffer = LearningEventBuffer(real_store)
    buffer.store = _FailingStore()
    for index in range(3):
        buffer.add(_event(index))
    buffer.flush()

    buffer.store = real_store

    assert buffer.flush() == 3
    assert _stored_ids(real_store) == ["event-0000", "event-0001", "event-0002"]


def test_a_requeued_batch_keeps_its_place_ahead_of_newer_events(tmp_path):
    real_store = _store(tmp_path)
    buffer = LearningEventBuffer(real_store, flush_threshold=100)
    buffer.store = _FailingStore()
    buffer.add(_event(0))
    buffer.add(_event(1))
    buffer.flush()

    buffer.store = real_store
    buffer.add(_event(2))
    buffer.flush()

    with sqlite3.connect(real_store.db_path) as connection:
        rows = connection.execute("SELECT event_id FROM learning_events ORDER BY rowid").fetchall()
    assert [row[0] for row in rows] == ["event-0000", "event-0001", "event-0002"]


def test_a_new_buffer_has_dropped_nothing(tmp_path):
    buffer = LearningEventBuffer(_store(tmp_path))

    assert buffer.dropped_events == 0
    assert buffer.pending_count == 0


def test_the_queue_is_bounded_and_drops_the_oldest(tmp_path):
    store = _FailingStore()
    buffer = LearningEventBuffer(store, flush_threshold=2, max_pending=4)

    for index in range(10):
        buffer.add(_event(index))

    assert buffer.pending_count == 4
    assert buffer.dropped_events == 6
    assert [event.event_id for event in buffer._pending] == [
        "event-0006",
        "event-0007",
        "event-0008",
        "event-0009",
    ]


def test_dropped_events_accumulate_across_overflows(tmp_path):
    buffer = LearningEventBuffer(_FailingStore(), flush_threshold=2, max_pending=4)

    for index in range(6):
        buffer.add(_event(index))
    first_total = buffer.dropped_events
    for index in range(6, 10):
        buffer.add(_event(index))

    assert first_total == 2
    assert buffer.dropped_events == 6


def test_max_pending_is_never_below_the_flush_threshold(tmp_path):
    buffer = LearningEventBuffer(_store(tmp_path), flush_threshold=10, max_pending=2)

    assert buffer.max_pending == 10


def test_thresholds_reject_non_positive_values(tmp_path):
    buffer = LearningEventBuffer(_store(tmp_path), flush_threshold=0)

    assert buffer.flush_threshold == 1


def test_clear_discards_without_writing(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store)
    buffer.add(_event(0))
    buffer.add(_event(1))

    assert buffer.clear() == 2
    assert buffer.pending_count == 0
    assert store.count() == 0


def test_concurrent_writers_lose_no_events(tmp_path):
    store = _store(tmp_path)
    buffer = LearningEventBuffer(store, flush_threshold=7)

    def add_range(start):
        for index in range(start, start + 20):
            buffer.add(_event(index))

    threads = [threading.Thread(target=add_range, args=(base * 20,)) for base in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    buffer.flush()

    assert store.count() == 80


def _flush_and_read_telemetry(buffer, path):
    """Flush under telemetry and return the record plus real elapsed milliseconds."""
    telemetry = PerformanceTelemetry(path, enabled=True)
    token = bind_performance_context(telemetry, "turn-1")
    started_at = time.perf_counter()
    try:
        buffer.flush()
    finally:
        reset_performance_context(token)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0]), elapsed_ms


def test_flush_emits_telemetry(tmp_path):
    buffer = LearningEventBuffer(_store(tmp_path))
    for index in range(3):
        buffer.add(_event(index))

    record, _ = _flush_and_read_telemetry(buffer, tmp_path / "telemetry.jsonl")

    assert record["event"] == "learning_flush"
    assert record["batch_size"] == 3
    assert record["inserted_events"] == 3
    assert record["queue_depth"] == 0
    assert record["dropped_events"] == 0
    assert record["error_type"] == ""
    assert record["success"] is True


def test_flush_telemetry_reports_a_realistic_duration(tmp_path):
    buffer = LearningEventBuffer(_store(tmp_path), flush_threshold=1_000)
    for index in range(200):
        buffer.add(_event(index))

    record, elapsed_ms = _flush_and_read_telemetry(buffer, tmp_path / "duration.jsonl")

    assert record["duration_ms"] <= elapsed_ms
    assert record["duration_ms"] >= elapsed_ms / 100


def test_failed_flush_telemetry_reports_the_error(tmp_path):
    buffer = LearningEventBuffer(_FailingStore())
    buffer.add(_event(0))

    record, _ = _flush_and_read_telemetry(buffer, tmp_path / "failure.jsonl")

    assert record["success"] is False
    assert record["error_type"] == "OperationalError"
    assert record["batch_size"] == 1
    assert record["inserted_events"] == 0
    assert record["queue_depth"] == 1
    assert record["dropped_events"] == 0


def test_default_threshold_matches_the_measured_batch_size():
    assert DEFAULT_FLUSH_THRESHOLD == 20


def test_optimizer_flushes_before_reading_tool_rankings(tmp_path):
    optimizer = ToolOptimizer(storage_dir=tmp_path)
    for index in range(4):
        optimizer.track_tool_execution(
            tool_name="run_tests",
            success=True,
            duration_ms=index + 1,
            task_context="verify the change",
        )

    assert optimizer.pending_event_count == 4

    rankings = optimizer.get_tool_rankings()

    assert optimizer.pending_event_count == 0
    assert any(ranking["tool_name"] == "run_tests" for ranking in rankings)


def test_optimizer_flushes_before_suggesting_a_tool_chain(tmp_path):
    optimizer = ToolOptimizer(storage_dir=tmp_path)
    optimizer.track_tool_execution("read_file", True, 1.0, task_context="read config")

    assert optimizer.pending_event_count == 1

    optimizer.suggest_tool_chain("read config")

    assert optimizer.pending_event_count == 0


def test_optimizer_clear_data_drops_buffered_events(tmp_path):
    optimizer = ToolOptimizer(storage_dir=tmp_path)
    optimizer.track_tool_execution("read_file", True, 1.0)

    optimizer.clear_data()

    assert optimizer.pending_event_count == 0
    assert optimizer.store.count(event_types={"tool_execution"}) == 0


def test_optimizer_flush_reports_whether_it_wrote(tmp_path):
    optimizer = ToolOptimizer(storage_dir=tmp_path)

    assert optimizer.flush() is False

    optimizer.track_tool_execution("read_file", True, 1.0)

    assert optimizer.flush() is True
    assert optimizer.flush() is False


def test_append_many_matches_append_row_for_row(tmp_path):
    individual = _store(tmp_path, "individual")
    batched = _store(tmp_path, "batched")
    events = [_event(index) for index in range(6)]

    for event in events:
        individual.append(event)
    batched.append_many(events)

    columns = "event_id, task_id, event_type, outcome, summary, metadata, schema_version"
    with sqlite3.connect(individual.db_path) as first:
        individual_rows = first.execute(
            f"SELECT {columns} FROM learning_events ORDER BY event_id"
        ).fetchall()
    with sqlite3.connect(batched.db_path) as second:
        batched_rows = second.execute(
            f"SELECT {columns} FROM learning_events ORDER BY event_id"
        ).fetchall()

    assert individual_rows == batched_rows
