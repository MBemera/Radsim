"""Integration tests for the agentic harness.

Drives the real RadSimAgent loop (_call_api → _handle_response →
_process_tool_calls iteration) with a scripted fake client — no network.
Verifies multi-turn conversations, tool round-trips, message-history
integrity, rejection handling, streaming, crash resilience, and loop
protection.
"""

import json
import sys
from pathlib import Path

import pytest

from radsim.config import Config
from radsim.rate_limiter import RateLimitExceeded


def make_response(*blocks, stop_reason="end_turn"):
    return {
        "content": list(blocks),
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def text_block(text):
    return {"type": "text", "text": text}


def tool_block(tool_id, name, tool_input):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


class FakeClient:
    """Scripted API client: returns queued responses, records history."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.interrupt_agent = None  # Set to simulate Esc mid-stream

    def chat(self, messages, system_prompt=None, tools=None):
        self.calls.append([dict(m) for m in messages])
        if not self.responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        return self.responses.pop(0)

    def stream_chat(self, messages, system_prompt=None, tools=None):
        response = self.chat(messages, system_prompt, tools)
        for block in response["content"]:
            if block["type"] == "text" and block["text"]:
                yield {"type": "text_delta", "text": block["text"]}
                if self.interrupt_agent is not None:
                    self.interrupt_agent._interrupted.set()
                    return
        yield {"type": "final_response", "response": response}


@pytest.fixture
def agent_factory(tmp_path, monkeypatch):
    """Build a hermetic agent with a scripted client."""
    import radsim.memory

    monkeypatch.setattr(radsim.memory, "CONFIG_DIR", tmp_path / "confdir")
    monkeypatch.chdir(tmp_path)

    # Keep learning/config side effects out of the loop under test
    class StubAgentConfig:
        def is_learning_module_enabled(self, name):
            return False

        def get(self, key, default=None):
            return default

        def is_tool_enabled(self, name):
            return True

    monkeypatch.setattr(
        "radsim.agent_config.get_agent_config_manager", lambda: StubAgentConfig()
    )
    monkeypatch.setattr("radsim.agent_api.track_tool_execution", lambda **kw: None)
    monkeypatch.setattr("radsim.agent_api.record_error", lambda **kw: None)
    monkeypatch.setattr(
        "radsim.learning.check_similar_error",
        lambda *a, **kw: {"error_found": False},
    )

    def build(responses, stream=False, auto_confirm=True, max_calls=8):
        from radsim.agent import RadSimAgent

        config = Config(
            provider="claude",
            api_key="test-key",
            model="test-model",
            auto_confirm=auto_confirm,
            stream=stream,
            max_api_calls_per_turn=max_calls,
            rate_limit_cooldown_ms=0,
        )
        agent = RadSimAgent(config)
        agent.client = FakeClient(responses)
        return agent

    return build


class TestSingleTurn:
    def test_text_only_response(self, agent_factory):
        agent = agent_factory([make_response(text_block("Hello Matt"))])

        result = agent.process_message("hi")

        assert result == "Hello Matt"
        assert [m["role"] for m in agent.messages] == ["user", "assistant"]

    def test_streaming_response(self, agent_factory):
        agent = agent_factory(
            [make_response(text_block("streamed answer"))], stream=True
        )

        result = agent.process_message("hi")

        assert result == "streamed answer"

    def test_interrupted_stream_returns_string(self, agent_factory):
        agent = agent_factory(
            [make_response(text_block("partial output"))], stream=True
        )
        agent.client.interrupt_agent = agent

        result = agent.process_message("hi")

        assert isinstance(result, str)


class TestToolRoundTrip:
    def test_tool_use_then_final_answer(self, agent_factory, tmp_path):
        target = tmp_path / "data.txt"
        target.write_text("file body\n")

        agent = agent_factory([
            make_response(
                text_block("Reading the file."),
                tool_block("tool_1", "read_file", {"file_path": str(target)}),
                stop_reason="tool_use",
            ),
            make_response(text_block("The file says: file body")),
        ])

        result = agent.process_message("what does data.txt say?")

        assert result == "The file says: file body"
        # Two API calls: initial + follow-up with tool results
        assert len(agent.client.calls) == 2

        # History integrity: assistant tool_use followed by user tool_result
        roles = [m["role"] for m in agent.messages]
        assert roles == ["user", "assistant", "user", "assistant"]
        tool_result = agent.messages[2]["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_use_id"] == "tool_1"
        payload = json.loads(tool_result["content"])
        assert payload["success"] is True
        assert "file body" in payload["content"]

    def test_multiple_tools_in_one_response(self, agent_factory, tmp_path):
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("alpha")
        file_b.write_text("beta")

        agent = agent_factory([
            make_response(
                tool_block("tool_a", "read_file", {"file_path": str(file_a)}),
                tool_block("tool_b", "read_file", {"file_path": str(file_b)}),
                stop_reason="tool_use",
            ),
            make_response(text_block("both read")),
        ])

        result = agent.process_message("read both")

        assert result == "both read"
        results_message = agent.messages[2]["content"]
        assert [r["tool_use_id"] for r in results_message] == ["tool_a", "tool_b"]

    def test_tool_error_flows_back_to_model(self, agent_factory, tmp_path):
        agent = agent_factory([
            make_response(
                tool_block(
                    "tool_1", "read_file", {"file_path": str(tmp_path / "nope.txt")}
                ),
                stop_reason="tool_use",
            ),
            make_response(text_block("that file does not exist")),
        ])

        result = agent.process_message("read missing file")

        assert result == "that file does not exist"
        payload = json.loads(agent.messages[2]["content"][0]["content"])
        assert payload["success"] is False

    def test_corrupted_tool_input_reported_not_crashed(self, agent_factory):
        agent = agent_factory([
            make_response(
                tool_block(
                    "tool_1",
                    "read_file",
                    {"__parse_error__": "bad json", "__raw__": "{oops"},
                ),
                stop_reason="tool_use",
            ),
            make_response(text_block("recovered")),
        ])

        result = agent.process_message("go")

        assert result == "recovered"
        payload = json.loads(agent.messages[2]["content"][0]["content"])
        assert payload["success"] is False
        assert "corrupted" in payload["error"].lower()


class TestMultiTurn:
    def test_three_turn_conversation_history(self, agent_factory):
        agent = agent_factory([
            make_response(text_block("answer one")),
            make_response(text_block("answer two")),
            make_response(text_block("answer three")),
        ])

        assert agent.process_message("first") == "answer one"
        assert agent.process_message("second") == "answer two"
        assert agent.process_message("third") == "answer three"

        roles = [m["role"] for m in agent.messages]
        assert roles == ["user", "assistant"] * 3
        # The final API call saw the full history
        assert len(agent.client.calls[2]) == 5

    def test_rate_limiter_resets_between_turns(self, agent_factory):
        agent = agent_factory([
            make_response(text_block("one")),
            make_response(text_block("two")),
        ])

        agent.process_message("first")
        first_turn_calls = agent.protection.rate_limiter._calls_this_turn
        agent.process_message("second")

        assert agent.protection.rate_limiter._calls_this_turn == first_turn_calls == 1

    def test_multi_step_task_with_tools_across_turns(self, agent_factory, tmp_path):
        """A realistic multi-turn task: write a file in turn 1, read it in turn 2."""
        target = tmp_path / "multi.txt"

        agent = agent_factory([
            make_response(
                tool_block(
                    "tool_w",
                    "write_file",
                    {"file_path": str(target), "content": "step one done\n"},
                ),
                stop_reason="tool_use",
            ),
            make_response(text_block("written")),
            make_response(
                tool_block("tool_r", "read_file", {"file_path": str(target)}),
                stop_reason="tool_use",
            ),
            make_response(text_block("confirmed: step one done")),
        ])

        assert agent.process_message("write the file") == "written"
        assert target.read_text() == "step one done\n"
        assert agent.process_message("now read it back") == "confirmed: step one done"

        # Full history remains API-valid: every tool_use has a tool_result
        tool_use_ids = []
        tool_result_ids = []
        for message in agent.messages:
            if isinstance(message.get("content"), list):
                for block in message["content"]:
                    if block.get("type") == "tool_use":
                        tool_use_ids.append(block["id"])
                    elif block.get("type") == "tool_result":
                        tool_result_ids.append(block["tool_use_id"])
        assert tool_use_ids == tool_result_ids == ["tool_w", "tool_r"]


class TestHarnessResilience:
    def test_crashing_tool_returns_error_result_not_exception(
        self, agent_factory, tmp_path, monkeypatch
    ):
        """A tool handler crash must become an error tool_result, not abort the turn."""

        def explode(tool_name, tool_input):
            raise RuntimeError("disk exploded")

        monkeypatch.setattr("radsim.agent_policy.execute_tool", explode)

        agent = agent_factory([
            make_response(
                tool_block(
                    "tool_1", "read_file", {"file_path": str(tmp_path / "any.txt")}
                ),
                stop_reason="tool_use",
            ),
            make_response(text_block("recovered from crash")),
        ])

        result = agent.process_message("read it")

        assert result == "recovered from crash"
        payload = json.loads(agent.messages[2]["content"][0]["content"])
        assert payload["success"] is False
        assert "disk exploded" in payload["error"]

    def test_non_json_tool_result_is_serialized_not_crashed(
        self, agent_factory, tmp_path, monkeypatch
    ):
        """Tool results with non-JSON types (Path, bytes) must still serialize."""
        monkeypatch.setattr(
            "radsim.agent_policy.execute_tool",
            lambda tool_name, tool_input: {
                "success": True,
                "content": Path(tmp_path / "weird.txt"),
            },
        )

        agent = agent_factory([
            make_response(
                tool_block(
                    "tool_1", "read_file", {"file_path": str(tmp_path / "weird.txt")}
                ),
                stop_reason="tool_use",
            ),
            make_response(text_block("handled odd payload")),
        ])

        result = agent.process_message("go")

        assert result == "handled odd payload"
        payload = json.loads(agent.messages[2]["content"][0]["content"])
        assert payload["success"] is True
        assert "weird.txt" in payload["content"]

    def test_long_tool_chain_runs_at_constant_stack_depth(
        self, agent_factory, tmp_path
    ):
        """200 tool rounds must not deepen the stack (loop, not recursion)."""
        target = tmp_path / "chain.txt"
        target.write_text("x")

        rounds = 200
        responses = [
            make_response(
                tool_block(f"tool_{i}", "read_file", {"file_path": str(target)}),
                stop_reason="tool_use",
            )
            for i in range(rounds)
        ]
        responses.append(make_response(text_block("chain done")))
        agent = agent_factory(responses, max_calls=rounds + 5)

        import inspect

        original_limit = sys.getrecursionlimit()
        current_depth = len(inspect.stack())
        sys.setrecursionlimit(current_depth + 150)
        try:
            assert agent.process_message("chain") == "chain done"
        finally:
            sys.setrecursionlimit(original_limit)


class TestLoopProtection:
    def test_runaway_tool_loop_hits_hard_stop(self, agent_factory, tmp_path):
        target = tmp_path / "loop.txt"
        target.write_text("x")

        looping = [
            make_response(
                tool_block(f"tool_{i}", "read_file", {"file_path": str(target)}),
                stop_reason="tool_use",
            )
            for i in range(10)
        ]
        agent = agent_factory(looping, max_calls=3)

        with pytest.raises(RateLimitExceeded):
            agent.process_message("loop forever")

        # The limiter stopped it at the configured ceiling
        assert len(agent.client.calls) < 4

    def test_user_rejection_stops_turn_without_followup(
        self, agent_factory, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("radsim.agent.confirm_write", lambda *a, **kw: False)

        agent = agent_factory(
            [
                make_response(
                    text_block("Writing the file now."),
                    tool_block(
                        "tool_1",
                        "write_file",
                        {
                            "file_path": str(tmp_path / "rejected.py"),
                            "content": "import os\n\nprint(os.name)\n",
                        },
                    ),
                    stop_reason="tool_use",
                )
            ],
            auto_confirm=False,
        )

        result = agent.process_message("write something")

        # Turn stops: exactly one API call, no follow-up
        assert len(agent.client.calls) == 1
        assert isinstance(result, str)
        assert not (tmp_path / "rejected.py").exists()
        # The rejection was recorded in the tool_result for the model
        payload = json.loads(agent.messages[2]["content"][0]["content"])
        assert payload["success"] is False
        assert "STOPPED" in payload["error"]
