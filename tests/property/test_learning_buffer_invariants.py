"""Property tests for batched learning-write invariants."""

from __future__ import annotations

import sqlite3

from hypothesis import given, settings
from hypothesis import strategies as st

from radsim.learning.buffer import LearningEventBuffer
from radsim.learning.events import LearningEvent, TaskOutcome
from radsim.learning.store import LearningStore

PROPERTY_TEST_SETTINGS = settings(max_examples=50, deadline=None)


def _store(tmp_path_factory, name):
    directory = tmp_path_factory.mktemp(name)
    return LearningStore(storage_dir=directory, max_events=10_000, migrate_legacy=False)


def _event(index):
    return LearningEvent.create(
        event_id=f"event-{index:05d}",
        task_id=f"task-{index}",
        event_type="tool_execution",
        task_category="test",
        tool_name="read_file",
        outcome=TaskOutcome.SUCCESSFUL,
        summary=f"event {index}",
    )


def _rowid_order(store):
    with sqlite3.connect(store.db_path) as connection:
        return [
            row[0]
            for row in connection.execute(
                "SELECT event_id FROM learning_events ORDER BY rowid"
            ).fetchall()
        ]


class _FailingStore:
    def append_many(self, events):
        raise sqlite3.OperationalError("database is locked")


@PROPERTY_TEST_SETTINGS
@given(
    event_count=st.integers(min_value=0, max_value=60),
    threshold=st.integers(min_value=1, max_value=15),
)
def test_every_added_event_is_written_exactly_once(tmp_path_factory, event_count, threshold):
    store = _store(tmp_path_factory, "written_once")
    buffer = LearningEventBuffer(store, flush_threshold=threshold)

    for index in range(event_count):
        buffer.add(_event(index))
    buffer.flush()

    assert store.count() == event_count
    assert buffer.pending_count == 0


@PROPERTY_TEST_SETTINGS
@given(
    event_count=st.integers(min_value=1, max_value=60),
    threshold=st.integers(min_value=1, max_value=15),
)
def test_write_order_always_matches_add_order(tmp_path_factory, event_count, threshold):
    store = _store(tmp_path_factory, "order")
    buffer = LearningEventBuffer(store, flush_threshold=threshold)

    for index in range(event_count):
        buffer.add(_event(index))
    buffer.flush()

    assert _rowid_order(store) == [f"event-{index:05d}" for index in range(event_count)]


@PROPERTY_TEST_SETTINGS
@given(
    event_count=st.integers(min_value=0, max_value=40),
    threshold=st.integers(min_value=1, max_value=10),
    max_pending=st.integers(min_value=1, max_value=40),
)
def test_the_queue_never_exceeds_its_bound(event_count, threshold, max_pending):
    buffer = LearningEventBuffer(
        _FailingStore(), flush_threshold=threshold, max_pending=max_pending
    )

    for index in range(event_count):
        buffer.add(_event(index))

    assert buffer.pending_count <= buffer.max_pending
    assert buffer.max_pending >= buffer.flush_threshold


@PROPERTY_TEST_SETTINGS
@given(event_count=st.integers(min_value=1, max_value=30))
def test_a_failed_flush_never_writes_and_never_loses_events(event_count):
    buffer = LearningEventBuffer(_FailingStore(), flush_threshold=1_000, max_pending=1_000)

    for index in range(event_count):
        buffer.add(_event(index))
    written = buffer.flush()

    assert written == 0
    assert buffer.pending_count == event_count


@PROPERTY_TEST_SETTINGS
@given(
    event_count=st.integers(min_value=1, max_value=30),
    repeats=st.integers(min_value=1, max_value=4),
)
def test_replaying_a_batch_is_idempotent(tmp_path_factory, event_count, repeats):
    store = _store(tmp_path_factory, "idempotent")
    events = [_event(index) for index in range(event_count)]

    for _ in range(repeats):
        store.append_many(events)

    assert store.count() == event_count


@PROPERTY_TEST_SETTINGS
@given(event_count=st.integers(min_value=1, max_value=25))
def test_batched_and_individual_writes_agree(tmp_path_factory, event_count):
    individual = _store(tmp_path_factory, "individual")
    batched = _store(tmp_path_factory, "batched")
    events = [_event(index) for index in range(event_count)]

    for event in events:
        individual.append(event)
    batched.append_many(events)

    assert _rowid_order(individual) == _rowid_order(batched)
    assert individual.count() == batched.count()
