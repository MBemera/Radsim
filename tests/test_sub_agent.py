"""Tests for the sub-agent runner.

Covers model resolution (fail-closed), profile wiring, the agentic tool loop
through the policy broker, cancellation, and result bounding.
"""

import threading
import unittest
from unittest.mock import MagicMock, patch

import pytest

from radsim.sub_agent import (
    MAX_RESULT_CHARS,
    SubAgentModelError,
    SubAgentResult,
    SubAgentTask,
    delegate_task,
    execute_subagent_task,
    get_available_models,
    resolve_subagent_model,
    stream_subagent_task,
)

VALID_PROVIDER = "openrouter"
VALID_MODEL = "moonshotai/kimi-k2.5"


def _task(**overrides):
    """Build a task with a valid saved selection unless overridden."""
    fields = {
        "task_description": "Summarise auth.py",
        "provider": VALID_PROVIDER,
        "model": VALID_MODEL,
        "profile": "explore",
    }
    fields.update(overrides)
    return SubAgentTask(**fields)


class TestAvailableModels(unittest.TestCase):
    """Model catalogue lookups are provider-aware."""

    def test_returns_models_for_a_known_provider(self):
        models = get_available_models(VALID_PROVIDER)
        assert len(models) > 0
        for model_id, description in models:
            assert isinstance(model_id, str)
            assert isinstance(description, str)

    def test_unknown_provider_returns_empty(self):
        assert get_available_models("not-a-provider") == []

    def test_every_provider_is_reachable(self):
        """Sub-agents are no longer OpenRouter-only."""
        assert get_available_models("claude")
        assert get_available_models("openai")


class TestModelResolutionFailsClosed(unittest.TestCase):
    """An unusable selection raises instead of substituting a model."""

    def test_unknown_model_raises(self):
        with pytest.raises(SubAgentModelError) as error:
            resolve_subagent_model(VALID_PROVIDER, "nonexistent-model-xyz")
        assert "not available" in str(error.value)

    def test_unknown_model_does_not_fall_back(self):
        """The old behaviour silently substituted Haiku. It must not return one."""
        with pytest.raises(SubAgentModelError) as error:
            resolve_subagent_model(VALID_PROVIDER, "nonexistent-model-xyz")
        assert "haiku" not in str(error.value).lower()

    def test_unknown_provider_raises(self):
        with pytest.raises(SubAgentModelError):
            resolve_subagent_model("not-a-provider", VALID_MODEL)

    def test_missing_provider_raises(self):
        with pytest.raises(SubAgentModelError):
            resolve_subagent_model(None, None)

    def test_missing_credential_raises_without_changing_selection(self, ):
        with patch("radsim.config.get_provider_api_key", return_value=None):
            with pytest.raises(SubAgentModelError) as error:
                resolve_subagent_model(VALID_PROVIDER, VALID_MODEL)
        message = str(error.value)
        assert "/login openrouter" in message
        assert "Neither model selection was changed" in message

    def test_valid_pair_resolves_with_key(self):
        with patch("radsim.config.get_provider_api_key", return_value="key-123"):
            provider, model, api_key = resolve_subagent_model(VALID_PROVIDER, VALID_MODEL)
        assert (provider, model, api_key) == (VALID_PROVIDER, VALID_MODEL, "key-123")


class TestUnknownProfileFailsClosed(unittest.TestCase):
    """An unknown profile is an error, not a permissive default."""

    def test_unknown_profile_returns_error_result(self):
        result = execute_subagent_task(_task(profile="nonexistent"))
        assert result.success is False
        assert "Unknown subagent profile" in result.error

    def test_unknown_profile_runs_no_tools(self):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            result = execute_subagent_task(_task(profile="nonexistent"))
        mock_create_client.assert_not_called()
        assert result.tool_calls == 0

    def test_retired_capable_tier_is_rejected(self):
        result = execute_subagent_task(_task(profile="capable"))
        assert result.success is False
        assert "has been removed" in result.error

    def test_legacy_fast_tier_maps_to_explore(self):
        with patch("radsim.config.get_provider_api_key", return_value="key"), patch(
            "radsim.sub_agent.create_client"
        ) as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"content": [{"type": "text", "text": "ok"}], "usage": {}}
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task(profile="fast"))
        assert result.profile_used == "explore"


class TestTaskExecution(unittest.TestCase):
    """The runner executes a bounded task against the supplied selection."""

    def setUp(self):
        self.key_patcher = patch("radsim.config.get_provider_api_key", return_value="test-key")
        self.key_patcher.start()
        self.addCleanup(self.key_patcher.stop)

    def test_successful_execution(self):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.return_value = {
                "content": [{"type": "text", "text": "Test response"}],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task())

        assert result.success is True
        assert result.content == "Test response"
        assert result.input_tokens == 10
        assert result.output_tokens == 20
        assert result.profile_used == "explore"

    def test_uses_the_supplied_provider_and_model(self):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"content": [], "usage": {}}
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task())

        assert mock_create_client.call_args[0][0] == VALID_PROVIDER
        assert mock_create_client.call_args[0][2] == VALID_MODEL
        assert result.model_used == VALID_MODEL
        assert result.provider_used == VALID_PROVIDER

    def test_execution_reports_api_errors(self):
        with patch("radsim.sub_agent.create_client", side_effect=Exception("API error")):
            result = execute_subagent_task(_task())
        assert result.success is False
        assert "API error" in result.error

    def test_reasoning_effort_is_threaded_into_the_client(self):
        with patch("radsim.config.resolve_reasoning_effort", return_value="high"), patch(
            "radsim.config.load_reasoning_effort", return_value="high"
        ), patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"content": [], "usage": {}}
            mock_create_client.return_value = mock_client
            execute_subagent_task(_task())

        mock_create_client.assert_called_once_with(
            VALID_PROVIDER, "test-key", VALID_MODEL, reasoning_effort="high"
        )

    def test_only_profile_tools_are_offered_to_the_model(self):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"content": [], "usage": {}}
            mock_create_client.return_value = mock_client
            execute_subagent_task(_task(profile="explore"))

        offered = {tool["name"] for tool in mock_client.chat.call_args[1]["tools"]}
        assert "read_file" in offered
        assert "write_file" not in offered
        assert "run_shell_command" not in offered
        assert "delegate_task" not in offered

    def test_oversized_result_is_capped(self):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.return_value = {
                "content": [{"type": "text", "text": "x" * (MAX_RESULT_CHARS + 5_000)}],
                "usage": {},
            }
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task())

        assert len(result.content) < MAX_RESULT_CHARS + 200
        assert "truncated" in result.content


class TestAgenticLoop(unittest.TestCase):
    """Tool calls route through the broker and feed back into the loop."""

    def setUp(self):
        self.key_patcher = patch("radsim.config.get_provider_api_key", return_value="test-key")
        self.key_patcher.start()
        self.addCleanup(self.key_patcher.stop)

    def test_tool_use_then_text(self):
        tool_response = {
            "content": [
                {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"file_path": "a.py"}}
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        text_response = {
            "content": [{"type": "text", "text": "Analysed."}],
            "usage": {"input_tokens": 20, "output_tokens": 15},
        }

        with patch("radsim.sub_agent.create_client") as mock_create_client, patch(
            "radsim.sub_agent_policy.SubAgentPolicyBroker._run",
            return_value={"success": True, "content": "hello"},
        ):
            mock_client = MagicMock()
            mock_client.chat.side_effect = [tool_response, text_response]
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task())

        assert result.success is True
        assert result.content == "Analysed."
        assert mock_client.chat.call_count == 2
        assert result.input_tokens == 30
        assert result.tool_calls == 1

    def test_iteration_limit_stops_the_loop(self):
        looping_response = {
            "content": [
                {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"file_path": "a.py"}}
            ],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }

        with patch("radsim.sub_agent.create_client") as mock_create_client, patch(
            "radsim.sub_agent_policy.SubAgentPolicyBroker._run",
            return_value={"success": True},
        ):
            mock_client = MagicMock()
            mock_client.chat.return_value = looping_response
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task(max_iterations=3))

        assert result.success is True
        assert "iteration limit" in result.content
        assert mock_client.chat.call_count == 3

    def test_denied_tool_is_reported_without_running(self):
        """A tool outside the profile comes back as a blocked result, not an escape."""
        tool_response = {
            "content": [
                {"type": "tool_use", "id": "t1", "name": "write_file", "input": {"file_path": "a.py"}}
            ],
            "usage": {},
        }
        text_response = {"content": [{"type": "text", "text": "Blocked."}], "usage": {}}

        with patch("radsim.sub_agent.create_client") as mock_create_client, patch(
            "radsim.sub_agent_policy.SubAgentPolicyBroker._run"
        ) as mock_run:
            mock_client = MagicMock()
            mock_client.chat.side_effect = [tool_response, text_response]
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task(profile="explore"))

        mock_run.assert_not_called()
        assert "write_file" in result.denied_tools
        assert result.tool_calls == 0


class TestCancellation(unittest.TestCase):
    """Cancellation stops work, not only the reported status."""

    def setUp(self):
        self.key_patcher = patch("radsim.config.get_provider_api_key", return_value="test-key")
        self.key_patcher.start()
        self.addCleanup(self.key_patcher.stop)

    def test_cancel_before_start_makes_no_api_call(self):
        cancel_event = threading.Event()
        cancel_event.set()

        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task(cancel_event=cancel_event))

        mock_client.chat.assert_not_called()
        assert result.cancelled is True
        assert result.success is False

    def test_cancel_between_iterations_stops_further_calls(self):
        cancel_event = threading.Event()
        tool_response = {
            "content": [
                {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"file_path": "a.py"}}
            ],
            "usage": {},
        }

        def cancel_then_respond(*_args, **_kwargs):
            cancel_event.set()
            return tool_response

        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.side_effect = cancel_then_respond
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task(cancel_event=cancel_event, max_iterations=5))

        assert mock_client.chat.call_count == 1
        assert result.cancelled is True

    def test_cancelled_task_runs_no_tools(self):
        cancel_event = threading.Event()
        cancel_event.set()

        from radsim.sub_agent_policy import SubAgentPolicyBroker

        broker = SubAgentPolicyBroker("explore", cancel_event=cancel_event)
        allowed, reason = broker.check("read_file", {"file_path": "a.py"})

        assert allowed is False
        assert "cancelled" in reason

    def test_expired_deadline_stops_the_loop(self):
        """A task that outruns its wall clock stops instead of looping on."""
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task(timeout_seconds=-1))

        mock_client.chat.assert_not_called()
        assert result.success is False
        assert "time limit" in result.error

    def test_partial_output_is_preserved_when_stopped(self):
        cancel_event = threading.Event()
        partial = {
            "content": [
                {"type": "text", "text": "found so far"},
                {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"file_path": "a.py"}},
            ],
            "usage": {},
        }

        def cancel_then_respond(*_args, **_kwargs):
            cancel_event.set()
            return partial

        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.side_effect = cancel_then_respond
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task(cancel_event=cancel_event))

        assert result.cancelled is True
        assert "found so far" in result.content


class TestStreamingRunner(unittest.TestCase):
    """The streaming path shares the runner's guarantees."""

    def setUp(self):
        self.key_patcher = patch("radsim.config.get_provider_api_key", return_value="test-key")
        self.key_patcher.start()
        self.addCleanup(self.key_patcher.stop)

    def _drain(self, generator):
        chunks = []
        try:
            while True:
                chunks.append(next(generator))
        except StopIteration as stop:
            return chunks, stop.value

    def test_streams_text_and_returns_result(self):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.stream_chat.return_value = iter(
                [
                    {"type": "text_delta", "text": "Hello"},
                    {
                        "type": "final_response",
                        "response": {"content": [{"type": "text", "text": "Hello"}], "usage": {}},
                    },
                ]
            )
            mock_create_client.return_value = mock_client
            chunks, result = self._drain(stream_subagent_task(_task()))

        assert chunks == [{"type": "text_delta", "text": "Hello"}]
        assert result.success is True
        assert result.content == "Hello"

    def test_unknown_profile_fails_before_streaming(self):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            _chunks, result = self._drain(stream_subagent_task(_task(profile="nope")))
        mock_create_client.assert_not_called()
        assert result.success is False


class TestBackgroundProfileGuard(unittest.TestCase):
    """Profiles that mutate or execute code cannot run in the background."""

    def test_implement_cannot_run_in_background(self):
        result = execute_subagent_task(_task(profile="implement", background=True))
        assert result.success is False
        assert "cannot run in the background" in result.error

    def test_verify_cannot_run_in_background(self):
        result = execute_subagent_task(_task(profile="verify", background=True))
        assert result.success is False

    def test_explore_can_run_in_background(self):
        with patch("radsim.config.get_provider_api_key", return_value="key"), patch(
            "radsim.sub_agent.create_client"
        ) as mock_create_client:
            mock_client = MagicMock()
            mock_client.chat.return_value = {"content": [{"type": "text", "text": "ok"}], "usage": {}}
            mock_create_client.return_value = mock_client
            result = execute_subagent_task(_task(profile="explore", background=True))
        assert result.success is True


class TestDelegateTaskEntryPoint(unittest.TestCase):
    """The developer entry point requires an explicit provider and model."""

    def test_delegate_requires_provider_and_model(self):
        with pytest.raises(TypeError):
            delegate_task("do something")

    def test_delegate_builds_the_expected_task(self):
        with patch("radsim.sub_agent.execute_subagent_task") as mock_execute:
            mock_execute.return_value = SubAgentResult(
                success=True, content="Done", model_used=VALID_MODEL, provider_used=VALID_PROVIDER
            )
            delegate_task(
                "Do something",
                provider=VALID_PROVIDER,
                model=VALID_MODEL,
                profile="review",
                custom_instructions="Focus on auth.",
            )

        task = mock_execute.call_args[0][0]
        assert task.task_description == "Do something"
        assert task.provider == VALID_PROVIDER
        assert task.model == VALID_MODEL
        assert task.profile == "review"
        assert task.custom_instructions == "Focus on auth."


class TestSubAgentResultShape(unittest.TestCase):
    """The result carries the evidence the primary agent needs."""

    def test_defaults(self):
        result = SubAgentResult(
            success=True, content="test", model_used=VALID_MODEL, provider_used=VALID_PROVIDER
        )
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.tool_calls == 0
        assert result.denied_tools == []
        assert result.cancelled is False
        assert result.error == ""

    def test_task_defaults_to_least_privileged_profile(self):
        task = SubAgentTask(task_description="t", provider=VALID_PROVIDER, model=VALID_MODEL)
        assert task.profile == "explore"
        assert task.background is False
        assert task.custom_instructions == ""


if __name__ == "__main__":
    unittest.main()
