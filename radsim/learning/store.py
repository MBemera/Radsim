"""One bounded SQLite store for RadSim learning events and analytics."""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..persistence import atomic_write_json
from .events import (
    LearningEvent,
    TaskOutcome,
    bounded_text,
    classify_task,
    stable_identifier,
)

logger = logging.getLogger(__name__)

STORE_SCHEMA_VERSION = 1
MAX_EVENTS = 2_000
MAX_METADATA_CHARS = 4_000
LEGACY_MIGRATION_ID = "legacy-json-v1"

_EVENT_COLUMNS = (
    "event_id",
    "task_id",
    "event_type",
    "task_category",
    "tool_name",
    "action_signature",
    "outcome",
    "duration_ms",
    "model",
    "provider",
    "input_tokens",
    "output_tokens",
    "error_type",
    "error_message",
    "user_decision",
    "created_at",
    "summary",
    "metadata",
    "schema_version",
)

_SECRET_KEY_PARTS = ("secret", "password", "token", "api_key", "credential")


class LearningStore:
    """Thread-safe, process-safe event persistence using the standard library."""

    def __init__(
        self,
        storage_dir: Path | None = None,
        *,
        max_events: int = MAX_EVENTS,
        migrate_legacy: bool = True,
    ):
        self.storage_dir = Path(storage_dir or Path.home() / ".radsim" / "learning")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "learning_events.sqlite3"
        self.max_events = max(1, int(max_events))
        self._initialize()
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass
        if migrate_legacy:
            self._migrate_legacy_once()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    task_category TEXT NOT NULL,
                    tool_name TEXT,
                    action_signature TEXT,
                    outcome TEXT NOT NULL,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    model TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT,
                    error_message TEXT,
                    user_decision TEXT,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    schema_version INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_learning_event_type
                    ON learning_events(event_type, created_at);
                CREATE INDEX IF NOT EXISTS idx_learning_task
                    ON learning_events(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_learning_outcome
                    ON learning_events(outcome, created_at);
                CREATE TABLE IF NOT EXISTS learning_migrations (
                    migration_id TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                PRAGMA user_version = 1;
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(learning_events)"
                ).fetchall()
            }
            if "schema_version" not in columns:
                connection.execute(
                    "ALTER TABLE learning_events "
                    "ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1"
                )

    def append(self, event: LearningEvent) -> bool:
        """Insert one event idempotently and enforce the storage bound."""
        metadata = json.dumps(_sanitize_metadata(event.metadata), sort_keys=True)
        if len(metadata) > MAX_METADATA_CHARS:
            metadata = json.dumps({"truncated": True, "preview": metadata[:MAX_METADATA_CHARS]})
        values = (
            event.event_id,
            event.task_id,
            event.event_type,
            event.task_category,
            event.tool_name,
            event.action_signature,
            event.outcome,
            event.duration_ms,
            event.model,
            event.provider,
            event.input_tokens,
            event.output_tokens,
            event.error_type,
            event.error_message,
            event.user_decision,
            event.created_at,
            event.summary,
            metadata,
            event.schema_version,
        )
        placeholders = ", ".join("?" for _ in _EVENT_COLUMNS)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                INSERT OR IGNORE INTO learning_events ({", ".join(_EVENT_COLUMNS)})
                VALUES ({placeholders})
                """,
                values,
            )
            inserted = cursor.rowcount > 0
            self._trim(connection)
        return inserted

    def append_many(self, events: list[LearningEvent]) -> int:
        """Insert a migration batch idempotently."""
        inserted = 0
        with self._connect() as connection:
            placeholders = ", ".join("?" for _ in _EVENT_COLUMNS)
            statement = (
                f"INSERT OR IGNORE INTO learning_events ({', '.join(_EVENT_COLUMNS)}) "
                f"VALUES ({placeholders})"
            )
            for event in events:
                metadata = json.dumps(_sanitize_metadata(event.metadata), sort_keys=True)
                if len(metadata) > MAX_METADATA_CHARS:
                    metadata = json.dumps(
                        {"truncated": True, "preview": metadata[:MAX_METADATA_CHARS]}
                    )
                cursor = connection.execute(
                    statement,
                    (
                        event.event_id,
                        event.task_id,
                        event.event_type,
                        event.task_category,
                        event.tool_name,
                        event.action_signature,
                        event.outcome,
                        event.duration_ms,
                        event.model,
                        event.provider,
                        event.input_tokens,
                        event.output_tokens,
                        event.error_type,
                        event.error_message,
                        event.user_decision,
                        event.created_at,
                        event.summary,
                        metadata,
                        event.schema_version,
                    ),
                )
                inserted += int(cursor.rowcount > 0)
            self._trim(connection)
        return inserted

    def query(
        self,
        *,
        event_types: set[str] | None = None,
        outcomes: set[str] | None = None,
        tool_name: str | None = None,
        task_category: str | None = None,
        task_id: str | None = None,
        since: str | None = None,
        limit: int = 500,
        newest_first: bool = False,
    ) -> list[LearningEvent]:
        """Return bounded events matching the supplied indexed filters."""
        clauses: list[str] = []
        values: list[Any] = []
        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            values.extend(sorted(event_types))
        if outcomes:
            placeholders = ", ".join("?" for _ in outcomes)
            clauses.append(f"outcome IN ({placeholders})")
            values.extend(sorted(outcomes))
        if tool_name is not None:
            clauses.append("tool_name = ?")
            values.append(tool_name)
        if task_category is not None:
            clauses.append("task_category = ?")
            values.append(task_category)
        if task_id is not None:
            clauses.append("task_id = ?")
            values.append(task_id)
        if since is not None:
            clauses.append("created_at > ?")
            values.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        direction = "DESC" if newest_first else "ASC"
        values.append(max(1, min(int(limit), self.max_events)))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {", ".join(_EVENT_COLUMNS)}
                FROM learning_events
                {where}
                ORDER BY created_at {direction}, event_id {direction}
                LIMIT ?
                """,
                values,
            ).fetchall()
        return [LearningEvent.from_record(dict(row)) for row in rows]

    def count(
        self,
        *,
        event_types: set[str] | None = None,
        outcomes: set[str] | None = None,
    ) -> int:
        clauses: list[str] = []
        values: list[Any] = []
        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            values.extend(sorted(event_types))
        if outcomes:
            placeholders = ", ".join("?" for _ in outcomes)
            clauses.append(f"outcome IN ({placeholders})")
            values.extend(sorted(outcomes))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM learning_events {where}",
                values,
            ).fetchone()
        return int(row["count"])

    def event_types(self) -> set[str]:
        """Return every event type currently stored."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT event_type FROM learning_events"
            ).fetchall()
        return {str(row["event_type"]) for row in rows}

    def delete(self, *, event_types: set[str] | None = None) -> int:
        """Delete a narrow event category. A missing filter never deletes all."""
        if not event_types:
            return 0
        placeholders = ", ".join("?" for _ in event_types)
        with self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM learning_events WHERE event_type IN ({placeholders})",
                sorted(event_types),
            )
        return cursor.rowcount

    def latest_task(self) -> LearningEvent | None:
        events = self.query(event_types={"task_completion"}, limit=1, newest_first=True)
        return events[0] if events else None

    def migration_info(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT completed_at, details FROM learning_migrations WHERE migration_id = ?",
                (LEGACY_MIGRATION_ID,),
            ).fetchone()
        if row is None:
            return {}
        try:
            details = json.loads(row["details"])
        except json.JSONDecodeError:
            details = {}
        return {"completed_at": row["completed_at"], **details}

    def _trim(self, connection: sqlite3.Connection) -> None:
        count = connection.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0]
        excess = count - self.max_events
        if excess <= 0:
            return
        connection.execute(
            """
            DELETE FROM learning_events
            WHERE event_id IN (
                SELECT event_id FROM learning_events
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
            )
            """,
            (excess,),
        )

    def _migrate_legacy_once(self) -> None:
        if self.migration_info():
            return
        legacy_names = (
            "reflections.json",
            "tool_executions.json",
            "tool_chains.json",
            "errors.json",
            "task_examples.json",
            "feedback.json",
        )
        files = [self.storage_dir / name for name in legacy_names]
        existing = [path for path in files if path.is_file() and not path.is_symlink()]
        backup_dir = self.storage_dir / "legacy_backup_v1"
        if existing:
            backup_dir.mkdir(parents=True, exist_ok=True)
            try:
                backup_dir.chmod(0o700)
            except OSError:
                pass
            for source in existing:
                target = backup_dir / source.name
                if not target.exists():
                    try:
                        shutil.copy2(source, target)
                        target.chmod(0o600)
                    except OSError as error:
                        logger.warning("Could not back up legacy learning file %s: %s", source, error)

        events, source_counts = _legacy_events(self.storage_dir)
        inserted = self.append_many(events) if events else 0
        completed_at = datetime.now(timezone.utc).isoformat()
        details = {
            "schema_version": STORE_SCHEMA_VERSION,
            "source_counts": source_counts,
            "candidate_events": len(events),
            "inserted_events": inserted,
            "backup_directory": str(backup_dir) if existing else None,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO learning_migrations
                    (migration_id, completed_at, details)
                VALUES (?, ?, ?)
                """,
                (LEGACY_MIGRATION_ID, completed_at, json.dumps(details, sort_keys=True)),
            )
        atomic_write_json(
            self.storage_dir / "migration_v1.json",
            {"migration_id": LEGACY_MIGRATION_ID, "completed_at": completed_at, **details},
            secure=True,
        )


def _sanitize_metadata(value: Any, depth: int = 0) -> Any:
    """Bound nested metadata and redact values with secret-bearing keys."""
    if depth > 4:
        return "[bounded]"
    if isinstance(value, dict):
        sanitized = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                sanitized["truncated"] = True
                break
            safe_key = bounded_text(key, 80)
            if any(part in safe_key.lower() for part in _SECRET_KEY_PARTS):
                sanitized[safe_key] = "[redacted]"
            else:
                sanitized[safe_key] = _sanitize_metadata(item, depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_metadata(item, depth + 1) for item in list(value)[:40]]
    if isinstance(value, (str, bytes, Path)):
        return bounded_text(value, 500)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return bounded_text(value, 200)


def _read_legacy_list(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        return []
    try:
        if path.stat().st_size > 5 * 1024 * 1024:
            return []
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _legacy_event_id(kind: str, item: dict[str, Any]) -> str:
    payload = json.dumps(item, sort_keys=True, default=str)
    return f"legacy_{stable_identifier(kind, payload)}"


def _legacy_events(storage_dir: Path) -> tuple[list[LearningEvent], dict[str, int]]:
    """Convert old mutable JSON records into idempotent canonical events."""
    events: list[LearningEvent] = []
    source_counts: dict[str, int] = {}
    seen_tasks: set[str] = set()

    reflections = _read_legacy_list(storage_dir / "reflections.json")
    source_counts["reflections.json"] = len(reflections)
    for item in reflections:
        task = bounded_text(item.get("task_description", ""))
        created_at = str(item.get("timestamp") or datetime.now(timezone.utc).isoformat())
        fingerprint = stable_identifier(task, created_at[:16])
        seen_tasks.add(fingerprint)
        events.append(
            LearningEvent.create(
                event_id=_legacy_event_id("reflection", item),
                task_id=f"legacy_{fingerprint}",
                event_type="task_completion",
                task_category=classify_task(task),
                action_signature=stable_identifier(task),
                outcome=TaskOutcome.SUCCESSFUL if item.get("success") else TaskOutcome.FAILED,
                duration_ms=_safe_float(item.get("duration_seconds")) * 1000,
                created_at=created_at,
                summary=task,
                error_message=None if item.get("success") else item.get("result"),
                metadata={
                    "approach": item.get("approach_taken", ""),
                    "result": item.get("result", ""),
                    "tools_used": item.get("tools_used", []),
                    "legacy_source": "reflections.json",
                },
            )
        )

    executions = _read_legacy_list(storage_dir / "tool_executions.json")
    source_counts["tool_executions.json"] = len(executions)
    for item in executions:
        tool_name = bounded_text(item.get("tool_name", ""), 100)
        success = bool(item.get("success"))
        task = bounded_text(item.get("task_context", ""))
        events.append(
            LearningEvent.create(
                event_id=_legacy_event_id("tool", item),
                task_id=f"legacy_{stable_identifier(task, item.get('timestamp', ''))}",
                event_type="tool_execution",
                task_category=classify_task(task),
                tool_name=tool_name,
                action_signature=stable_identifier(tool_name, task),
                outcome=TaskOutcome.SUCCESSFUL if success else TaskOutcome.FAILED,
                duration_ms=_safe_float(item.get("duration_ms")),
                created_at=str(item.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                summary=task or tool_name,
                error_message=item.get("error") if not success else None,
                metadata={"legacy_source": "tool_executions.json"},
            )
        )

    chains = _read_legacy_list(storage_dir / "tool_chains.json")
    source_counts["tool_chains.json"] = len(chains)
    for item in chains:
        task = bounded_text(item.get("task_description", ""))
        created_at = str(item.get("timestamp") or datetime.now(timezone.utc).isoformat())
        fingerprint = stable_identifier(task, created_at[:16])
        if fingerprint in seen_tasks:
            continue
        seen_tasks.add(fingerprint)
        events.append(
            LearningEvent.create(
                event_id=_legacy_event_id("chain", item),
                task_id=f"legacy_{fingerprint}",
                event_type="task_completion",
                task_category=classify_task(task),
                action_signature=stable_identifier(task),
                outcome=TaskOutcome.SUCCESSFUL if item.get("success") else TaskOutcome.FAILED,
                created_at=created_at,
                summary=task,
                metadata={
                    "tools_used": item.get("tools_used", []),
                    "legacy_source": "tool_chains.json",
                },
            )
        )

    errors = _read_legacy_list(storage_dir / "errors.json")
    source_counts["errors.json"] = len(errors)
    for item in errors:
        context = item.get("context", {}) if isinstance(item.get("context"), dict) else {}
        task = bounded_text(context.get("task_description", ""))
        events.append(
            LearningEvent.create(
                event_id=_legacy_event_id("error", item),
                event_type="error",
                task_category=classify_task(task),
                tool_name=context.get("tool_name"),
                action_signature=item.get("hash") or stable_identifier(item.get("error_message")),
                outcome=TaskOutcome.FAILED,
                created_at=str(item.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                summary=task or item.get("error_message", ""),
                error_type=item.get("error_type"),
                error_message=item.get("error_message"),
                metadata={
                    "correction": item.get("correction", ""),
                    "legacy_source": "errors.json",
                },
            )
        )

    examples = _read_legacy_list(storage_dir / "task_examples.json")
    source_counts["task_examples.json"] = len(examples)
    for item in examples:
        task = bounded_text(item.get("task_description", ""))
        created_at = str(item.get("timestamp") or datetime.now(timezone.utc).isoformat())
        fingerprint = stable_identifier(task, created_at[:16])
        if fingerprint in seen_tasks:
            continue
        events.append(
            LearningEvent.create(
                event_id=_legacy_event_id("example", item),
                task_id=f"legacy_{fingerprint}",
                event_type="task_example",
                task_category=classify_task(task),
                action_signature=stable_identifier(task),
                outcome=TaskOutcome.SUCCESSFUL if item.get("success") else TaskOutcome.FAILED,
                created_at=created_at,
                summary=task,
                metadata={
                    "approach": item.get("approach", ""),
                    "result": item.get("outcome", ""),
                    "tools_used": item.get("tools_used", []),
                    "legacy_source": "task_examples.json",
                },
            )
        )

    feedback = _read_legacy_list(storage_dir / "feedback.json")
    source_counts["feedback.json"] = len(feedback)
    for item in feedback:
        action = bounded_text(item.get("action", "unknown"), 40)
        outcome = {
            "accept": TaskOutcome.SUCCESSFUL,
            "good": TaskOutcome.SUCCESSFUL,
            "modify": TaskOutcome.PARTIALLY_SUCCESSFUL,
            "improve": TaskOutcome.PARTIALLY_SUCCESSFUL,
            "reject": TaskOutcome.USER_REJECTED,
        }.get(action, TaskOutcome.UNKNOWN)
        events.append(
            LearningEvent.create(
                event_id=_legacy_event_id("feedback", item),
                event_type="feedback",
                action_signature=stable_identifier(
                    item.get("suggestion_preview", ""),
                    item.get("timestamp", ""),
                ),
                outcome=outcome,
                user_decision=action,
                created_at=str(
                    item.get("timestamp") or datetime.now(timezone.utc).isoformat()
                ),
                summary="Migrated user feedback",
                metadata={
                    "quality_score": item.get("quality_score", 0.5),
                    "legacy_source": "feedback.json",
                },
            )
        )
    return events, source_counts


class LearningAnalytics:
    """Analytics facade over the canonical event store and user preferences."""

    VALID_CATEGORIES = ("all", "preferences", "errors", "examples", "tools", "reflections")

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = Path(storage_dir or Path.home() / ".radsim" / "learning")
        self.store = LearningStore(storage_dir=self.storage_dir)

    def get_learning_stats(self) -> dict[str, Any]:
        from .events import ReflectionEngine
        from .preference_learner import PreferenceLearner
        from .proposals import ProposalEngine
        from .retrieval import ErrorAnalyzer, FewShotAssembler, ToolOptimizer

        errors = ErrorAnalyzer(storage_dir=self.storage_dir).get_error_stats()
        preferences = PreferenceLearner(storage_dir=self.storage_dir)
        feedback = preferences.get_feedback_summary()
        examples = FewShotAssembler(storage_dir=self.storage_dir).get_examples_stats()
        optimizer = ToolOptimizer(storage_dir=self.storage_dir)
        rankings = optimizer.get_tool_rankings()
        reflections = ReflectionEngine(storage_dir=self.storage_dir)
        rates = reflections.get_success_rate_by_category()
        total_tasks = sum(item["total_tasks"] for item in rates.values())
        weighted_success = sum(
            item["success_rate"] * item["total_tasks"] for item in rates.values()
        )
        return {
            "summary": {
                "total_errors_tracked": errors["total_errors"],
                "total_feedback_received": feedback["total"],
                "total_examples_stored": examples["total"],
                "total_tools_tracked": len(rankings),
                "overall_task_success_rate": weighted_success / total_tasks if total_tasks else 0,
                "total_tasks_completed": total_tasks,
            },
            "errors": errors,
            "feedback": feedback,
            "examples": examples,
            "tools": {
                "top_tools": rankings[:5],
                "slow_tools": optimizer.get_slow_tools(),
                "unreliable_tools": optimizer.get_unreliable_tools(),
            },
            "task_categories": rates,
            "learned_preferences": preferences.get_learned_preferences(),
            "improvement_opportunities": reflections.get_improvement_opportunities(),
            "self_improvement": ProposalEngine(storage_dir=self.storage_dir).get_stats(),
            "store": {
                "schema_version": STORE_SCHEMA_VERSION,
                "event_count": self.store.count(),
                "bounded_to": self.store.max_events,
                "migration": self.store.migration_info(),
            },
        }

    def export_learning_report(self, format: str = "text") -> str:
        stats = self.get_learning_stats()
        if format == "json":
            return json.dumps(stats, indent=2, default=str)
        summary = stats["summary"]
        return (
            "\nRADSIM LEARNING REPORT\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Tasks completed: {summary['total_tasks_completed']}\n"
            f"Verified success rate: {summary['overall_task_success_rate']:.1%}\n"
            f"Errors tracked: {summary['total_errors_tracked']}\n"
            f"Feedback received: {summary['total_feedback_received']}\n"
            f"Examples available: {summary['total_examples_stored']}\n"
            f"Tools tracked: {summary['total_tools_tracked']}\n"
            f"Canonical events: {stats['store']['event_count']}\n"
        )

    def audit_learned_preferences(self) -> dict[str, dict[str, Any]]:
        from .preference_learner import PreferenceLearner

        preferences = PreferenceLearner(storage_dir=self.storage_dir).get_learned_preferences()
        audit: dict[str, dict[str, Any]] = {}
        for category, values in preferences.items():
            if isinstance(values, dict):
                for key, value in values.items():
                    audit[f"{category}.{key}"] = {
                        "current_value": value,
                        "category": category,
                        "can_reset": True,
                    }
            else:
                audit[category] = {
                    "current_value": values,
                    "category": "general",
                    "can_reset": True,
                }
        return audit

    def reset_learning_category(self, category: str) -> dict[str, Any]:
        if category not in self.VALID_CATEGORIES:
            return {
                "success": False,
                "error": f"Invalid category: {category}",
                "valid_categories": list(self.VALID_CATEGORIES),
            }
        from .preference_learner import PreferenceLearner

        event_map = {
            "errors": {"error"},
            "examples": {"task_example"},
            "tools": {"tool_execution"},
            "reflections": {"task_completion", "task_revert"},
        }
        if category in ("all", "preferences"):
            PreferenceLearner(storage_dir=self.storage_dir).clear_preferences()
        # "all" must clear every stored event type, including feedback,
        # messages, API calls, proposal decisions, and extension lifecycle
        # records, or a user clearing their data keeps rows they were told
        # were deleted.
        targets = (
            self.store.event_types()
            if category == "all"
            else event_map.get(category, set())
        )
        if targets:
            self.store.delete(event_types=targets)
        return {"success": True, "message": f"Successfully reset '{category}' learning data."}

    def get_learning_timeline(self, days: int = 7) -> list[dict[str, Any]]:
        events = self.store.query(limit=min(self.store.max_events, max(1, days) * 500))
        grouped: dict[str, dict[str, Any]] = {}
        for event in events:
            date = event.created_at[:10]
            day = grouped.setdefault(
                date,
                {"date": date, "tasks_completed": 0, "errors_recorded": 0, "feedback_received": 0},
            )
            if event.event_type == "task_completion":
                day["tasks_completed"] += 1
            elif event.event_type == "error":
                day["errors_recorded"] += 1
            elif event.event_type == "feedback":
                day["feedback_received"] += 1
        return sorted(grouped.values(), key=lambda item: item["date"])[-max(1, days):]


_stores: dict[str, LearningStore] = {}
_analytics: LearningAnalytics | None = None


def get_learning_store(storage_dir: Path | None = None) -> LearningStore:
    directory = Path(storage_dir or Path.home() / ".radsim" / "learning").resolve()
    key = str(directory)
    if key not in _stores:
        _stores[key] = LearningStore(storage_dir=directory)
    return _stores[key]


def get_analytics() -> LearningAnalytics:
    global _analytics
    if _analytics is None:
        _analytics = LearningAnalytics()
    return _analytics


def get_learning_stats() -> dict[str, Any]:
    return get_analytics().get_learning_stats()


def export_learning_report(format: str = "text") -> str:
    return get_analytics().export_learning_report(format)


def reset_learning_category(category: str) -> dict[str, Any]:
    return get_analytics().reset_learning_category(category)
