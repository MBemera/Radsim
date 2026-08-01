"""Tests for the sub-agent policy broker.

Every subagent tool call passes through the broker. These tests assert it
fails closed: outside the profile, disabled in settings, never-delegated,
background-unsafe, or pointed at a secret all deny.
"""

import threading
import time
import unittest
from unittest.mock import patch

import pytest

from radsim.sub_agent_policy import (
    EXECUTING_TOOLS,
    MUTATING_TOOLS,
    NEVER_DELEGATED_TOOLS,
    SubAgentPolicyBroker,
)
from radsim.sub_agent_profiles import ProfileError


class TestProfileAllowlist(unittest.TestCase):
    """A tool outside the selected profile is refused."""

    def test_allowed_tool_passes(self):
        broker = SubAgentPolicyBroker("explore")
        allowed, reason = broker.check("read_file", {"file_path": "radsim/agent.py"})
        assert allowed is True
        assert reason == ""

    def test_tool_outside_profile_is_denied(self):
        broker = SubAgentPolicyBroker("explore")
        allowed, reason = broker.check("write_file", {"file_path": "a.py", "content": "x"})
        assert allowed is False
        assert "outside the 'explore' profile" in reason

    def test_denied_tool_never_runs(self):
        broker = SubAgentPolicyBroker("explore")
        with patch.object(SubAgentPolicyBroker, "_run") as mock_run:
            result = broker.execute("write_file", {"file_path": "a.py", "content": "x"})
        mock_run.assert_not_called()
        assert result["success"] is False
        assert "BLOCKED by subagent policy" in result["error"]

    def test_unknown_profile_raises_at_construction(self):
        with pytest.raises(ProfileError):
            SubAgentPolicyBroker("nonexistent")

    def test_unknown_tool_name_is_denied(self):
        broker = SubAgentPolicyBroker("explore")
        allowed, _reason = broker.check("totally_made_up_tool", {})
        assert allowed is False

    def test_empty_tool_name_is_denied(self):
        broker = SubAgentPolicyBroker("explore")
        allowed, reason = broker.check("", {})
        assert allowed is False
        assert "no tool name" in reason

    def test_implement_profile_gets_only_its_allowlist(self):
        """The retired 'capable' tier handed over all 72 tools; 'implement' does not."""
        from radsim.sub_agent_profiles import get_tools_for_profile
        from radsim.tools.definitions import TOOL_DEFINITIONS

        tools = get_tools_for_profile("implement")
        names = {tool["name"] for tool in tools}

        assert len(tools) < len(TOOL_DEFINITIONS)
        assert "write_file" in names
        assert "run_shell_command" not in names
        assert "delete_file" not in names
        assert "git_commit" not in names
        assert "web_fetch" not in names


class TestNeverDelegatedTools(unittest.TestCase):
    """Some capabilities are refused for every profile."""

    def test_recursive_delegation_is_refused(self):
        for profile in ("explore", "review", "research", "verify", "implement"):
            broker = SubAgentPolicyBroker(profile)
            allowed, reason = broker.check("delegate_task", {"task_description": "spawn"})
            assert allowed is False, profile
            assert "never available to a subagent" in reason

    def test_no_profile_offers_delegate_task(self):
        from radsim.sub_agent_profiles import CAPABILITY_PROFILES

        for name, profile in CAPABILITY_PROFILES.items():
            assert "delegate_task" not in profile["tools"], name

    def test_self_extension_is_refused(self):
        broker = SubAgentPolicyBroker("implement")
        assert broker.check("add_tool", {})[0] is False
        assert broker.check("remove_tool", {})[0] is False

    def test_shell_escape_is_refused(self):
        broker = SubAgentPolicyBroker("implement")
        allowed, _reason = broker.check("run_shell_command", {"command": "cat .env"})
        assert allowed is False

    def test_outbound_messaging_and_deploys_are_refused(self):
        broker = SubAgentPolicyBroker("research")
        assert broker.check("send_telegram", {"message": "secrets"})[0] is False
        assert broker.check("deploy", {})[0] is False

    def test_memory_and_schedule_writes_are_refused(self):
        broker = SubAgentPolicyBroker("implement")
        assert broker.check("save_memory", {})[0] is False
        assert broker.check("forget_memory", {})[0] is False
        assert broker.check("schedule_task", {})[0] is False

    def test_git_writes_and_deletes_are_refused(self):
        broker = SubAgentPolicyBroker("implement")
        assert broker.check("git_commit", {"message": "x"})[0] is False
        assert broker.check("delete_file", {"file_path": "a.py"})[0] is False

    def test_never_delegated_beats_the_profile_allowlist(self):
        """Even if a profile listed one of these, the broker still refuses."""
        broker = SubAgentPolicyBroker("implement")
        broker.profile = dict(broker.profile)
        broker.profile["tools"] = frozenset(broker.profile["tools"]) | {"run_shell_command"}

        allowed, reason = broker.check("run_shell_command", {"command": "ls"})

        assert allowed is False
        assert "never available" in reason


class TestDisabledToolEnforcement(unittest.TestCase):
    """A tool the user switched off in /settings stays off for subagents."""

    def test_disabled_tool_is_denied(self):
        broker = SubAgentPolicyBroker("research")
        with patch("radsim.agent_config.AgentConfigManager.is_tool_enabled", return_value=False):
            allowed, reason = broker.check("web_fetch", {"url": "https://example.com"})
        assert allowed is False
        assert "disabled in agent settings" in reason

    def test_unreadable_policy_fails_closed(self):
        broker = SubAgentPolicyBroker("explore")
        with patch(
            "radsim.agent_config.get_agent_config_manager", side_effect=RuntimeError("boom")
        ):
            allowed, reason = broker.check("read_file", {"file_path": "radsim/agent.py"})
        assert allowed is False
        assert "could not be evaluated" in reason


class TestBackgroundLimits(unittest.TestCase):
    """A background job may not change state or run project code."""

    def test_background_mutation_is_denied(self):
        broker = SubAgentPolicyBroker("implement", background=True)
        allowed, reason = broker.check("write_file", {"file_path": "a.py", "content": "x"})
        assert allowed is False
        assert "background" in reason

    def test_background_execution_is_denied(self):
        broker = SubAgentPolicyBroker("verify", background=True)
        allowed, reason = broker.check("run_tests", {})
        assert allowed is False
        assert "background" in reason

    def test_foreground_mutation_is_allowed_under_implement(self):
        broker = SubAgentPolicyBroker("implement", background=False)
        allowed, _reason = broker.check("write_file", {"file_path": "notes.md", "content": "x"})
        assert allowed is True

    def test_background_reads_are_allowed(self):
        broker = SubAgentPolicyBroker("explore", background=True)
        allowed, _reason = broker.check("read_file", {"file_path": "radsim/agent.py"})
        assert allowed is True

    def test_mutating_and_executing_sets_are_disjoint_from_reads(self):
        from radsim.sub_agent_profiles import CAPABILITY_PROFILES

        explore_tools = CAPABILITY_PROFILES["explore"]["tools"]
        assert not (explore_tools & MUTATING_TOOLS)
        assert not (explore_tools & EXECUTING_TOOLS)
        assert not (explore_tools & NEVER_DELEGATED_TOOLS)


class TestPathBoundaries(unittest.TestCase):
    """Reads and writes stay inside the project, and never touch secrets."""

    def test_secret_read_is_denied(self):
        broker = SubAgentPolicyBroker("explore")
        allowed, reason = broker.check("read_file", {"file_path": ".env"})
        assert allowed is False
        assert "protected credentials" in reason

    def test_secret_read_is_denied_for_every_profile(self):
        for profile in ("explore", "review", "verify", "implement"):
            broker = SubAgentPolicyBroker(profile)
            allowed, _reason = broker.check("read_file", {"file_path": ".env"})
            assert allowed is False, profile

    def test_private_key_read_is_denied(self):
        broker = SubAgentPolicyBroker("explore")
        assert broker.check("read_file", {"file_path": "id_rsa"})[0] is False

    def test_path_traversal_is_denied(self):
        broker = SubAgentPolicyBroker("explore")
        allowed, _reason = broker.check("read_file", {"file_path": "../../etc/passwd"})
        assert allowed is False

    def test_absolute_path_outside_project_is_denied(self):
        broker = SubAgentPolicyBroker("explore")
        allowed, _reason = broker.check("read_file", {"file_path": "/etc/passwd"})
        assert allowed is False

    def test_list_of_paths_is_checked(self):
        broker = SubAgentPolicyBroker("explore")
        allowed, reason = broker.check(
            "read_many_files", {"file_paths": ["radsim/agent.py", ".env"]}
        )
        assert allowed is False
        assert "protected credentials" in reason

    def test_multi_edit_paths_are_checked(self):
        broker = SubAgentPolicyBroker("implement")
        allowed, _reason = broker.check(
            "multi_edit", {"edits": [{"file_path": "../outside.py"}]}
        )
        assert allowed is False


class TestCallBudgetAndCancellation(unittest.TestCase):
    """Bounded work: a call ceiling, and cancellation that actually stops."""

    def test_call_limit_is_enforced(self):
        broker = SubAgentPolicyBroker("explore", max_tool_calls=2)
        with patch.object(SubAgentPolicyBroker, "_run", return_value={"success": True}):
            broker.execute("read_file", {"file_path": "radsim/agent.py"})
            broker.execute("read_file", {"file_path": "radsim/agent.py"})
            third = broker.execute("read_file", {"file_path": "radsim/agent.py"})

        assert broker.call_count == 2
        assert third["success"] is False
        assert "limit reached" in third["error"]

    def test_cancellation_denies_further_calls(self):
        cancel_event = threading.Event()
        broker = SubAgentPolicyBroker("explore", cancel_event=cancel_event)

        assert broker.check("read_file", {"file_path": "radsim/agent.py"})[0] is True
        cancel_event.set()
        allowed, reason = broker.check("read_file", {"file_path": "radsim/agent.py"})

        assert allowed is False
        assert "cancelled" in reason

    def test_cancelled_broker_reports_cancelled(self):
        cancel_event = threading.Event()
        broker = SubAgentPolicyBroker("explore", cancel_event=cancel_event)
        assert broker.is_cancelled() is False
        cancel_event.set()
        assert broker.is_cancelled() is True

    def test_expired_deadline_denies_further_calls(self):
        broker = SubAgentPolicyBroker("explore", timeout_seconds=0.0001)
        time.sleep(0.001)

        allowed, reason = broker.check("read_file", {"file_path": "radsim/agent.py"})

        assert allowed is False
        assert "time limit" in reason

    def test_deadline_is_distinct_from_cancellation(self):
        broker = SubAgentPolicyBroker("explore", timeout_seconds=0.0001)
        time.sleep(0.001)

        assert broker.is_expired() is True
        assert broker.is_cancelled() is False
        assert broker.should_stop() is True

    def test_a_live_task_is_not_stopped(self):
        broker = SubAgentPolicyBroker("explore", timeout_seconds=60)
        assert broker.should_stop() is False

    def test_timeout_can_be_disabled_for_direct_calls(self):
        broker = SubAgentPolicyBroker("explore", timeout_seconds=0)
        assert broker.deadline is None
        assert broker.is_expired() is False


class TestExecutionRouting(unittest.TestCase):
    """Approved calls run through the configured executor, never around it."""

    def test_executor_receives_approved_calls(self):
        calls = []

        def fake_executor(tool_name, tool_input):
            calls.append((tool_name, tool_input))
            return {"success": True}

        broker = SubAgentPolicyBroker("explore", executor=fake_executor)
        broker.execute("read_file", {"file_path": "radsim/agent.py"})

        assert calls == [("read_file", {"file_path": "radsim/agent.py"})]

    def test_executor_is_skipped_for_denied_calls(self):
        calls = []
        broker = SubAgentPolicyBroker(
            "explore", executor=lambda name, args: calls.append(name) or {"success": True}
        )
        broker.execute("write_file", {"file_path": "a.py", "content": "x"})
        assert calls == []

    def test_executor_failure_becomes_a_tool_error(self):
        def failing_executor(_tool_name, _tool_input):
            raise RuntimeError("disk on fire")

        broker = SubAgentPolicyBroker("explore", executor=failing_executor)
        result = broker.execute("read_file", {"file_path": "radsim/agent.py"})

        assert result["success"] is False
        assert "disk on fire" in result["error"]

    def test_execute_blocks_returns_tool_results(self):
        broker = SubAgentPolicyBroker(
            "explore", executor=lambda name, args: {"success": True, "content": "data"}
        )
        results = broker.execute_blocks(
            [
                {"id": "t1", "name": "read_file", "input": {"file_path": "radsim/agent.py"}},
                {"id": "t2", "name": "write_file", "input": {"file_path": "a.py"}},
            ]
        )

        assert results[0]["tool_use_id"] == "t1"
        assert "is_error" not in results[0]
        assert results[1]["tool_use_id"] == "t2"
        assert results[1]["is_error"] is True

    def test_summary_records_names_not_arguments(self):
        broker = SubAgentPolicyBroker("explore")
        broker.execute("read_file", {"file_path": ".env"})
        summary = broker.summary()

        assert summary["profile"] == "explore"
        assert summary["denied"] == ["read_file"]
        assert "file_path" not in str(summary)
        assert ".env" not in str(summary)


if __name__ == "__main__":
    unittest.main()
