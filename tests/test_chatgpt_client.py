"""The ChatGPT subscription provider inside RadSim's own agent loop."""

import json
import time
from types import SimpleNamespace

import pytest

from radsim import chatgpt_client, chatgpt_tokens
from radsim.codex_transport import CodexError


def make_jwt(expiry: float) -> str:
    import base64

    payload = base64.urlsafe_b64encode(json.dumps({"exp": expiry}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def write_store(path, access_token="access-marker", account_id="acct-marker"):
    path.write_text(
        json.dumps({"tokens": {"access_token": access_token, "account_id": account_id}})
    )


def test_missing_or_broken_sign_in_fails_closed(monkeypatch, tmp_path):
    store = tmp_path / "auth.json"
    monkeypatch.setattr(chatgpt_tokens, "auth_file", lambda: store)
    with pytest.raises(CodexError, match="radsim login chatgpt"):
        chatgpt_tokens.read_tokens()

    store.write_text("{not json")
    with pytest.raises(CodexError, match="radsim login chatgpt"):
        chatgpt_tokens.read_tokens()


def test_expiring_token_is_refreshed_through_codex(monkeypatch, tmp_path):
    """RadSim never refreshes tokens itself; Codex owns the credential."""
    store = tmp_path / "auth.json"
    write_store(store, access_token=make_jwt(time.time() + 60))
    monkeypatch.setattr(chatgpt_tokens, "auth_file", lambda: store)
    refreshed = []

    def refresh():
        refreshed.append(True)
        write_store(store, access_token=make_jwt(time.time() + 3600))

    monkeypatch.setattr(chatgpt_tokens, "refresh_through_codex", refresh)
    access_token, account_id = chatgpt_tokens.load_subscription_credentials()

    assert refreshed == [True]
    assert account_id == "acct-marker"
    assert chatgpt_tokens.token_expiry(access_token) > time.time()


def test_valid_token_is_used_without_starting_codex(monkeypatch, tmp_path):
    store = tmp_path / "auth.json"
    write_store(store, access_token=make_jwt(time.time() + 3600))
    monkeypatch.setattr(chatgpt_tokens, "auth_file", lambda: store)
    monkeypatch.setattr(
        chatgpt_tokens, "refresh_through_codex", lambda: pytest.fail("must not refresh")
    )

    access_token, _ = chatgpt_tokens.load_subscription_credentials()
    assert chatgpt_tokens.token_expiry(access_token) > time.time()


class FakeResponses:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.result


class FakeOpenAI:
    last = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.responses = FakeResponses(FakeOpenAI.next_result)
        FakeOpenAI.last = self


def build_client(monkeypatch, result):
    import openai

    FakeOpenAI.next_result = result
    monkeypatch.setattr(
        chatgpt_client,
        "load_subscription_credentials",
        lambda: ("access-marker", "acct-marker"),
        raising=False,
    )
    monkeypatch.setattr(
        chatgpt_tokens, "load_subscription_credentials", lambda: ("access-marker", "acct-marker")
    )
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    return chatgpt_client.ChatGPTClient(model="gpt-6-astra")


def completed_response(output, usage=None):
    return SimpleNamespace(
        output=output,
        usage=usage,
        incomplete_details=None,
        model="gpt-6-astra",
    )


def test_session_uses_the_subscription_endpoint_and_account(monkeypatch):
    client = build_client(monkeypatch, [])
    kwargs = FakeOpenAI.last.kwargs

    assert kwargs["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert kwargs["api_key"] == "access-marker"
    assert kwargs["default_headers"]["chatgpt-account-id"] == "acct-marker"
    assert kwargs["default_headers"]["originator"] == chatgpt_client.CODEX_ORIGINATOR
    assert client.model == "gpt-6-astra"
    assert kwargs["max_retries"] == 0


def stream_of(response):
    return [SimpleNamespace(type="response.completed", response=response)]


def test_request_carries_prompt_tools_and_never_stores(monkeypatch):
    client = build_client(monkeypatch, stream_of(completed_response([])))
    tools = [
        {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]
    client.chat([{"role": "user", "content": "hello"}], system_prompt="be brief", tools=tools)

    request = FakeOpenAI.last.responses.requests[0]
    assert request["instructions"] == "be brief"
    assert request["store"] is False
    # The subscription endpoint answers streamed requests only.
    assert request["stream"] is True
    assert request["input"] == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]}
    ]
    assert request["tools"][0] == {
        "type": "function",
        "name": "read_file",
        "description": "Read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    }


def test_tool_calls_and_results_round_trip():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "list files"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "checking"},
                {"type": "tool_use", "id": "call-1", "name": "list_files", "input": {"path": "."}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "a.py"}],
        },
    ]

    items = chatgpt_client.build_input_items(messages)

    assert items[1] == {
        "type": "function_call",
        "call_id": "call-1",
        "name": "list_files",
        "arguments": json.dumps({"path": "."}),
    }
    assert items[2]["content"] == [{"type": "output_text", "text": "checking"}]
    assert items[3] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "a.py",
    }


def test_response_becomes_radsim_text_and_tool_blocks(monkeypatch):
    output = [
        SimpleNamespace(type="reasoning", summary=[]),
        SimpleNamespace(
            type="message",
            content=[SimpleNamespace(type="output_text", text="done")],
        ),
        SimpleNamespace(
            type="function_call",
            name="read_file",
            call_id="call-9",
            arguments='{"path": "README.md"}',
        ),
    ]
    usage = SimpleNamespace(
        input_tokens=12,
        output_tokens=5,
        input_tokens_details=SimpleNamespace(cached_tokens=4),
        output_tokens_details=SimpleNamespace(reasoning_tokens=3),
    )

    parsed = chatgpt_client.parse_response(completed_response(output, usage))

    assert parsed["content"][0] == {"type": "text", "text": "done"}
    assert parsed["content"][1] == {
        "type": "tool_use",
        "id": "call-9",
        "name": "read_file",
        "input": {"path": "README.md"},
    }
    assert parsed["stop_reason"] == "tool_calls"
    assert parsed["usage"]["input_tokens"] == 12
    assert parsed["usage"]["output_tokens"] == 5
    assert parsed["usage"]["cache_read_input_tokens"] == 4
    assert parsed["usage"]["reasoning_output_tokens"] == 3


def test_output_ceiling_is_not_sent_to_the_subscription_endpoint(monkeypatch):
    """The endpoint rejects max_output_tokens outright, so the turn must omit it."""
    client = build_client(monkeypatch, stream_of(completed_response([])))

    client.chat([{"role": "user", "content": "hello"}], max_tokens=4000)

    assert "max_output_tokens" not in FakeOpenAI.last.responses.requests[0]


def test_truncated_response_is_reported_as_length():
    response = SimpleNamespace(
        output=[],
        usage=None,
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
    )
    assert chatgpt_client.parse_response(response)["stop_reason"] == "length"


def test_streaming_yields_deltas_then_the_final_response(monkeypatch):
    events = [
        SimpleNamespace(type="response.output_text.delta", delta="hel"),
        SimpleNamespace(type="response.output_text.delta", delta="lo"),
        SimpleNamespace(
            type="response.completed",
            response=completed_response(
                [
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", text="hello")],
                    )
                ]
            ),
        ),
    ]
    client = build_client(monkeypatch, events)

    yielded = list(client.stream_chat([{"role": "user", "content": "hi"}]))

    assert [item["text"] for item in yielded if item["type"] == "text_delta"] == ["hel", "lo"]
    final = yielded[-1]
    assert final["type"] == "final_response"
    assert final["response"]["content"] == [{"type": "text", "text": "hello"}]
    assert FakeOpenAI.last.responses.requests[0]["stream"] is True


def test_stream_without_completion_fails_closed(monkeypatch):
    client = build_client(monkeypatch, [SimpleNamespace(type="response.created")])
    with pytest.raises(CodexError, match="ended the response early"):
        list(client.stream_chat([{"role": "user", "content": "hi"}]))


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "radsim login chatgpt"),
        (403, "radsim login chatgpt"),
        (429, "usage limit"),
        (400, "rejected this request"),
        (None, "could not complete"),
    ],
)
def test_backend_failures_are_explained_without_echoing_the_request(status, expected):
    error = RuntimeError("secret-request-body")
    error.status_code = status
    message = chatgpt_client.describe_http_failure(error)
    assert expected in message
    assert "secret-request-body" not in message


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"type": "usage_limit_reached", "resets_in_seconds": 6484}},
        {"type": "usage_limit_reached", "resets_in_seconds": 6484},
    ],
)
def test_quota_message_says_when_it_resets(body):
    """The SDK reports either the whole payload or just its error object."""
    error = RuntimeError("limit")
    error.status_code = 429
    error.body = body

    message = chatgpt_client.describe_http_failure(error)

    assert "1h 48m" in message
    assert "never used as a fallback" in message


def test_chat_failure_is_reported_as_a_codex_error(monkeypatch):
    client = build_client(monkeypatch, [])

    def fail(**_):
        error = RuntimeError("backend detail")
        error.status_code = 429
        raise error

    monkeypatch.setattr(client.client.responses, "create", fail)
    with pytest.raises(CodexError, match="usage limit"):
        client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.parametrize("kind", ["response.failed", "response.incomplete", "error"])
def test_failed_stream_never_returns_tool_calls(monkeypatch, kind):
    response = completed_response(
        [
            SimpleNamespace(
                type="function_call",
                name="write_file",
                call_id="call-1",
                arguments='{"file_path":"unapproved.txt","content":"data"}',
            )
        ]
    )
    client = build_client(monkeypatch, [SimpleNamespace(type=kind, response=response)])
    with pytest.raises(CodexError):
        client.chat([{"role": "user", "content": "hi"}])


def test_stream_is_closed_on_interrupt(monkeypatch):
    closed = []

    def events():
        try:
            yield SimpleNamespace(type="response.output_text.delta", delta="hello")
            yield from stream_of(completed_response([]))
        finally:
            closed.append(True)

    client = build_client(monkeypatch, events())
    stream = client.stream_chat([{"role": "user", "content": "hi"}])
    next(stream)
    stream.close()
    assert closed == [True]


def test_running_client_reloads_credentials_before_each_request(monkeypatch):
    client = build_client(monkeypatch, stream_of(completed_response([])))
    monkeypatch.setattr(
        chatgpt_tokens, "load_subscription_credentials", lambda: ("refreshed-marker", "acct-marker")
    )
    client.chat([{"role": "user", "content": "hi"}])
    assert client.client.api_key == "refreshed-marker"

    def signed_out():
        raise CodexError("ChatGPT sign-in is required")

    monkeypatch.setattr(chatgpt_tokens, "load_subscription_credentials", signed_out)
    with pytest.raises(CodexError, match="sign-in is required"):
        client.chat([{"role": "user", "content": "hi again"}])
    assert len(client.client.responses.requests) == 1


def test_running_client_refuses_an_account_change(monkeypatch):
    client = build_client(monkeypatch, [])
    monkeypatch.setattr(
        chatgpt_tokens,
        "load_subscription_credentials",
        lambda: ("different-marker", "other-account"),
    )
    with pytest.raises(CodexError, match="account changed"):
        client.chat([{"role": "user", "content": "hi"}])
    assert client.client.responses.requests == []


@pytest.mark.parametrize("index", [-1, 4096, "0", True, None])
def test_stream_rejects_invalid_output_indices(monkeypatch, index):
    event = SimpleNamespace(
        type="response.output_item.done",
        output_index=index,
        item=SimpleNamespace(type="message", content=[]),
    )
    client = build_client(monkeypatch, [event])
    with pytest.raises(CodexError, match="invalid output item"):
        client.chat([{"role": "user", "content": "hi"}])


def test_completed_stream_items_are_not_duplicated(monkeypatch):
    item = SimpleNamespace(
        type="function_call",
        name="read_file",
        call_id="call-1",
        arguments='{"file_path":"fixture.txt"}',
    )
    event = SimpleNamespace(type="response.output_item.done", output_index=0, item=item)
    client = build_client(monkeypatch, [event, event, *stream_of(completed_response([item]))])
    response = client.chat([{"role": "user", "content": "hi"}])
    assert len(response["content"]) == 1
