"""Tests for the Event Hooks system."""

import pytest

from radsim.hooks import (
    HookContext,
    HooksManager,
    HookType,
    create_budget_hook,
    create_notification_hook,
    create_validation_hook,
)


class TestHookType:
    """Test HookType enum."""

    def test_all_hook_types_exist(self):
        assert HookType.PRE_TOOL.value == "pre_tool"
        assert HookType.POST_TOOL.value == "post_tool"
        assert HookType.PRE_API.value == "pre_api"
        assert HookType.POST_API.value == "post_api"
        assert HookType.ON_ERROR.value == "on_error"
        assert HookType.PRE_MESSAGE.value == "pre_message"
        assert HookType.POST_MESSAGE.value == "post_message"


class TestHookContext:
    """Test HookContext dataclass."""

    def test_default_values(self):
        ctx = HookContext(hook_type=HookType.PRE_TOOL)
        assert ctx.tool_name == ""
        assert ctx.tool_input == {}
        assert ctx.should_proceed is True
        assert ctx.modified_input is None
        assert ctx.error is None

    def test_cancel_operation(self):
        ctx = HookContext(hook_type=HookType.PRE_TOOL)
        ctx.should_proceed = False
        assert ctx.should_proceed is False

    def test_modify_input(self):
        ctx = HookContext(
            hook_type=HookType.PRE_TOOL,
            tool_name="write_file",
            tool_input={"path": "/test.py"},
        )
        ctx.modified_input = {"path": "/safe/test.py"}
        assert ctx.modified_input["path"] == "/safe/test.py"


class TestHooksManager:
    """Test HooksManager registration and execution."""

    def test_register_and_execute(self):
        manager = HooksManager()
        called = []

        def my_hook(ctx):
            called.append(ctx.tool_name)
            return ctx

        manager.register(HookType.PRE_TOOL, my_hook)

        ctx = HookContext(hook_type=HookType.PRE_TOOL, tool_name="read_file")
        manager.execute(HookType.PRE_TOOL, ctx)

        assert called == ["read_file"]

    def test_multiple_hooks_execute_in_order(self):
        manager = HooksManager()
        order = []

        def hook_a(ctx):
            order.append("a")
            return ctx

        def hook_b(ctx):
            order.append("b")
            return ctx

        manager.register(HookType.PRE_TOOL, hook_a)
        manager.register(HookType.PRE_TOOL, hook_b)

        ctx = HookContext(hook_type=HookType.PRE_TOOL)
        manager.execute(HookType.PRE_TOOL, ctx)

        assert order == ["a", "b"]

    def test_hook_can_cancel_operation(self):
        manager = HooksManager()

        def blocking_hook(ctx):
            ctx.should_proceed = False
            return ctx

        def never_called(ctx):
            pytest.fail("This hook should not be called")

        manager.register(HookType.PRE_TOOL, blocking_hook)
        manager.register(HookType.PRE_TOOL, never_called)

        ctx = HookContext(hook_type=HookType.PRE_TOOL)
        result = manager.execute(HookType.PRE_TOOL, ctx)

        assert result.should_proceed is False

    def test_hook_can_modify_context(self):
        manager = HooksManager()

        def modify_hook(ctx):
            ctx.modified_input = {"sanitized": True}
            return ctx

        manager.register(HookType.PRE_TOOL, modify_hook)

        ctx = HookContext(hook_type=HookType.PRE_TOOL, tool_input={"raw": True})
        result = manager.execute(HookType.PRE_TOOL, ctx)

        assert result.modified_input == {"sanitized": True}

    def test_hook_error_does_not_crash(self):
        manager = HooksManager()

        def crashing_hook(ctx):
            raise RuntimeError("hook exploded")

        manager.register(HookType.PRE_TOOL, crashing_hook)

        ctx = HookContext(hook_type=HookType.PRE_TOOL)
        result = manager.execute(HookType.PRE_TOOL, ctx)

        assert "hook_error" in result.metadata
        assert "hook exploded" in result.metadata["hook_error"]

    def test_unregister(self):
        manager = HooksManager()
        called = []

        def my_hook(ctx):
            called.append(True)
            return ctx

        manager.register(HookType.PRE_TOOL, my_hook)
        manager.unregister(HookType.PRE_TOOL, my_hook)

        ctx = HookContext(hook_type=HookType.PRE_TOOL)
        manager.execute(HookType.PRE_TOOL, ctx)

        assert called == []

    def test_clear_specific_type(self):
        manager = HooksManager()

        manager.register(HookType.PRE_TOOL, lambda ctx: ctx)
        manager.register(HookType.POST_TOOL, lambda ctx: ctx)

        manager.clear(HookType.PRE_TOOL)

        assert len(manager._hooks[HookType.PRE_TOOL]) == 0
        assert len(manager._hooks[HookType.POST_TOOL]) == 1

    def test_clear_all(self):
        manager = HooksManager()

        manager.register(HookType.PRE_TOOL, lambda ctx: ctx)
        manager.register(HookType.POST_TOOL, lambda ctx: ctx)
        manager.register(HookType.ON_ERROR, lambda ctx: ctx)

        manager.clear()

        for hook_type in HookType:
            assert len(manager._hooks[hook_type]) == 0

    def test_hook_returning_none_preserves_context(self):
        manager = HooksManager()

        def none_hook(ctx):
            ctx.metadata["touched"] = True
            # Returning None instead of ctx

        manager.register(HookType.PRE_TOOL, none_hook)

        ctx = HookContext(hook_type=HookType.PRE_TOOL)
        result = manager.execute(HookType.PRE_TOOL, ctx)

        assert result.metadata.get("touched") is True


class TestBuiltInHookFactories:
    """Test hook factory functions."""

    def test_validation_hook_passes(self):
        def valid(tool_input):
            return True, ""

        hook = create_validation_hook(valid)
        ctx = HookContext(hook_type=HookType.PRE_TOOL, tool_input={"path": "/ok.py"})
        result = hook(ctx)
        assert result.should_proceed is True

    def test_validation_hook_blocks(self):
        def invalid(tool_input):
            return False, "path is dangerous"

        hook = create_validation_hook(invalid)
        ctx = HookContext(hook_type=HookType.PRE_TOOL, tool_input={"path": "/.env"})
        result = hook(ctx)
        assert result.should_proceed is False
        assert "path is dangerous" in result.metadata["validation_error"]

    def test_budget_hook_allows_under_budget(self):
        tracker = {"current_cost": 0.50}
        hook = create_budget_hook(max_cost=1.0, cost_tracker=tracker)

        ctx = HookContext(hook_type=HookType.PRE_API)
        result = hook(ctx)
        assert result.should_proceed is True

    def test_budget_hook_blocks_over_budget(self):
        tracker = {"current_cost": 1.50}
        hook = create_budget_hook(max_cost=1.0, cost_tracker=tracker)

        ctx = HookContext(hook_type=HookType.PRE_API)
        result = hook(ctx)
        assert result.should_proceed is False
        assert result.metadata["budget_exceeded"] is True

    def test_notification_hook_success(self):
        messages = []
        hook = create_notification_hook(messages.append)

        ctx = HookContext(
            hook_type=HookType.POST_TOOL,
            tool_name="read_file",
            tool_result={"success": True},
        )
        hook(ctx)
        assert len(messages) == 1
        assert "read_file" in messages[0]
        assert "completed" in messages[0]

    def test_notification_hook_failure(self):
        messages = []
        hook = create_notification_hook(messages.append)

        ctx = HookContext(
            hook_type=HookType.POST_TOOL,
            tool_name="write_file",
            tool_result={"success": False, "error": "disk full"},
        )
        hook(ctx)
        assert "failed" in messages[0]
        assert "disk full" in messages[0]
