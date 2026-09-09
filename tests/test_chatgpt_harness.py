"""Exercise the subscription SDK through RadSim's real tool and approval loop."""

import json

import httpx
import openai
import pytest

from radsim.agent import RadSimAgent
from radsim.chatgpt_client import ChatGPTClient
from radsim.codex_transport import CodexError
from radsim.config import Config


def stream_response(output):
    response = {
        "type": "response.completed",
        "response": {
            "id": "resp-test",
            "status": "completed",
            "output": [],
            "usage": {"input_tokens": 12, "output_tokens": 5},
        },
    }
    delta = {"type": "response.output_text.delta", "delta": "fixture verified"}
    items = [
        {"type": "response.output_item.done", "output_index": index, "item": item}
        for index, item in enumerate(output)
    ]
    events = ([delta] if output[0]["type"] == "message" else []) + items + [response]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)


@pytest.fixture
def subscription_agent(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "radsim.chatgpt_tokens.load_subscription_credentials",
        lambda: ("synthetic-access", "synthetic-account"),
    )
    real_openai = openai.OpenAI

    def build(outputs, stream=True):
        requests = []

        def handle(request):
            assert str(request.url) == "https://chatgpt.com/backend-api/codex/responses"
            requests.append(json.loads(request.content))
            return stream_response(outputs.pop(0))

        def create(**kwargs):
            return real_openai(
                **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
            )

        monkeypatch.setattr(openai, "OpenAI", create)
        agent = RadSimAgent(
            Config(
                provider="chatgpt",
                api_key=None,
                model="gpt-6-astra",
                stream=stream,
                auto_confirm=False,
                rate_limit_cooldown_ms=0,
            )
        )
        assert isinstance(agent.client, ChatGPTClient)
        return agent, requests

    return build


def tool_call(name, arguments):
    return [
        {
            "type": "function_call",
            "name": name,
            "call_id": "call-fixture",
            "arguments": json.dumps(arguments),
        }
    ]


@pytest.mark.parametrize("stream", [True, False])
def test_subscription_reads_file_in_radsim_loop(subscription_agent, tmp_path, stream):
    (tmp_path / "fixture.txt").write_text("synthetic fixture contents")
    final = [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "fixture verified"}],
        }
    ]
    agent, requests = subscription_agent(
        [tool_call("read_file", {"file_path": "fixture.txt"}), final], stream=stream
    )

    assert agent.process_message("Read fixture.txt") == "fixture verified"
    assert len(requests) == 2
    assert "read_file" in {tool["name"] for tool in requests[0]["tools"]}
    result = next(item for item in requests[1]["input"] if item["type"] == "function_call_output")
    assert result["call_id"] == "call-fixture"
    assert "synthetic fixture contents" in result["output"]
    assert agent.usage_stats["request_count"] == 2
    assert [message["role"] for message in agent.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_subscription_write_still_needs_radsim_approval(
    subscription_agent,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("radsim.agent_tool_handlers.confirm_write", lambda *a, **kw: False)
    agent, requests = subscription_agent(
        [tool_call("write_file", {"file_path": "denied.txt", "content": "synthetic"})]
    )

    agent.process_message("Write denied.txt")

    assert not (tmp_path / "denied.txt").exists()
    assert len(requests) == 1
    result = json.loads(agent.messages[2]["content"][0]["content"])
    assert result["success"] is False
    assert "STOPPED" in result["error"]


def test_failed_switch_preserves_client_and_configuration(subscription_agent, monkeypatch):
    agent, _ = subscription_agent([])
    old_client = agent.client
    old_config = vars(agent.config).copy()

    def fail(*args, **kwargs):
        raise CodexError("ChatGPT sign-in is required")

    monkeypatch.setattr("radsim.agent_conversation.create_client", fail)
    with pytest.raises(CodexError):
        agent.update_config("chatgpt", None, "different-model")
    assert agent.client is old_client
    assert vars(agent.config) == old_config
