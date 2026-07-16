"""Batching and crash-safety tests for learning and vector-memory writes."""

import json
from collections import Counter
from unittest.mock import MagicMock

import pytest

import radsim.learning.tool_optimizer as tool_optimizer_module
import radsim.persistence as persistence
from radsim.agent import RadSimAgent
from radsim.learning.tool_optimizer import ToolOptimizer
from radsim.vector_memory import COLLECTION_CONVERSATIONS, JsonMemoryFallback, VectorMemory


def memory_items(count):
    """Build deterministic fallback-memory inputs."""
    return [
        {
            "memory_id": f"memory_{index}",
            "content": f"Alpha topic {index} with shared keyword",
            "metadata": {"index": index},
        }
        for index in range(count)
    ]


def test_individual_and_batch_add_produce_identical_json(tmp_path):
    individual = JsonMemoryFallback(tmp_path / "individual")
    batched = JsonMemoryFallback(tmp_path / "batched")
    items = memory_items(20)

    for item in items:
        individual.add(
            COLLECTION_CONVERSATIONS,
            item["memory_id"],
            item["content"],
            item["metadata"],
        )
    batched.add_many(COLLECTION_CONVERSATIONS, items)

    individual_json = individual._get_collection_path(COLLECTION_CONVERSATIONS).read_text()
    batched_json = batched._get_collection_path(COLLECTION_CONVERSATIONS).read_text()
    assert json.loads(individual_json) == json.loads(batched_json)
    assert individual_json == batched_json


def test_fallback_add_many_saves_once_and_updates_keyword_counts(
    tmp_path, monkeypatch
):
    fallback = JsonMemoryFallback(tmp_path / "batched")
    save_calls = []
    original_save = fallback._save_collection

    def counting_save(collection):
        save_calls.append(collection)
        original_save(collection)

    monkeypatch.setattr(fallback, "_save_collection", counting_save)
    fallback.add_many(COLLECTION_CONVERSATIONS, memory_items(10))

    frequencies = fallback.document_frequencies[COLLECTION_CONVERSATIONS]
    assert save_calls == [COLLECTION_CONVERSATIONS]
    assert frequencies["alpha"] == 10
    assert frequencies["shared"] == 10


def test_high_level_memory_batch_rejects_empty_content_without_writing(tmp_path):
    memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))

    memory_ids = memory.add_memories(
        COLLECTION_CONVERSATIONS,
        [{"content": "valid"}, {"content": "   "}],
    )

    collection_path = memory.fallback._get_collection_path(COLLECTION_CONVERSATIONS)
    assert memory_ids == []
    assert not collection_path.exists()


def test_tool_optimizer_flush_writes_each_file_once(tmp_path, monkeypatch):
    optimizer = ToolOptimizer(storage_dir=tmp_path)
    write_paths = []
    original_write = tool_optimizer_module.atomic_write_json

    def counting_write(path, data, secure=False):
        write_paths.append(path)
        original_write(path, data, secure=secure)

    monkeypatch.setattr(tool_optimizer_module, "atomic_write_json", counting_write)

    for index in range(10):
        optimizer.track_tool_execution(
            tool_name="read_file",
            success=index != 9,
            duration_ms=index + 1,
            input_data={"index": index},
            output_data={"success": index != 9},
        )
    optimizer.complete_task_chain("batch persistence", success=True)

    assert write_paths == []
    assert optimizer.flush() is True
    assert Counter(write_paths) == {
        optimizer.executions_file: 1,
        optimizer.chains_file: 1,
        optimizer.scores_file: 1,
    }
    assert json.loads(optimizer.executions_file.read_text()) == optimizer._executions
    assert json.loads(optimizer.chains_file.read_text()) == optimizer._chains
    assert json.loads(optimizer.scores_file.read_text()) == optimizer._scores
    assert optimizer.flush() is False
    assert len(write_paths) == 3


def test_turn_cancellation_flushes_optimizer(monkeypatch):
    agent = object.__new__(RadSimAgent)
    agent._interrupted = MagicMock()
    agent._is_processing = MagicMock()
    agent._process_message_inner = MagicMock(side_effect=KeyboardInterrupt)
    flush_calls = []
    monkeypatch.setattr("radsim.escape_listener.start_escape_listener", lambda agent: None)
    monkeypatch.setattr("radsim.escape_listener.stop_escape_listener", lambda: None)
    monkeypatch.setattr(
        "radsim.agent_conversation.flush_tool_optimizer",
        lambda: flush_calls.append(True),
    )

    with pytest.raises(KeyboardInterrupt):
        agent.process_message("cancelled turn")

    assert flush_calls == [True]
    agent._is_processing.clear.assert_called_once()


def test_atomic_write_failure_preserves_old_file(tmp_path, monkeypatch):
    destination = tmp_path / "state.json"
    destination.write_text('{"version": 1}')
    monkeypatch.setattr(
        persistence.os,
        "replace",
        lambda source, target: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        persistence.atomic_write_json(destination, {"version": 2})

    assert destination.read_text() == '{"version": 1}'
    assert list(tmp_path.glob(".state.json.*.tmp")) == []
