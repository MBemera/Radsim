"""Tests for provider tool-call argument parsing in api_client."""

from types import SimpleNamespace

from radsim.api_client import ClaudeClient, OpenAIClient, _parse_tool_arguments


class EmptyClaudeStream:
    def __enter__(self):
        return iter(())

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class TestParseToolArguments:
    def test_valid_json_object_is_parsed(self):
        assert _parse_tool_arguments('{"path": "a.txt"}', "read_file") == {"path": "a.txt"}

    def test_empty_string_means_no_arguments(self):
        assert _parse_tool_arguments("", "list_files") == {}
        assert _parse_tool_arguments("   ", "list_files") == {}
        assert _parse_tool_arguments(None, "list_files") == {}

    def test_malformed_json_returns_marked_error(self):
        result = _parse_tool_arguments('{"path": ', "read_file")
        assert "__parse_error__" in result
        assert result["__raw__"] == '{"path": '

    def test_non_object_json_returns_marked_error(self):
        result = _parse_tool_arguments('["not", "a", "dict"]', "read_file")
        assert "__parse_error__" in result

    def test_raw_preview_is_capped(self):
        result = _parse_tool_arguments("{" + "x" * 2000, "read_file")
        assert len(result["__raw__"]) == 500


class TestOpenAIParseResponse:
    def _response_with_arguments(self, arguments):
        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="read_file", arguments=arguments),
        )
        message = SimpleNamespace(content=None, tool_calls=[tool_call])
        choice = SimpleNamespace(message=message, finish_reason="tool_calls")
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        return SimpleNamespace(choices=[choice], usage=usage)

    def test_valid_arguments_are_parsed(self):
        client = OpenAIClient.__new__(OpenAIClient)
        response = client._parse_response(self._response_with_arguments('{"path": "a.txt"}'))
        assert response["content"][0]["input"] == {"path": "a.txt"}

    def test_malformed_arguments_do_not_raise(self):
        client = OpenAIClient.__new__(OpenAIClient)
        response = client._parse_response(self._response_with_arguments('{"path": '))
        assert "__parse_error__" in response["content"][0]["input"]

    def test_empty_arguments_become_empty_dict(self):
        client = OpenAIClient.__new__(OpenAIClient)
        response = client._parse_response(self._response_with_arguments(""))
        assert response["content"][0]["input"] == {}


class TestRequestKwargsParity:
    messages = [{"role": "user", "content": "hello"}]
    tools = [
        {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]

    def test_openai_chat_and_stream_use_matching_kwargs(self):
        chat_kwargs = {}
        stream_kwargs = {}
        client = OpenAIClient.__new__(OpenAIClient)
        client.model = "gpt-test"
        client.reasoning_effort = "medium"
        client._chat_with_retry = lambda **kwargs: chat_kwargs.update(kwargs)
        completions = SimpleNamespace(create=lambda **kwargs: stream_kwargs.update(kwargs) or [])
        client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        client.chat(self.messages, "system", self.tools)
        list(client.stream_chat(self.messages, "system", self.tools))

        stream_kwargs.pop("stream")
        stream_kwargs.pop("stream_options")
        assert chat_kwargs == stream_kwargs

    def test_claude_chat_and_stream_use_matching_kwargs(self):
        chat_kwargs = {}
        stream_kwargs = {}
        client = ClaudeClient.__new__(ClaudeClient)
        client.model = "claude-test"
        client._chat_with_retry = lambda **kwargs: chat_kwargs.update(kwargs)
        messages_api = SimpleNamespace(
            create=lambda **kwargs: stream_kwargs.update(kwargs) or EmptyClaudeStream()
        )
        client.client = SimpleNamespace(messages=messages_api)

        client.chat(self.messages, "system", self.tools)
        list(client.stream_chat(self.messages, "system", self.tools))

        stream_kwargs.pop("stream")
        assert chat_kwargs == stream_kwargs
