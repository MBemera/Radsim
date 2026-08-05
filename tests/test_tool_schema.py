"""Contracts for deterministic provider-facing tool schemas."""

import json

import pytest

from radsim.api_client import ClaudeClient, OpenAIClient
from radsim.tool_schema import canonicalize_tool_schemas

TOOLS = [
    {
        "name": "zeta",
        "description": "Last tool",
        "input_schema": {
            "properties": {"z": {"type": "string"}, "a": {"type": "integer"}},
            "type": "object",
        },
    },
    {
        "input_schema": {"type": "object", "properties": {}},
        "description": "First tool",
        "name": "alpha",
    },
]


def test_canonicalization_is_byte_stable_across_input_order():
    first = canonicalize_tool_schemas(TOOLS)
    reversed_input = canonicalize_tool_schemas(list(reversed(TOOLS)))

    assert json.dumps(first) == json.dumps(reversed_input)
    assert [tool["name"] for tool in first] == ["alpha", "zeta"]
    assert list(first[1]["input_schema"]["properties"]) == ["a", "z"]


@pytest.mark.parametrize(
    "tools",
    [
        [{"description": "missing name"}],
        [{"name": "   "}],
        [{"name": "same"}, {"name": "same"}],
        [{"name": "valid", "input_schema": {1: "invalid-key"}}],
        ["not-an-object"],
    ],
)
def test_malformed_or_duplicate_schemas_fail_before_provider_io(tools):
    with pytest.raises(ValueError):
        canonicalize_tool_schemas(tools)


def test_claude_request_serialization_is_stable():
    client = ClaudeClient.__new__(ClaudeClient)
    client.model = "claude-test"

    first = client._build_request_kwargs([], tools=TOOLS)
    second = client._build_request_kwargs([], tools=list(reversed(TOOLS)))

    assert json.dumps(first) == json.dumps(second)


def test_openai_request_serialization_is_stable():
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-test"
    client.reasoning_effort = None

    first = client._build_request_kwargs([], tools=TOOLS)
    second = client._build_request_kwargs([], tools=list(reversed(TOOLS)))

    assert json.dumps(first) == json.dumps(second)
