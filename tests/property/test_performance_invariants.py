"""Property tests for performance-critical and safety-critical invariants."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from radsim.context_budget import MAX_CONTEXT_SETTING_TOKENS, ContextBudget
from radsim.learning.events import LearningEvent, TaskOutcome
from radsim.learning.store import LearningStore
from radsim.performance import PerformanceTelemetry
from radsim.response_validator import sanitize_tool_input, validate_response_structure
from radsim.tool_schema import canonicalize_tool_schemas
from radsim.tools.validation import validate_shell_command

PROPERTY_TEST_SETTINGS = settings(max_examples=100, deadline=None)


@PROPERTY_TEST_SETTINGS
@given(
    model_tokens=st.integers(min_value=1, max_value=MAX_CONTEXT_SETTING_TOKENS),
    configured_tokens=st.integers(min_value=0, max_value=MAX_CONTEXT_SETTING_TOKENS),
    output_tokens=st.integers(min_value=1, max_value=MAX_CONTEXT_SETTING_TOKENS),
    recovery_tokens=st.integers(min_value=0, max_value=MAX_CONTEXT_SETTING_TOKENS),
    remaining_tokens=st.one_of(
        st.none(),
        st.integers(min_value=0, max_value=MAX_CONTEXT_SETTING_TOKENS),
    ),
)
def test_context_budget_never_exceeds_any_active_limit(
    model_tokens,
    configured_tokens,
    output_tokens,
    recovery_tokens,
    remaining_tokens,
):
    budget = ContextBudget(
        model_context_tokens=model_tokens,
        configured_input_tokens=configured_tokens,
        output_reserve_tokens=output_tokens,
        recovery_tokens=recovery_tokens,
        remaining_session_input_tokens=remaining_tokens,
    )

    assert 0 <= budget.prune_target_tokens <= budget.effective_input_tokens
    assert budget.effective_input_tokens <= budget.provider_input_tokens
    if configured_tokens:
        assert budget.effective_input_tokens <= configured_tokens
    if remaining_tokens is not None:
        assert budget.effective_input_tokens <= remaining_tokens


@PROPERTY_TEST_SETTINGS
@given(
    names=st.lists(
        st.text(
            alphabet=st.characters(categories=("Ll", "Lu", "Nd")),
            min_size=1,
            max_size=20,
        ),
        min_size=1,
        max_size=20,
        unique=True,
    ),
)
def test_tool_schema_canonicalisation_is_deterministic(names):
    tools = [
        {
            "description": f"Tool {name}",
            "name": name,
            "input_schema": {
                "required": ["value"],
                "properties": {"value": {"description": "value", "type": "string"}},
                "type": "object",
            },
        }
        for name in reversed(names)
    ]

    canonical = canonicalize_tool_schemas(tools)
    second_pass = canonicalize_tool_schemas(canonical)

    assert canonical == second_pass
    assert [tool["name"] for tool in canonical] == sorted(names)
    assert json.dumps(canonical, separators=(",", ":"), sort_keys=True) == json.dumps(
        second_pass,
        separators=(",", ":"),
        sort_keys=True,
    )


@PROPERTY_TEST_SETTINGS
@given(marker=st.sampled_from(["`", "$", "\x00", "\n", "\r", "<(", ">("]))
def test_dangerous_shell_syntax_always_fails_closed(marker):
    valid, reason = validate_shell_command(f"echo safe{marker}payload")

    assert valid is False
    assert reason


@PROPERTY_TEST_SETTINGS
@given(
    public_values=st.dictionaries(
        keys=st.text(min_size=1, max_size=20).filter(lambda value: not value.startswith("__")),
        values=st.integers() | st.text(max_size=40),
        max_size=10,
    ),
    private_values=st.dictionaries(
        keys=st.text(min_size=1, max_size=20).map(lambda value: f"__{value}"),
        values=st.integers() | st.text(max_size=40),
        min_size=1,
        max_size=10,
    ),
)
def test_tool_input_sanitisation_removes_every_private_marker(public_values, private_values):
    cleaned = sanitize_tool_input({**public_values, **private_values})

    assert cleaned == public_values
    assert all(not key.startswith("__") for key in cleaned)


@PROPERTY_TEST_SETTINGS
@given(block=st.one_of(st.none(), st.integers(), st.text(), st.lists(st.integers())))
def test_malformed_response_blocks_are_rejected(block):
    valid, reason = validate_response_structure({"content": [block]})

    assert valid is False
    assert reason


@PROPERTY_TEST_SETTINGS
@given(secret=st.text(min_size=1, max_size=200))
def test_unknown_telemetry_fields_never_reach_disk(secret):
    with tempfile.TemporaryDirectory() as storage_dir:
        path = Path(storage_dir) / "performance.jsonl"
        telemetry = PerformanceTelemetry(path, enabled=True)

        telemetry.emit(
            "tool_execution",
            turn_id="turn-property",
            tool_name="read_file",
            success=True,
            untrusted_content=secret,
        )

        record = json.loads(path.read_text(encoding="utf-8"))
        assert "untrusted_content" not in record
        assert set(record).issubset(
            {"event", "schema_version", "success", "timestamp", "tool_name", "turn_id"}
        )


@PROPERTY_TEST_SETTINGS
@given(event_count=st.integers(min_value=1, max_value=25))
def test_learning_batches_are_ordered_and_idempotent(event_count):
    with tempfile.TemporaryDirectory() as storage_dir:
        store = LearningStore(
            storage_dir=Path(storage_dir),
            max_events=100,
            migrate_legacy=False,
        )
        created_at = datetime.now(timezone.utc).isoformat()
        events = [
            LearningEvent.create(
                event_id=f"event-{index:03d}",
                task_id=f"task-{index:03d}",
                event_type="task_completion",
                outcome=TaskOutcome.SUCCESSFUL,
                summary=f"event {index}",
                created_at=created_at,
            )
            for index in range(event_count)
        ]

        assert store.append_many(events) == event_count
        assert store.append_many(events) == 0
        assert [event.event_id for event in store.query(limit=100)] == [
            event.event_id for event in events
        ]


@pytest.mark.parametrize("value", [True, False, 1.5, "100", object()])
def test_context_budget_rejects_non_integer_limits(value):
    with pytest.raises(ValueError):
        ContextBudget(model_context_tokens=value)
