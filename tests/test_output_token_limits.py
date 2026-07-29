"""Tests for per-request output token ceilings.

A capability profile declares how much output its subagent may produce. These
tests cover the whole path: the profile record, the runner that reads it, the
three provider clients that send it, and the notice shown when a response is
cut off at the ceiling.

The primary agent asks for no ceiling, so its requests must be unchanged.
"""

import unittest
from unittest.mock import MagicMock, patch

from radsim.api_client import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    ClaudeClient,
    OpenAIClient,
    OpenRouterClient,
)
from radsim.sub_agent import SubAgentTask, execute_subagent_task, stream_subagent_task
from radsim.sub_agent_profiles import get_profile

VALID_PROVIDER = "openrouter"
VALID_MODEL = "moonshotai/kimi-k2.5"


def _task(**overrides):
    """Build a task against a valid saved selection unless overridden."""
    fields = {
        "task_description": "Summarise auth.py",
        "provider": VALID_PROVIDER,
        "model": VALID_MODEL,
        "profile": "explore",
    }
    fields.update(overrides)
    return SubAgentTask(**fields)


def _client_returning(response):
    """Build a mocked client whose chat() returns one fixed response."""
    client = MagicMock()
    client.chat.return_value = response
    return client


class TestClaudeRequestCeiling(unittest.TestCase):
    """Anthropic requires the field, so a default is always sent."""

    def _kwargs(self, **overrides):
        client = ClaudeClient.__new__(ClaudeClient)
        client.model = "claude-haiku-4-5"
        return client._build_request_kwargs([{"role": "user", "content": "hi"}], **overrides)

    def test_no_ceiling_keeps_the_historic_default(self):
        assert self._kwargs()["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS

    def test_supplied_ceiling_is_sent(self):
        assert self._kwargs(max_tokens=2048)["max_tokens"] == 2048

    def test_zero_falls_back_to_the_default(self):
        assert self._kwargs(max_tokens=0)["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS


class TestOpenAIRequestCeiling(unittest.TestCase):
    """OpenAI-compatible clients send nothing unless a ceiling is asked for."""

    def _kwargs(self, client_class, **overrides):
        client = client_class.__new__(client_class)
        client.model = "gpt-5.2"
        client.reasoning_effort = None
        return client._build_request_kwargs([{"role": "user", "content": "hi"}], **overrides)

    def test_no_ceiling_sends_no_limit_field(self):
        kwargs = self._kwargs(OpenAIClient)
        assert "max_tokens" not in kwargs
        assert "max_completion_tokens" not in kwargs

    def test_openai_uses_max_completion_tokens(self):
        kwargs = self._kwargs(OpenAIClient, max_tokens=3072)
        assert kwargs["max_completion_tokens"] == 3072
        assert "max_tokens" not in kwargs

    def test_openrouter_uses_max_tokens(self):
        kwargs = self._kwargs(OpenRouterClient, max_tokens=3072)
        assert kwargs["max_tokens"] == 3072
        assert "max_completion_tokens" not in kwargs


class TestProfileCeilingReachesTheProvider(unittest.TestCase):
    """The declared profile ceiling is the one the request carries."""

    def setUp(self):
        self.key_patcher = patch("radsim.config.get_provider_api_key", return_value="test-key")
        self.key_patcher.start()
        self.addCleanup(self.key_patcher.stop)

    def _run(self, task):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            client = _client_returning({"content": [], "usage": {}})
            mock_create_client.return_value = client
            execute_subagent_task(task)
        return client

    def test_explore_sends_its_own_ceiling(self):
        client = self._run(_task(profile="explore"))
        assert client.chat.call_args[1]["max_tokens"] == get_profile("explore")["max_tokens"]

    def test_implement_sends_a_larger_ceiling(self):
        client = self._run(_task(profile="implement"))
        assert client.chat.call_args[1]["max_tokens"] == get_profile("implement")["max_tokens"]
        assert get_profile("implement")["max_tokens"] > get_profile("explore")["max_tokens"]

    def test_task_override_wins_over_the_profile(self):
        client = self._run(_task(profile="explore", max_tokens=512))
        assert client.chat.call_args[1]["max_tokens"] == 512

    def test_streaming_path_sends_the_ceiling_too(self):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            client = MagicMock()
            client.stream_chat.return_value = iter(
                [{"type": "final_response", "response": {"content": [], "usage": {}}}]
            )
            mock_create_client.return_value = client
            generator = stream_subagent_task(_task(profile="review"))
            for _chunk in generator:
                pass

        assert client.stream_chat.call_args[1]["max_tokens"] == get_profile("review")["max_tokens"]


class TestTruncationIsReported(unittest.TestCase):
    """A response cut off at the ceiling never reads as a finished answer."""

    def setUp(self):
        self.key_patcher = patch("radsim.config.get_provider_api_key", return_value="test-key")
        self.key_patcher.start()
        self.addCleanup(self.key_patcher.stop)

    def _result_for(self, stop_reason):
        with patch("radsim.sub_agent.create_client") as mock_create_client:
            mock_create_client.return_value = _client_returning(
                {
                    "content": [{"type": "text", "text": "Half an answ"}],
                    "stop_reason": stop_reason,
                    "usage": {},
                }
            )
            return execute_subagent_task(_task())

    def test_anthropic_truncation_is_flagged(self):
        result = self._result_for("max_tokens")
        assert "incomplete" in result.content
        assert "ceiling" in result.content

    def test_openai_truncation_is_flagged(self):
        assert "incomplete" in self._result_for("length").content

    def test_normal_completion_carries_no_notice(self):
        assert self._result_for("end_turn").content == "Half an answ"


class TestStreamingFinishReasonSurvives(unittest.TestCase):
    """The streamed finish reason is reported, not hardcoded to 'stop'."""

    def _stream_response(self, finish_reason):
        client = OpenAIClient.__new__(OpenAIClient)
        client.model = "gpt-5.2"
        client.reasoning_effort = None
        chunk = MagicMock()
        chunk.usage = None
        choice = MagicMock()
        choice.finish_reason = finish_reason
        choice.delta.content = "partial"
        choice.delta.tool_calls = None
        chunk.choices = [choice]
        client.client = MagicMock()
        client.client.chat.completions.create.return_value = iter([chunk])

        final = None
        for event in client.stream_chat([{"role": "user", "content": "hi"}]):
            if event["type"] == "final_response":
                final = event["response"]
        return final

    def test_length_finish_reason_is_reported(self):
        assert self._stream_response("length")["stop_reason"] == "length"

    def test_normal_finish_reason_is_reported(self):
        assert self._stream_response("stop")["stop_reason"] == "stop"


if __name__ == "__main__":
    unittest.main()
