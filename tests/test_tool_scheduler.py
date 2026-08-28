"""Ordering, policy, cancellation, and race tests for bounded parallel reads."""

from __future__ import annotations

import threading
import time

import pytest

from radsim.agent_constants import CONFIRMATION_TOOLS, READ_ONLY_TOOLS
from radsim.tool_scheduler import (
    MAX_PARALLEL_WORKERS,
    MIN_PARALLEL_GROUP,
    PARALLEL_SAFE_TOOLS,
    PARALLEL_TOOLS_ENV_VAR,
    ParallelPlan,
    parallel_tools_enabled,
    plan_parallel_group,
    run_parallel_group,
)
from radsim.tools import TOOL_DEFINITIONS

ON = {PARALLEL_TOOLS_ENV_VAR: "1"}
OFF: dict[str, str] = {}


def _call(name, **tool_input):
    return {"name": name, "input": dict(tool_input), "id": f"id-{name}-{len(tool_input)}"}


def _reads(count):
    return [
        {"name": "read_file", "input": {"file_path": f"file-{index}.py"}, "id": f"id-{index}"}
        for index in range(count)
    ]


def _never_confirms(tool_name, tool_input):
    return False


def _plan(tool_uses, **overrides):
    options = {"needs_confirmation": _never_confirms, "environ": ON}
    options.update(overrides)
    return plan_parallel_group(tool_uses, **options)


def test_the_allowlist_is_read_only_and_never_needs_confirmation():
    assert PARALLEL_SAFE_TOOLS <= READ_ONLY_TOOLS
    assert not PARALLEL_SAFE_TOOLS & CONFIRMATION_TOOLS


def test_every_allowlisted_tool_is_registered():
    registry = {tool["name"] for tool in TOOL_DEFINITIONS}

    assert PARALLEL_SAFE_TOOLS <= registry


@pytest.mark.parametrize(
    "tool_name",
    [
        "write_file",
        "replace_in_file",
        "apply_patch",
        "run_shell_command",
        "run_tests",
        "git_commit",
        "git_checkout",
        "database_query",
        "deploy",
        "delete_file",
        "multi_edit",
        "batch_replace",
    ],
)
def test_mutating_tools_are_never_allowlisted(tool_name):
    assert tool_name not in PARALLEL_SAFE_TOOLS


def test_the_flag_is_off_by_default():
    assert parallel_tools_enabled({}) is False
    assert parallel_tools_enabled({PARALLEL_TOOLS_ENV_VAR: "0"}) is False
    assert parallel_tools_enabled({PARALLEL_TOOLS_ENV_VAR: "1"}) is True
    assert parallel_tools_enabled({PARALLEL_TOOLS_ENV_VAR: " On "}) is True


def test_no_group_is_planned_when_the_flag_is_off():
    plan = _plan(_reads(4), environ=OFF)

    assert plan.is_parallel is False
    assert plan.indexes == ()
    assert plan.skipped_reason == "disabled"


def test_a_group_of_independent_reads_is_planned():
    plan = _plan(_reads(3))

    assert plan.indexes == (0, 1, 2)
    assert plan.worker_count == 3
    assert plan.skipped_reason == ""


def test_the_worker_count_is_bounded():
    plan = _plan(_reads(12))

    assert plan.worker_count == MAX_PARALLEL_WORKERS
    assert len(plan.indexes) == 12


def test_a_single_call_is_left_serial():
    plan = _plan(_reads(1))

    assert plan.is_parallel is False
    assert plan.skipped_reason == "group_too_small"
    assert MIN_PARALLEL_GROUP == 2


def test_the_group_stops_at_the_first_unsafe_call():
    tool_uses = _reads(2) + [_call("write_file", file_path="out.py")] + _reads(2)

    plan = _plan(tool_uses)

    assert plan.indexes == (0, 1)


def test_a_leading_write_disables_the_whole_group():
    tool_uses = [_call("write_file", file_path="out.py")] + _reads(3)

    plan = _plan(tool_uses)

    assert plan.is_parallel is False
    assert plan.skipped_reason == "group_too_small"


def test_shell_and_test_runs_are_never_grouped():
    for tool_name in ("run_shell_command", "run_tests"):
        plan = _plan([_call(tool_name, command="ls")] + _reads(3))

        assert plan.is_parallel is False


def test_a_confirmation_requiring_read_stops_the_group():
    tool_uses = _reads(4)

    plan = _plan(
        tool_uses,
        needs_confirmation=lambda name, tool_input: tool_input["file_path"] == "file-2.py",
    )

    assert plan.indexes == (0, 1)


def test_a_leading_confirmation_requiring_read_disables_the_group():
    plan = _plan(_reads(3), needs_confirmation=lambda name, tool_input: True)

    assert plan.is_parallel is False


def test_order_sensitive_hooks_disable_the_group():
    plan = _plan(_reads(4), hooks_present=True)

    assert plan.is_parallel is False
    assert plan.skipped_reason == "order_sensitive_hooks"


def test_a_corrupted_argument_stops_the_group():
    tool_uses = _reads(2)
    tool_uses.append({"name": "read_file", "input": {"__parse_error__": "bad json"}, "id": "x"})
    tool_uses.extend(_reads(2))

    plan = _plan(tool_uses)

    assert plan.indexes == (0, 1)


def test_non_dict_arguments_stop_the_group():
    tool_uses = _reads(2) + [{"name": "read_file", "input": "not-a-dict", "id": "x"}]

    plan = _plan(tool_uses)

    assert plan.indexes == (0, 1)


def test_an_empty_round_plans_nothing():
    plan = _plan([])

    assert plan.is_parallel is False


def test_results_are_returned_by_original_index():
    tool_uses = _reads(4)
    plan = _plan(tool_uses)

    def execute(tool_name, tool_input):
        # Finish in reverse order so completion order cannot leak into results.
        time.sleep(0.02 * (4 - int(tool_input["file_path"][5])))
        return {"success": True, "path": tool_input["file_path"]}

    completed = run_parallel_group(execute, tool_uses, plan)

    assert sorted(completed) == [0, 1, 2, 3]
    for index in completed:
        result, duration_ms = completed[index]
        assert result["path"] == f"file-{index}.py"
        assert duration_ms > 0


def test_the_group_actually_runs_concurrently():
    tool_uses = _reads(4)
    plan = _plan(tool_uses)
    barrier = threading.Barrier(4, timeout=5)

    def execute(tool_name, tool_input):
        barrier.wait()
        return {"success": True}

    completed = run_parallel_group(execute, tool_uses, plan)

    assert len(completed) == 4


def test_concurrency_never_exceeds_the_worker_count():
    tool_uses = _reads(12)
    plan = _plan(tool_uses)
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def execute(tool_name, tool_input):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.01)
        with lock:
            state["active"] -= 1
        return {"success": True}

    run_parallel_group(execute, tool_uses, plan)

    assert state["peak"] <= MAX_PARALLEL_WORKERS


def test_a_failing_call_does_not_lose_the_others():
    tool_uses = _reads(4)
    plan = _plan(tool_uses)

    def execute(tool_name, tool_input):
        if tool_input["file_path"] == "file-1.py":
            return {"success": False, "error": "Tool crashed: ValueError"}
        return {"success": True}

    completed = run_parallel_group(execute, tool_uses, plan)

    assert len(completed) == 4
    assert completed[1][0]["success"] is False
    assert completed[0][0]["success"] is True


def test_a_propagating_exception_reaches_the_caller():
    tool_uses = _reads(3)
    plan = _plan(tool_uses)

    def execute(tool_name, tool_input):
        raise RuntimeError("protection stop")

    with pytest.raises(RuntimeError):
        run_parallel_group(execute, tool_uses, plan)


def test_an_interrupt_before_dispatch_runs_nothing():
    tool_uses = _reads(4)
    plan = _plan(tool_uses)
    interrupted = threading.Event()
    interrupted.set()
    calls = []

    def execute(tool_name, tool_input):
        calls.append(tool_input["file_path"])
        return {"success": True}

    completed = run_parallel_group(execute, tool_uses, plan, interrupted=interrupted)

    assert completed == {}
    assert calls == []


def test_an_interrupt_mid_round_stops_further_dispatch():
    tool_uses = _reads(12)
    plan = _plan(tool_uses)
    interrupted = threading.Event()
    lock = threading.Lock()
    calls = []

    def execute(tool_name, tool_input):
        with lock:
            calls.append(tool_input["file_path"])
            if len(calls) >= 4:
                interrupted.set()
        time.sleep(0.01)
        return {"success": True}

    completed = run_parallel_group(execute, tool_uses, plan, interrupted=interrupted)

    assert len(calls) < 12
    assert set(completed) <= set(plan.indexes)


def test_a_non_parallel_plan_executes_nothing():
    def execute(tool_name, tool_input):
        raise AssertionError("should not run")

    assert run_parallel_group(execute, _reads(2), ParallelPlan((), 0, "disabled")) == {}
