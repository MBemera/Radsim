"""Tests for provider tool-call argument parsing in api_client."""

from types import SimpleNamespace

from radsim.api_client import OpenAIClient, _parse_tool_arguments


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
