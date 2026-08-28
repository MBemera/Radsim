"""Canonical learning events and evidence-based task outcomes."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_SUMMARY_CHARS = 500
MAX_ERROR_CHARS = 500
MAX_TRACKED_TOOL_RESULTS = 200
VERIFICATION_TOOLS = {"run_tests", "lint_code", "type_check"}
_SECRET_TEXT_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret)"
        r"\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


class TaskOutcome(str, Enum):
    """Shared outcome vocabulary for every learned task."""

    UNKNOWN = "unknown"
    SUCCESSFUL = "successful"
    PARTIALLY_SUCCESSFUL = "partially_successful"
    FAILED = "failed"
    CANCELLED = "cancelled"
    USER_REJECTED = "user_rejected"
    REVERTED = "reverted"


VERIFIED_SUCCESS_OUTCOMES = {
    TaskOutcome.SUCCESSFUL.value,
    TaskOutcome.PARTIALLY_SUCCESSFUL.value,
}


def normalize_outcome(value: TaskOutcome | str | bool | None) -> TaskOutcome:
    """Convert legacy booleans and strings into the shared outcome type."""
    if isinstance(value, TaskOutcome):
        return value
    if value is True:
        return TaskOutcome.SUCCESSFUL
    if value is False:
        return TaskOutcome.FAILED
    try:
        return TaskOutcome(str(value))
    except ValueError:
        return TaskOutcome.UNKNOWN


def classify_task(task_description: str) -> str:
    """Classify a task using one deterministic, shared keyword map."""
    text = (task_description or "").lower()
    categories = {
        "bug_fix": ("fix", "bug", "error", "issue", "broken"),
        "feature": ("add", "create", "implement", "build", "new"),
        "refactor": ("refactor", "improve", "clean", "optimise", "optimize"),
        "test": ("test", "testing", "coverage", "spec"),
        "docs": ("document", "readme", "comment", "doc"),
        "config": ("config", "setting", "setup", "install"),
    }
    for category, keywords in categories.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "general"


def stable_identifier(*parts: Any) -> str:
    """Return a stable, non-secret identifier for persisted learning data."""
    encoded = json.dumps(parts, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def bounded_text(value: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Store printable, bounded text without terminal-control characters."""
    text = str(value or "")
    printable = "".join(character for character in text if character.isprintable() or character in "\n\t")
    for pattern in _SECRET_TEXT_PATTERNS:
        printable = pattern.sub("[redacted]", printable)
    return printable[:limit]


@dataclass
class LearningEvent:
    """Versioned canonical record for tool, task, feedback, and error learning."""

    event_id: str
    task_id: str
    event_type: str
    task_category: str
    tool_name: str | None
    action_signature: str | None
    outcome: str
    duration_ms: float
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    error_type: str | None
    error_message: str | None
    user_decision: str | None
    created_at: str
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        task_id: str = "",
        task_category: str = "general",
        tool_name: str | None = None,
        action_signature: str | None = None,
        outcome: TaskOutcome | str | bool | None = TaskOutcome.UNKNOWN,
        duration_ms: float = 0,
        model: str = "",
        provider: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
        user_decision: str | None = None,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
        event_id: str | None = None,
        created_at: str | None = None,
        schema_version: int = SCHEMA_VERSION,
    ) -> LearningEvent:
        normalized_outcome = normalize_outcome(outcome)
        return cls(
            event_id=event_id or uuid.uuid4().hex,
            task_id=task_id or uuid.uuid4().hex,
            event_type=bounded_text(event_type, 64),
            task_category=bounded_text(task_category or "general", 64),
            tool_name=bounded_text(tool_name, 100) or None,
            action_signature=bounded_text(action_signature, 200) or None,
            outcome=normalized_outcome.value,
            duration_ms=max(0.0, float(duration_ms or 0)),
            model=bounded_text(model, 160),
            provider=bounded_text(provider, 80),
            input_tokens=max(0, int(input_tokens or 0)),
            output_tokens=max(0, int(output_tokens or 0)),
            error_type=bounded_text(error_type, 120) or None,
            error_message=bounded_text(error_message, MAX_ERROR_CHARS) or None,
            user_decision=bounded_text(user_decision, 80) or None,
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
            summary=bounded_text(summary),
            metadata=dict(metadata or {}),
            schema_version=max(1, int(schema_version or SCHEMA_VERSION)),
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> LearningEvent:
        """Build an event from a SQLite row or dictionary."""
        metadata = record.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        return cls.create(
            event_id=str(record.get("event_id") or uuid.uuid4().hex),
            task_id=str(record.get("task_id") or ""),
            event_type=str(record.get("event_type") or "unknown"),
            task_category=str(record.get("task_category") or "general"),
            tool_name=record.get("tool_name"),
            action_signature=record.get("action_signature"),
            outcome=record.get("outcome"),
            duration_ms=record.get("duration_ms", 0),
            model=str(record.get("model") or ""),
            provider=str(record.get("provider") or ""),
            input_tokens=record.get("input_tokens", 0),
            output_tokens=record.get("output_tokens", 0),
            error_type=record.get("error_type"),
            error_message=record.get("error_message"),
            user_decision=record.get("user_decision"),
            created_at=str(record.get("created_at") or ""),
            summary=str(record.get("summary") or ""),
            metadata=metadata if isinstance(metadata, dict) else {},
            schema_version=record.get("schema_version", SCHEMA_VERSION),
        )


@dataclass
class TaskReflection:
    """Compatibility view over a canonical task-completion event."""

    task_description: str
    approach_taken: str
    result: str
    success: bool
    insights: list[str]
    improvement_suggestions: list[str]
    outcome: str = TaskOutcome.UNKNOWN.value
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskOutcomeTracker:
    """Collect execution evidence and resolve one outcome at the turn boundary."""

    def __init__(self, task_description: str, provider: str = "", model: str = ""):
        self.task_id = uuid.uuid4().hex
        self.task_description = bounded_text(task_description)
        self.provider = bounded_text(provider, 80)
        self.model = bounded_text(model, 160)
        self.tool_results: list[dict[str, Any]] = []
        self.dropped_tool_results = 0
        self._had_success = False
        self._had_failure = False
        self._had_failed_verification = False
        self.cancelled = False
        self.user_rejected = False
        self.reverted = False

    def record_tool(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float = 0,
        error: str = "",
    ) -> None:
        """Record only bounded outcome evidence, never raw tool inputs."""
        stopped = "STOPPED" in str(error)
        record = {
            "tool_name": bounded_text(tool_name, 100),
            "success": bool(success),
            "duration_ms": max(0.0, float(duration_ms or 0)),
            "error": bounded_text(error, MAX_ERROR_CHARS),
            "verification": tool_name in VERIFICATION_TOOLS,
        }
        self._had_success = self._had_success or record["success"]
        self._had_failure = self._had_failure or not record["success"]
        self._had_failed_verification = self._had_failed_verification or (
            record["verification"] and not record["success"]
        )
        if len(self.tool_results) >= MAX_TRACKED_TOOL_RESULTS:
            self.tool_results.pop(0)
            self.dropped_tool_results += 1
        self.tool_results.append(record)
        if stopped:
            self.user_rejected = True

    def mark_cancelled(self) -> None:
        self.cancelled = True

    def mark_reverted(self) -> None:
        self.reverted = True

    def resolve(self, error: BaseException | None = None) -> TaskOutcome:
        """Resolve conservatively, with unknown as the no-evidence default."""
        if self.reverted:
            return TaskOutcome.REVERTED
        if self.cancelled:
            return TaskOutcome.CANCELLED
        if self.user_rejected:
            return TaskOutcome.USER_REJECTED
        if error is not None:
            return TaskOutcome.FAILED
        if not self.tool_results:
            return TaskOutcome.UNKNOWN

        if self._had_failed_verification:
            return TaskOutcome.PARTIALLY_SUCCESSFUL if self._had_success else TaskOutcome.FAILED
        if self._had_failure:
            return TaskOutcome.PARTIALLY_SUCCESSFUL if self._had_success else TaskOutcome.FAILED
        return TaskOutcome.SUCCESSFUL

    def build_event(
        self,
        *,
        result: Any = "",
        error: BaseException | None = None,
        duration_ms: float = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> LearningEvent:
        """Build the one task-completion event for this tracker."""
        outcome = self.resolve(error)
        successful_tools = [item["tool_name"] for item in self.tool_results if item["success"]]
        failed_tools = [item["tool_name"] for item in self.tool_results if not item["success"]]
        user_decision = "rejected" if self.user_rejected else None
        error_message = str(error) if error else next(
            (item["error"] for item in reversed(self.tool_results) if item["error"]),
            None,
        )
        return LearningEvent.create(
            task_id=self.task_id,
            event_type="task_completion",
            task_category=classify_task(self.task_description),
            action_signature=stable_identifier(self.task_description),
            outcome=outcome,
            duration_ms=duration_ms,
            model=self.model,
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_type=type(error).__name__ if error else None,
            error_message=error_message,
            user_decision=user_decision,
            summary=self.task_description,
            metadata={
                "tools_used": [item["tool_name"] for item in self.tool_results],
                "successful_tools": successful_tools,
                "failed_tools": failed_tools,
                "verification_tools": [
                    item["tool_name"] for item in self.tool_results if item["verification"]
                ],
                "tool_results_dropped": self.dropped_tool_results,
            },
        )


class ReflectionEngine:
    """Read and write reflection-compatible views through the canonical store."""

    def __init__(self, storage_dir: Path | None = None):
        from .store import LearningStore

        self.storage_dir = storage_dir or Path.home() / ".radsim" / "learning"
        self.store = LearningStore(storage_dir=self.storage_dir)

    def reflect_on_completion(
        self,
        task_description: str,
        approach_taken: str,
        result: str,
        success: TaskOutcome | str | bool,
        tools_used: list[str] | None = None,
        duration_seconds: float = 0,
    ) -> TaskReflection:
        """Persist a compatibility reflection as one task event."""
        outcome = normalize_outcome(success)
        event = LearningEvent.create(
            event_type="task_completion",
            task_category=classify_task(task_description),
            action_signature=stable_identifier(task_description),
            outcome=outcome,
            duration_ms=duration_seconds * 1000,
            summary=task_description,
            metadata={
                "approach": bounded_text(approach_taken, 1000),
                "result": bounded_text(result),
                "tools_used": list(tools_used or []),
            },
        )
        self.store.append(event)
        insights, suggestions = _reflection_notes(event)
        return TaskReflection(
            task_description=task_description,
            approach_taken=approach_taken,
            result=result,
            success=outcome == TaskOutcome.SUCCESSFUL,
            outcome=outcome.value,
            insights=insights,
            improvement_suggestions=suggestions,
            timestamp=event.created_at,
        )

    @property
    def _reflections(self) -> list[dict[str, Any]]:
        return [self._event_to_reflection(event) for event in self.store.query(
            event_types={"task_completion"}, limit=500
        )]

    def get_recent_reflections(self, count: int = 10) -> list[dict[str, Any]]:
        events = self.store.query(event_types={"task_completion"}, limit=count, newest_first=True)
        return [self._event_to_reflection(event) for event in reversed(events)]

    def get_success_rate_by_category(self) -> dict[str, dict[str, Any]]:
        categories: dict[str, dict[str, Any]] = {}
        reverted_task_ids = {
            event.task_id
            for event in self.store.query(event_types={"task_revert"}, limit=2000)
        }
        for event in self.store.query(event_types={"task_completion"}, limit=2000):
            stats = categories.setdefault(
                event.task_category,
                {"successful": 0.0, "total_tasks": 0, "effective_approaches": []},
            )
            stats["total_tasks"] += 1
            if event.task_id in reverted_task_ids:
                effective_outcome = TaskOutcome.REVERTED.value
            else:
                effective_outcome = event.outcome
            if effective_outcome == TaskOutcome.SUCCESSFUL.value:
                stats["successful"] += 1
            elif effective_outcome == TaskOutcome.PARTIALLY_SUCCESSFUL.value:
                stats["successful"] += 0.5
            approach = bounded_text(event.metadata.get("approach", ""), 200)
            if effective_outcome == TaskOutcome.SUCCESSFUL.value and approach:
                if approach not in stats["effective_approaches"]:
                    stats["effective_approaches"].append(approach)

        return {
            category: {
                "success_rate": values["successful"] / values["total_tasks"],
                "total_tasks": values["total_tasks"],
                "effective_approaches": values["effective_approaches"][-3:],
            }
            for category, values in categories.items()
        }

    def get_improvement_opportunities(self) -> list[dict[str, Any]]:
        failures: dict[str, list[LearningEvent]] = {}
        failure_outcomes = {
            TaskOutcome.FAILED.value,
            TaskOutcome.PARTIALLY_SUCCESSFUL.value,
            TaskOutcome.REVERTED.value,
        }
        failed_task_ids = set()
        for event in self.store.query(
            event_types={"task_completion"}, outcomes=failure_outcomes, limit=500
        ):
            failures.setdefault(event.task_category, []).append(event)
            failed_task_ids.add(event.task_id)
        completions = {
            event.task_id: event
            for event in self.store.query(event_types={"task_completion"}, limit=2000)
        }
        for revert in self.store.query(event_types={"task_revert"}, limit=500):
            completion = completions.get(revert.task_id)
            if completion is not None and completion.task_id not in failed_task_ids:
                failures.setdefault(completion.task_category, []).append(completion)
        suggestions = {
            "bug_fix": "Read and reproduce the failure before changing code.",
            "feature": "Break the feature into testable increments.",
            "refactor": "Make one structural change at a time and verify behaviour.",
            "test": "Verify the test environment before changing implementation.",
            "docs": "Keep documentation aligned with executable behaviour.",
            "config": "Validate environment values and paths before applying changes.",
            "general": "Collect stronger execution evidence before repeating the approach.",
        }
        ranked = sorted(failures.items(), key=lambda item: len(item[1]), reverse=True)
        return [
            {
                "category": category,
                "failure_count": len(events),
                "common_issues": [
                    bounded_text(event.error_message or event.metadata.get("result", ""), 100)
                    for event in events[-5:]
                ],
                "suggestion": suggestions.get(category, suggestions["general"]),
            }
            for category, events in ranked[:3]
        ]

    def clear_data(self) -> None:
        self.store.delete(event_types={"task_completion"})

    @staticmethod
    def _event_to_reflection(event: LearningEvent) -> dict[str, Any]:
        insights, suggestions = _reflection_notes(event)
        return {
            "task_description": event.summary,
            "approach_taken": event.metadata.get("approach", ""),
            "result": event.metadata.get("result", ""),
            "success": event.outcome == TaskOutcome.SUCCESSFUL.value,
            "outcome": event.outcome,
            "insights": insights,
            "suggestions": suggestions,
            "tools_used": event.metadata.get("tools_used", []),
            "duration_seconds": event.duration_ms / 1000,
            "timestamp": event.created_at,
        }


def _reflection_notes(event: LearningEvent) -> tuple[list[str], list[str]]:
    tools = list(event.metadata.get("tools_used", []))
    insights: list[str] = []
    suggestions: list[str] = []
    if event.outcome == TaskOutcome.SUCCESSFUL.value:
        insights.append("SUCCESS: Execution evidence verified the completed task.")
    elif event.outcome == TaskOutcome.UNKNOWN.value:
        insights.append("UNKNOWN: No execution evidence verified the result.")
    else:
        insights.append(f"{event.outcome.upper()}: Review the failed execution evidence.")
    if "write_file" in tools and "run_tests" not in tools:
        suggestions.append("Run tests after changing code.")
    if len(tools) > 10:
        suggestions.append("Reduce avoidable tool calls.")
    return insights, suggestions


_reflection_engine: ReflectionEngine | None = None


def get_reflection_engine() -> ReflectionEngine:
    global _reflection_engine
    if _reflection_engine is None:
        _reflection_engine = ReflectionEngine()
    return _reflection_engine


def reflect_on_completion(
    task_description: str,
    approach_taken: str,
    result: str,
    success: TaskOutcome | str | bool,
    tools_used: list[str] | None = None,
    duration_seconds: float = 0,
) -> TaskReflection:
    return get_reflection_engine().reflect_on_completion(
        task_description,
        approach_taken,
        result,
        success,
        tools_used,
        duration_seconds,
    )


def get_improvement_opportunities() -> list[dict[str, Any]]:
    return get_reflection_engine().get_improvement_opportunities()


def record_revert(task_id: str = "", summary: str = "User reverted the last change") -> LearningEvent:
    """Record an explicit rollback without rewriting the original event."""
    from .store import get_learning_store

    store = get_learning_store()
    if not task_id:
        latest = store.latest_task()
        task_id = latest.task_id if latest is not None else ""
    event = LearningEvent.create(
        task_id=task_id,
        event_type="task_revert",
        outcome=TaskOutcome.REVERTED,
        summary=summary,
        user_decision="reverted",
    )
    store.append(event)
    return event
