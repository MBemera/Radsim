# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Tests for todo_read / todo_write task tracking."""

from radsim.todo import TaskStatus, TodoTracker, get_tracker, reset_tracker


class TestTodoTracker:
    def setup_method(self):
        self.tracker = TodoTracker()

    def test_read_empty(self):
        result = self.tracker.read()
        assert result["success"] is True
        assert result["todos"] == []
        assert "No tasks" in result["summary"]

    def test_write_single_task(self):
        result = self.tracker.write([{"description": "Fix the bug"}])
        assert result["success"] is True
        assert len(result["todos"]) == 1
        assert result["todos"][0]["description"] == "Fix the bug"
        assert result["todos"][0]["status"] == "pending"

    def test_write_multiple_tasks(self):
        result = self.tracker.write([
            {"description": "Step 1", "status": "completed"},
            {"description": "Step 2", "status": "in_progress"},
            {"description": "Step 3", "status": "pending"},
        ])
        assert result["success"] is True
        assert result["counts"]["completed"] == 1
        assert result["counts"]["in_progress"] == 1
        assert result["counts"]["pending"] == 1

    def test_enforce_single_in_progress(self):
        result = self.tracker.write([
            {"description": "Task A", "status": "in_progress"},
            {"description": "Task B", "status": "in_progress"},
        ])
        assert result["success"] is False
        assert "Only one task" in result["error"]

    def test_auto_assigns_ids(self):
        result = self.tracker.write([
            {"description": "First"},
            {"description": "Second"},
        ])
        assert result["success"] is True
        ids = [t["id"] for t in result["todos"]]
        assert ids[0] != ids[1]

    def test_preserves_explicit_ids(self):
        result = self.tracker.write([
            {"id": 10, "description": "Task ten"},
            {"description": "Next task"},
        ])
        assert result["success"] is True
        assert result["todos"][0]["id"] == 10
        assert result["todos"][1]["id"] == 11

    def test_summary_format(self):
        self.tracker.write([
            {"description": "Done thing", "status": "completed"},
            {"description": "Doing thing", "status": "in_progress"},
            {"description": "Todo thing", "status": "pending"},
        ])
        result = self.tracker.read()
        assert "IN PROGRESS" in result["summary"]
        assert "PENDING" in result["summary"]
        assert "DONE" in result["summary"]

    def test_write_replaces_full_list(self):
        self.tracker.write([{"description": "Old task"}])
        self.tracker.write([{"description": "New task"}])
        result = self.tracker.read()
        assert len(result["todos"]) == 1
        assert result["todos"][0]["description"] == "New task"

    def test_zero_in_progress_allowed(self):
        result = self.tracker.write([
            {"description": "A", "status": "pending"},
            {"description": "B", "status": "completed"},
        ])
        assert result["success"] is True
        assert result["counts"]["in_progress"] == 0


class TestSingleton:
    def setup_method(self):
        reset_tracker()

    def test_get_tracker_returns_same_instance(self):
        t1 = get_tracker()
        t2 = get_tracker()
        assert t1 is t2

    def test_reset_creates_new_instance(self):
        t1 = get_tracker()
        t1.write([{"description": "Something"}])
        reset_tracker()
        t2 = get_tracker()
        assert t2.read()["todos"] == []


class TestTaskStatus:
    def test_enum_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.IN_PROGRESS == "in_progress"
        assert TaskStatus.COMPLETED == "completed"

    def test_from_string(self):
        assert TaskStatus("pending") == TaskStatus.PENDING
        assert TaskStatus("in_progress") == TaskStatus.IN_PROGRESS
        assert TaskStatus("completed") == TaskStatus.COMPLETED
