"""Tests for opt-in structured performance telemetry."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from radsim.hooks import HookContext, HooksManager, HookType
from radsim.performance import (
    TELEMETRY_ENV_VAR,
    PerformanceTelemetry,
    bind_performance_context,
    emit_active_performance_event,
    estimate_tokens,
    request_payload_metrics,
    reset_performance_context,
)

ROTATION_EVENT = "turn_started"
ROTATION_FIELDS = {"turn_id": "turn-rotate", "model": "m" * 200}


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _record_bytes(tmp_path):
    """Return the encoded length of one rotation-fixture record, without its newline."""
    probe = tmp_path / "probe.jsonl"
    telemetry = PerformanceTelemetry(probe, enabled=True)
    assert telemetry.emit(ROTATION_EVENT, **ROTATION_FIELDS)
    return len(probe.read_text(encoding="utf-8").splitlines()[0])


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


def test_memory_stats_write_every_count_field_without_payloads(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)

    assert telemetry.emit(
        "memory_stats",
        turn_id="turn-memory",
        retained_messages=400,
        message_evictions=12,
        released_media_blocks=3,
        injected_job_ids=100,
        background_jobs=100,
        background_running_jobs=4,
        background_finished_jobs=96,
        background_job_evictions=7,
        raw_prompt="must not be recorded",
    )

    record = _records(path)[0]
    assert record == {
        "schema_version": 1,
        "timestamp": record["timestamp"],
        "event": "memory_stats",
        "turn_id": "turn-memory",
        "retained_messages": 400,
        "message_evictions": 12,
        "released_media_blocks": 3,
        "injected_job_ids": 100,
        "background_jobs": 100,
        "background_running_jobs": 4,
        "background_finished_jobs": 96,
        "background_job_evictions": 7,
    }
    assert "must not be recorded" not in path.read_text(encoding="utf-8")


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


def test_request_metrics_measure_unicode_schemas_unescaped():
    metrics = request_payload_metrics("", [{"name": "read_file", "description": "café"}])

    assert metrics["tool_schema_chars"] == 43
    assert metrics["tool_schema_tokens"] == 11


def test_estimate_tokens_rounds_up_only_for_partial_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_active_performance_event_is_dropped_without_a_bound_turn():
    assert emit_active_performance_event("turn_started") is False


def test_telemetry_clamps_rotation_bounds():
    telemetry = PerformanceTelemetry("performance.jsonl", max_bytes=0, backup_count=-5)

    assert telemetry.max_bytes == 1_024
    assert telemetry.backup_count == 0
    assert telemetry._failed is False


def test_from_environment_uses_the_radsim_log_path(monkeypatch):
    monkeypatch.delenv(TELEMETRY_ENV_VAR, raising=False)

    telemetry = PerformanceTelemetry.from_environment()

    assert telemetry.path == Path.home() / ".radsim" / "logs" / "performance.jsonl"
    assert telemetry.enabled is False


def test_from_environment_enables_telemetry_for_truthy_values(monkeypatch):
    for raw in ("1", "true", "TRUE", " yes ", "on"):
        monkeypatch.setenv(TELEMETRY_ENV_VAR, raw)

        assert PerformanceTelemetry.from_environment().enabled is True


def test_from_environment_leaves_telemetry_disabled_for_other_values(monkeypatch):
    for raw in ("0", "false", "maybe", ""):
        monkeypatch.setenv(TELEMETRY_ENV_VAR, raw)

        assert PerformanceTelemetry.from_environment().enabled is False


def test_emit_stops_permanently_after_a_write_failure(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)
    telemetry._failed = True

    assert telemetry.emit("turn_started", turn_id="turn-1") is False
    assert not path.exists()


def test_emit_records_a_utc_timestamp(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)

    assert telemetry.emit("turn_started", turn_id="turn-1")
    assert _records(path)[0]["timestamp"].endswith("+00:00")


def test_disallowed_field_does_not_drop_later_allowed_fields(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)

    assert telemetry.emit(
        "tool_execution",
        raw_prompt="never store this",
        turn_id="turn-1",
        tool_name="read_file",
    )

    record = _records(path)[0]
    assert record["turn_id"] == "turn-1"
    assert record["tool_name"] == "read_file"
    assert "raw_prompt" not in record


def test_emit_writes_compact_sorted_ascii_json(tmp_path):
    path = tmp_path / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)

    assert telemetry.emit("tool_execution", turn_id="turn-1", tool_name="café", duration_ms=1.5)

    line = path.read_text(encoding="utf-8").splitlines()[0]
    assert line.isascii()
    assert "caf\\u00e9" in line
    assert ", " not in line
    assert ": " not in line
    keys = list(json.loads(line))
    assert keys == sorted(keys)


def test_emit_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "logs" / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)

    assert telemetry.emit("turn_started", turn_id="turn-1") is True
    assert path.exists()


def test_emit_restricts_the_log_directory_to_the_owner(tmp_path):
    path = tmp_path / "logs" / "performance.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)

    assert telemetry.emit("turn_started", turn_id="turn-1") is True
    if hasattr(stat, "S_IMODE"):
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_file_already_at_the_limit_rotates(tmp_path):
    path = tmp_path / "performance.jsonl"
    filler = b"x" * 2_048
    path.write_bytes(filler)
    telemetry = PerformanceTelemetry(path, enabled=True, max_bytes=2_048, backup_count=1)

    assert telemetry.emit(ROTATION_EVENT, **ROTATION_FIELDS) is True
    assert path.with_name("performance.jsonl.1").read_bytes() == filler


def test_a_record_that_exactly_fills_the_limit_is_not_rotated(tmp_path):
    max_bytes = 2_048
    path = tmp_path / "performance.jsonl"
    path.write_bytes(b"x" * (max_bytes - _record_bytes(tmp_path) - 1))
    telemetry = PerformanceTelemetry(path, enabled=True, max_bytes=max_bytes, backup_count=1)

    assert telemetry.emit(ROTATION_EVENT, **ROTATION_FIELDS) is True
    assert not path.with_name("performance.jsonl.1").exists()
    assert path.stat().st_size == max_bytes


def test_a_record_that_overflows_the_limit_by_one_byte_rotates(tmp_path):
    max_bytes = 2_048
    path = tmp_path / "performance.jsonl"
    filler = b"x" * (max_bytes - _record_bytes(tmp_path))
    path.write_bytes(filler)
    telemetry = PerformanceTelemetry(path, enabled=True, max_bytes=max_bytes, backup_count=1)

    assert telemetry.emit(ROTATION_EVENT, **ROTATION_FIELDS) is True
    assert path.with_name("performance.jsonl.1").read_bytes() == filler


def test_rotation_shifts_every_backup_down_one_slot(tmp_path):
    path = tmp_path / "performance.jsonl"
    path.write_bytes(b"current")
    for index, content in ((1, b"first"), (2, b"second"), (3, b"third"), (4, b"stale")):
        path.with_name(f"performance.jsonl.{index}").write_bytes(content)
    telemetry = PerformanceTelemetry(path, enabled=True, backup_count=3)

    telemetry._rotate()

    assert not path.exists()
    assert path.with_name("performance.jsonl.1").read_bytes() == b"current"
    assert path.with_name("performance.jsonl.2").read_bytes() == b"first"
    assert path.with_name("performance.jsonl.3").read_bytes() == b"second"
    assert path.with_name("performance.jsonl.4").read_bytes() == b"stale"
