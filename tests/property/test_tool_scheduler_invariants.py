"""Property tests for bounded parallel tool-round invariants."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from radsim.tool_scheduler import (
    MAX_PARALLEL_WORKERS,
    MIN_PARALLEL_GROUP,
    PARALLEL_SAFE_TOOLS,
    PARALLEL_TOOLS_ENV_VAR,
    plan_parallel_group,
    run_parallel_group,
)

PROPERTY_TEST_SETTINGS = settings(max_examples=100, deadline=None)
ON = {PARALLEL_TOOLS_ENV_VAR: "1"}

UNSAFE_TOOLS = ("write_file", "run_shell_command", "git_commit", "apply_patch", "run_tests")
ANY_TOOL = tuple(sorted(PARALLEL_SAFE_TOOLS)) + UNSAFE_TOOLS

tool_use = st.builds(
    lambda name, argument: {"name": name, "input": {"value": argument}, "id": f"id-{argument}"},
    name=st.sampled_from(ANY_TOOL),
    argument=st.integers(min_value=0, max_value=99),
)

rounds = st.lists(tool_use, max_size=10)


def _never_confirms(tool_name, tool_input):
    return False


@PROPERTY_TEST_SETTINGS
@given(tool_uses=rounds)
def test_the_group_is_always_a_contiguous_leading_prefix(tool_uses):
    plan = plan_parallel_group(tool_uses, needs_confirmation=_never_confirms, environ=ON)

    assert plan.indexes == tuple(range(len(plan.indexes)))


@PROPERTY_TEST_SETTINGS
@given(tool_uses=rounds)
def test_only_allowlisted_tools_are_ever_grouped(tool_uses):
    plan = plan_parallel_group(tool_uses, needs_confirmation=_never_confirms, environ=ON)

    for index in plan.indexes:
        assert tool_uses[index]["name"] in PARALLEL_SAFE_TOOLS


@PROPERTY_TEST_SETTINGS
@given(tool_uses=rounds, confirm_at=st.integers(min_value=0, max_value=9))
def test_a_call_needing_confirmation_is_never_grouped(tool_uses, confirm_at):
    def needs_confirmation(tool_name, tool_input):
        return tool_input.get("value") == confirm_at

    plan = plan_parallel_group(tool_uses, needs_confirmation=needs_confirmation, environ=ON)

    for index in plan.indexes:
        assert tool_uses[index]["input"].get("value") != confirm_at


@PROPERTY_TEST_SETTINGS
@given(tool_uses=rounds, max_workers=st.integers(min_value=1, max_value=16))
def test_the_worker_count_is_always_bounded(tool_uses, max_workers):
    plan = plan_parallel_group(
        tool_uses,
        needs_confirmation=_never_confirms,
        environ=ON,
        max_workers=max_workers,
    )

    if plan.is_parallel:
        assert 1 <= plan.worker_count <= max_workers
        assert plan.worker_count <= len(plan.indexes)
        assert len(plan.indexes) >= MIN_PARALLEL_GROUP
    else:
        assert plan.indexes == ()
        assert plan.skipped_reason


@PROPERTY_TEST_SETTINGS
@given(tool_uses=rounds, hooks_present=st.booleans())
def test_hooks_and_the_flag_always_gate_the_group(tool_uses, hooks_present):
    plan = plan_parallel_group(
        tool_uses,
        needs_confirmation=_never_confirms,
        hooks_present=hooks_present,
        environ=ON,
    )
    disabled = plan_parallel_group(tool_uses, needs_confirmation=_never_confirms, environ={})

    if hooks_present:
        assert plan.indexes == ()
    assert disabled.indexes == ()
    assert disabled.skipped_reason == "disabled"


@PROPERTY_TEST_SETTINGS
@given(tool_uses=rounds)
def test_results_always_map_back_to_their_own_call(tool_uses):
    plan = plan_parallel_group(tool_uses, needs_confirmation=_never_confirms, environ=ON)

    def execute(tool_name, tool_input):
        return {"name": tool_name, "value": tool_input["value"]}

    completed = run_parallel_group(execute, tool_uses, plan)

    assert set(completed) <= set(plan.indexes)
    for index, (result, duration_ms) in completed.items():
        assert result["name"] == tool_uses[index]["name"]
        assert result["value"] == tool_uses[index]["input"]["value"]
        assert duration_ms >= 0


@PROPERTY_TEST_SETTINGS
@given(tool_uses=rounds)
def test_a_completed_group_never_exceeds_the_worker_bound(tool_uses):
    plan = plan_parallel_group(tool_uses, needs_confirmation=_never_confirms, environ=ON)

    assert plan.worker_count <= MAX_PARALLEL_WORKERS
