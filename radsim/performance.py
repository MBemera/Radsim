"""Low-overhead, privacy-safe performance telemetry for RadSim."""

from __future__ import annotations

import json
import math
import os
import threading
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TELEMETRY_ENV_VAR = "RADSIM_PERFORMANCE_TELEMETRY"
DEFAULT_MAX_BYTES = 10_000_000
DEFAULT_BACKUP_COUNT = 3
TELEMETRY_SCHEMA_VERSION = 1

_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_EVENT_NAMES = {
    "hook_execution",
    "prompt_cache",
    "provider_request",
    "provider_response",
    "tool_execution",
    "tool_routing",
    "tool_routing_recovery",
    "turn_completed",
    "turn_started",
}
_ALLOWED_FIELDS = {
    "api_calls",
    "cache_read_input_tokens",
    "cache_write_input_tokens",
    "duration_ms",
    "error_type",
    "first_chunk_ms",
    "hook_name",
    "hook_owner",
    "hook_type",
    "input_chars",
    "input_tokens",
    "interrupted",
    "message_count",
    "model",
    "outcome",
    "output_tokens",
    "prompt_cache_applied",
    "prompt_cache_minimum_tokens",
    "prompt_cache_prefix_tokens",
    "prompt_cache_skipped_reason",
    "prompt_construction_ms",
    "provider",
    "request_assembly_ms",
    "request_index",
    "result_chars",
    "retry_attempts",
    "routed_group_count",
    "routed_groups",
    "routed_schema_tokens",
    "routed_tool_count",
    "routing_budget_tokens",
    "routing_dropped_groups",
    "routing_enabled",
    "routing_failed",
    "routing_recovered_group",
    "stop_reason",
    "success",
    "system_prompt_chars",
    "system_prompt_tokens",
    "tool_calls",
    "tool_name",
    "tool_schema_chars",
    "tool_schema_count",
    "tool_schema_tokens",
    "turn_id",
}
_MAX_STRING_CHARS = 256


class PerformanceTelemetry:
    """Append bounded structured events to an opt-in rotating JSONL file."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        enabled: bool = False,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
    ) -> None:
        self.enabled = bool(enabled and path)
        self.path = Path(path).expanduser() if path else None
        self.max_bytes = max(1_024, int(max_bytes))
        self.backup_count = max(0, int(backup_count))
        self._lock = threading.Lock()
        self._failed = False

    @classmethod
    def from_environment(cls) -> PerformanceTelemetry:
        """Create telemetry using the trusted process environment."""
        raw_enabled = os.environ.get(TELEMETRY_ENV_VAR, "")
        enabled = raw_enabled.strip().lower() in _TRUTHY_VALUES
        path = Path.home() / ".radsim" / "logs" / "performance.jsonl"
        return cls(path, enabled=enabled)

    def new_turn_id(self) -> str:
        """Return an opaque correlation identifier with no user content."""
        return uuid.uuid4().hex

    def emit(self, event: str, **fields: Any) -> bool:
        """Write one allowlisted event without exposing prompt or tool content."""
        if not self.enabled or self.path is None or self._failed:
            return False
        if event not in _EVENT_NAMES:
            return False

        record: dict[str, Any] = {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        for name, value in fields.items():
            if name not in _ALLOWED_FIELDS:
                continue
            normalized = _safe_scalar(value)
            if normalized is not None:
                record[name] = normalized

        encoded = json.dumps(
            record,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            with self._lock:
                self._prepare_destination(len(encoded) + 1)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(encoded)
                    handle.write("\n")
                _restrict_permissions(self.path, 0o600)
        except OSError:
            self._failed = True
            return False
        return True

    def _prepare_destination(self, incoming_bytes: int) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _restrict_permissions(self.path.parent, 0o700)
        if not self.path.exists():
            return
        if self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        self._rotate()

    def _rotate(self) -> None:
        assert self.path is not None
        if self.backup_count == 0:
            self.path.unlink(missing_ok=True)
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.backup_count}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                source.replace(self.path.with_name(f"{self.path.name}.{index + 1}"))
        if self.path.exists():
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))


def request_payload_metrics(system_prompt: str, tools: list[dict[str, Any]]) -> dict[str, int]:
    """Return provider payload counts without retaining the payload itself."""
    serialized_tools = json.dumps(
        tools,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "system_prompt_chars": len(system_prompt),
        "system_prompt_tokens": estimate_tokens(system_prompt),
        "tool_schema_count": len(tools),
        "tool_schema_chars": len(serialized_tools),
        "tool_schema_tokens": estimate_tokens(serialized_tools),
    }


def estimate_tokens(text: str) -> int:
    """Estimate tokens using RadSim's existing four-characters-per-token rule."""
    return (len(text) + 3) // 4 if text else 0


_active_telemetry: ContextVar[tuple[PerformanceTelemetry, str] | None] = ContextVar(
    "radsim_active_performance_telemetry",
    default=None,
)


def bind_performance_context(
    telemetry: PerformanceTelemetry,
    turn_id: str,
) -> Token[tuple[PerformanceTelemetry, str] | None]:
    """Bind telemetry to the current turn so lower layers can emit spans."""
    return _active_telemetry.set((telemetry, turn_id))


def reset_performance_context(token: Token[tuple[PerformanceTelemetry, str] | None]) -> None:
    """Restore the previous telemetry context."""
    _active_telemetry.reset(token)


def emit_active_performance_event(event: str, **fields: Any) -> bool:
    """Emit through the recorder bound to the current turn, if any."""
    active = _active_telemetry.get()
    if active is None:
        return False
    telemetry, turn_id = active
    return telemetry.emit(event, turn_id=turn_id, **fields)


def _safe_scalar(value: Any) -> bool | int | float | str | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        printable = "".join(character for character in value if character.isprintable())
        return printable[:_MAX_STRING_CHARS]
    return None


def _restrict_permissions(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass
