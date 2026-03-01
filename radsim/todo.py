# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Structured task tracking for the RadSim agent.

Maintains a session-scoped todo list. The LLM uses this to
track progress on multi-step tasks and avoid drift.

Design: Exactly one task can be 'in_progress' at a time.
"""

import logging
from dataclasses import asdict, dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class TodoItem:
    id: int
    description: str
    status: TaskStatus = TaskStatus.PENDING


class TodoTracker:
    """Session-scoped todo list for the agent."""

    def __init__(self):
        self._items: list[TodoItem] = []
        self._next_id: int = 1

    def read(self) -> dict:
        """Read the current todo list."""
        if not self._items:
            return {
                "success": True,
                "todos": [],
                "summary": "No tasks tracked. Use todo_write to create tasks.",
            }

        pending = [i for i in self._items if i.status == TaskStatus.PENDING]
        in_progress = [i for i in self._items if i.status == TaskStatus.IN_PROGRESS]
        completed = [i for i in self._items if i.status == TaskStatus.COMPLETED]

        lines = []
        if in_progress:
            lines.append(f"▶ IN PROGRESS: {in_progress[0].description} (#{in_progress[0].id})")
        for item in pending:
            lines.append(f"⬚ PENDING: {item.description} (#{item.id})")
        for item in completed:
            lines.append(f"✓ DONE: {item.description} (#{item.id})")

        return {
            "success": True,
            "todos": [asdict(i) for i in self._items],
            "summary": "\n".join(lines),
            "counts": {
                "pending": len(pending),
                "in_progress": len(in_progress),
                "completed": len(completed),
            },
        }

    def write(self, todos: list[dict]) -> dict:
        """Write/update the todo list.

        Accepts a full list of todo items. Each item has:
        - id (optional, for updates; omit for new items)
        - description (required)
        - status: "pending", "in_progress", or "completed"

        Enforces: exactly one in_progress item.
        """
        new_items = []
        in_progress_count = 0

        for item_data in todos:
            status = TaskStatus(item_data.get("status", "pending"))

            if status == TaskStatus.IN_PROGRESS:
                in_progress_count += 1

            item_id = item_data.get("id", self._next_id)
            if item_id >= self._next_id:
                self._next_id = item_id + 1

            new_items.append(
                TodoItem(
                    id=item_id,
                    description=item_data["description"],
                    status=status,
                )
            )

        if in_progress_count > 1:
            return {
                "success": False,
                "error": f"Only one task can be in_progress at a time. Got {in_progress_count}.",
            }

        self._items = new_items
        return self.read()


# Module-level singleton (session-scoped)
_tracker = None


def get_tracker() -> TodoTracker:
    global _tracker
    if _tracker is None:
        _tracker = TodoTracker()
    return _tracker


def reset_tracker():
    global _tracker
    _tracker = TodoTracker()
