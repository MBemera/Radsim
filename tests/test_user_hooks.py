"""User hooks: validation, persistence, firing, and fail-closed blocking."""

import json

import pytest

from radsim import user_hooks
from radsim.user_hooks import (
    MAX_USER_HOOKS,
    UserHook,
    add_user_hook,
    fire_hooks,
    fire_tool_hooks,
    load_user_hooks,
    remove_user_hook,
    save_user_hooks,
    set_user_hook_enabled,
    validate_hook_definition,
)


@pytest.fixture(autouse=True)
def isolated_hooks_file(tmp_path, monkeypatch):
    """Point HOOKS_FILE at a temp path so tests never touch ~/.radsim."""
    hooks_file = tmp_path / "hooks.json"
    monkeypatch.setattr(user_hooks, "HOOKS_FILE", hooks_file)
    return hooks_file


class TestValidation:
    """Every field is validated before a hook can be saved or run."""

    def test_valid_definition_passes(self):
        ok, error = validate_hook_definition("lint", "post_tool", "write_file", "echo ok", 10)
        assert ok is True

    def test_bad_name_rejected(self):
        for name in ("", "a" * 41, "has space", "semi;colon", "../traversal"):
            ok, _ = validate_hook_definition(name, "pre_tool", "*", "echo ok", 10)
            assert ok is False, name

    def test_unknown_event_rejected(self):
        ok, error = validate_hook_definition("x", "before_everything", "*", "echo ok", 10)
        assert ok is False
        assert "Invalid event" in error

    def test_command_goes_through_shell_validator(self):
        ok, error = validate_hook_definition("x", "pre_tool", "*", "echo $(rm -rf /)", 10)
        assert ok is False
        assert "rejected" in error

    def test_catastrophic_command_rejected(self):
        ok, _ = validate_hook_definition("x", "pre_tool", "*", "rm -rf /", 10)
        assert ok is False

    def test_timeout_bounds_enforced(self):
        assert validate_hook_definition("x", "pre_tool", "*", "echo ok", 0)[0] is False
        assert validate_hook_definition("x", "pre_tool", "*", "echo ok", 121)[0] is False
        assert validate_hook_definition("x", "pre_tool", "*", "echo ok", "5")[0] is False

    def test_control_characters_in_matcher_rejected(self):
        ok, _ = validate_hook_definition("x", "pre_tool", "evil\x1b[2K", "echo ok", 10)
        assert ok is False


class TestPersistence:
    """Hooks round-trip through hooks.json with limits and dedupe."""

    def test_add_list_remove_round_trip(self):
        result = add_user_hook("lint", "post_tool", "write_file", "echo ok")
        assert result["success"] is True

        hooks = load_user_hooks()
        assert len(hooks) == 1
        assert hooks[0].name == "lint"

        assert remove_user_hook("lint")["success"] is True
        assert load_user_hooks() == []

    def test_duplicate_names_rejected(self):
        add_user_hook("lint", "post_tool", "*", "echo ok")
        result = add_user_hook("lint", "pre_tool", "*", "echo ok")
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_hook_limit_enforced(self, monkeypatch):
        monkeypatch.setattr(user_hooks, "MAX_USER_HOOKS", 2)
        add_user_hook("one", "post_tool", "*", "echo ok")
        add_user_hook("two", "post_tool", "*", "echo ok")
        result = add_user_hook("three", "post_tool", "*", "echo ok")
        assert result["success"] is False
        assert "limit" in result["error"].lower()

    def test_enable_disable_round_trip(self):
        add_user_hook("lint", "post_tool", "*", "echo ok")
        assert set_user_hook_enabled("lint", False)["success"] is True
        assert load_user_hooks()[0].enabled is False
        assert set_user_hook_enabled("missing", True)["success"] is False

    def test_malformed_file_is_ignored(self, isolated_hooks_file):
        isolated_hooks_file.write_text("not json at all")
        assert load_user_hooks() == []
        isolated_hooks_file.write_text('{"a": "dict, not a list"}')
        assert load_user_hooks() == []

    def test_tampered_entries_are_skipped_on_load(self, isolated_hooks_file):
        entries = [
            {"name": "ok", "event": "post_tool", "matcher": "*", "command": "echo ok"},
            {"name": "bad;name", "event": "post_tool", "matcher": "*", "command": "echo ok"},
            {"name": "badcmd", "event": "post_tool", "matcher": "*", "command": "rm -rf /"},
            "not-a-dict",
        ]
        isolated_hooks_file.write_text(json.dumps(entries))
        hooks = load_user_hooks()
        assert [hook.name for hook in hooks] == ["ok"]

    def test_load_caps_entry_count(self, isolated_hooks_file):
        entries = [
            {"name": f"hook{n}", "event": "post_tool", "matcher": "*", "command": "echo ok"}
            for n in range(MAX_USER_HOOKS + 10)
        ]
        isolated_hooks_file.write_text(json.dumps(entries))
        assert len(load_user_hooks()) == MAX_USER_HOOKS


class TestFiring:
    """Hooks run as subprocesses; only pre_tool can block, and it fails closed."""

    def test_exit_zero_allows(self):
        save_user_hooks([UserHook("ok", "pre_tool", "*", "true")])
        proceed, reason = fire_hooks("pre_tool", tool_name="write_file")
        assert proceed is True

    def test_exit_two_blocks_with_stderr_reason(self):
        save_user_hooks(
            [UserHook("guard", "pre_tool", "git_push", "echo no pushes today >&2; exit 2")]
        )
        proceed, reason = fire_hooks("pre_tool", tool_name="git_push")
        assert proceed is False
        assert "guard" in reason
        assert "no pushes today" in reason

    def test_matcher_scopes_the_hook(self):
        save_user_hooks([UserHook("guard", "pre_tool", "git_*", "exit 2")])
        assert fire_hooks("pre_tool", tool_name="git_push")[0] is False
        assert fire_hooks("pre_tool", tool_name="write_file")[0] is True

    def test_disabled_hooks_do_not_fire(self):
        save_user_hooks([UserHook("guard", "pre_tool", "*", "exit 2", enabled=False)])
        assert fire_hooks("pre_tool", tool_name="write_file")[0] is True

    def test_pre_tool_hook_failure_fails_closed(self):
        save_user_hooks([UserHook("broken", "pre_tool", "*", "exit 7")])
        proceed, reason = fire_hooks("pre_tool", tool_name="write_file")
        assert proceed is False
        assert "failing closed" in reason

    def test_pre_tool_timeout_fails_closed(self):
        save_user_hooks([UserHook("slow", "pre_tool", "*", "sleep 5", timeout=1)])
        proceed, reason = fire_hooks("pre_tool", tool_name="write_file")
        assert proceed is False
        assert "timed out" in reason

    def test_tampered_command_blocks_at_run_time(self, isolated_hooks_file, monkeypatch):
        # Bypass save-time validation to simulate hand-editing hooks.json,
        # then also bypass load-time validation to prove the run-time check
        # alone still fails closed.
        hook = UserHook("tampered", "pre_tool", "*", "echo $(whoami)")
        monkeypatch.setattr(user_hooks, "load_user_hooks", lambda: [hook])
        proceed, reason = fire_hooks("pre_tool", tool_name="write_file")
        assert proceed is False
        assert "failed validation" in reason

    def test_post_tool_failure_warns_but_proceeds(self, capsys):
        save_user_hooks([UserHook("notify", "post_tool", "*", "exit 1")])
        proceed, reason = fire_hooks("post_tool", tool_name="write_file")
        assert proceed is True
        assert "notify" in capsys.readouterr().out

    def test_payload_arrives_on_stdin(self, tmp_path):
        capture = tmp_path / "payload.json"
        save_user_hooks([UserHook("capture", "pre_tool", "*", f"cat > {capture}")])
        fire_tool_hooks("pre_tool", "write_file", {"file_path": "a.py", "content": "x" * 5000})
        payload = json.loads(capture.read_text())
        assert payload["event"] == "pre_tool"
        assert payload["tool_name"] == "write_file"
        assert payload["tool_input"]["file_path"] == "a.py"
        assert len(payload["tool_input"]["content"]) < 5000  # truncated

    def test_no_hooks_file_means_everything_proceeds(self):
        assert fire_hooks("pre_tool", tool_name="anything") == (True, None)


class TestAgentWiring:
    """A blocking hook stops the tool call at the agent choke point."""

    def make_agent(self):
        from types import SimpleNamespace

        from radsim.agent import RadSimAgent

        agent = object.__new__(RadSimAgent)
        agent.config = SimpleNamespace(auto_confirm=True, trust_mode="medium", verbose=False)
        agent._rejected_writes = set()
        agent._mcp_manager = None
        agent._session_approve_shell = False
        return agent

    def test_pre_tool_block_reaches_execute_with_permission(self):
        save_user_hooks([UserHook("no-reads", "pre_tool", "read_file", "exit 2")])
        agent = self.make_agent()
        result = agent._execute_with_permission("read_file", {"file_path": "x.py"})
        assert result["success"] is False
        assert "no-reads" in result["error"]

    def test_allowed_call_dispatches_normally(self, monkeypatch):
        save_user_hooks([UserHook("noop", "pre_tool", "*", "true")])
        agent = self.make_agent()
        monkeypatch.setattr(
            "radsim.agent_policy.AgentPolicyMixin._dispatch_tool",
            lambda self, tool_name, tool_input: {"success": True, "stdout": "ok"},
        )
        result = agent._execute_with_permission("read_file", {"file_path": "x.py"})
        assert result["success"] is True

    def test_in_process_hooks_can_block_too(self):
        from radsim.hooks import HookType, get_hooks_manager

        manager = get_hooks_manager()

        def deny(context):
            context.should_proceed = False
            context.metadata["validation_error"] = "denied by python hook"
            return context

        manager.register(HookType.PRE_TOOL, deny)
        try:
            proceed, reason = fire_tool_hooks("pre_tool", "write_file", {})
            assert proceed is False
            assert "denied by python hook" in reason
        finally:
            manager.unregister(HookType.PRE_TOOL, deny)
