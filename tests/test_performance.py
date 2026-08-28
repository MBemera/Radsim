"""Tests for opt-in structured performance telemetry."""

from __future__ import annotations

import json
import stat

from radsim.hooks import HookContext, HooksManager, HookType
from radsim.performance import (
    PerformanceTelemetry,
    bind_performance_context,
    request_payload_metrics,
    reset_performance_context,
)


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_disabled_telemetry_does_not_create_a_file(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=False)

    assert telemetry.emit("turn_started", turn_id="turn-1") is False
    assert not path.exists()


def test_telemetry_is_disabled_by_default(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path)

    assert telemetry.enabled is False
    assert telemetry.emit("turn_started", turn_id="turn-default") is False
    assert not path.exists()


def test_telemetry_writes_only_allowlisted_bounded_scalars(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)

    assert telemetry.emit(
        "tool_execution",
        turn_id="turn-1",
        tool_name="read_file\n",
        duration_ms=1.25,
        success=True,
        raw_prompt="never store this",
        tool_input={"api_key": "secret"},
    )

    record = _records(path)[0]
    assert record["event"] == "tool_execution"
    assert record["tool_name"] == "read_file"
    assert record["duration_ms"] == 1.25
    assert "raw_prompt" not in record
    assert "tool_input" not in record
    assert "secret" not in path.read_text(encoding="utf-8")
    if hasattr(stat, "S_IMODE"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_unknown_event_is_rejected(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)

    assert telemetry.emit("prompt_contents", turn_id="turn-1") is False
    assert not path.exists()


def test_small_telemetry_file_rotates(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True, max_bytes=1_024, backup_count=1)

    for index in range(30):
        telemetry.emit(
            "provider_response",
            turn_id=f"turn-{index}",
            model="m" * 200,
            duration_ms=1.0,
            success=True,
        )

    assert path.exists()
    assert path.with_name("performance.jsonl.1").exists()


def test_hook_execution_uses_active_turn_context(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)
    manager = HooksManager()
    manager.register(HookType.PRE_API, lambda context: context, owner="test")
    token = bind_performance_context(telemetry, "turn-hook")
    try:
        manager.execute(HookType.PRE_API, HookContext(hook_type=HookType.PRE_API))
    finally:
        reset_performance_context(token)

    record = _records(path)[0]
    assert record["event"] == "hook_execution"
    assert record["turn_id"] == "turn-hook"
    assert record["hook_type"] == "pre_api"
    assert record["hook_owner"] == "test"
    assert record["success"] is True


def test_request_metrics_capture_sizes_not_content():
    metrics = request_payload_metrics(
        "private prompt",
        [{"name": "read_file", "description": "private schema text"}],
    )

    assert metrics == {
        "system_prompt_chars": 14,
        "system_prompt_tokens": 4,
        "tool_schema_count": 1,
        "tool_schema_chars": 58,
        "tool_schema_tokens": 15,
    }
