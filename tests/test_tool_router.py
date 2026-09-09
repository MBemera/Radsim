"""Tests for deterministic capability-based tool-schema routing."""

from __future__ import annotations

import json

import pytest

from radsim.agent_constants import CONFIRMATION_TOOLS
from radsim.performance import PerformanceTelemetry
from radsim.tool_router import (
    BUDGET_ENV_VAR,
    CAPABILITY_GROUPS,
    COMMON_SCHEMA_TOKEN_TARGET,
    CORE_TOOL_NAMES,
    DEFAULT_SCHEMA_BUDGET_TOKENS,
    EXTERNAL_GROUP_NAME,
    MINIMUM_SCHEMA_BUDGET_TOKENS,
    ROUTING_ENV_VAR,
    estimate_schema_tokens,
    group_for_tool,
    matched_group_names,
    route_tool_schemas,
    routing_enabled,
    schema_budget_tokens,
    tools_in_group,
)
from radsim.tools import TOOL_DEFINITIONS


def _names(decision):
    return {tool["name"] for tool in decision.tools}


def _mcp_tool(name):
    return {
        "name": name,
        "description": "MCP-provided capability",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }


def test_every_registered_tool_is_core_or_grouped():
    grouped = set(CORE_TOOL_NAMES)
    for group in CAPABILITY_GROUPS:
        grouped.update(group.tools)

    registry_names = {tool["name"] for tool in TOOL_DEFINITIONS}
    assert registry_names - grouped == set()


def test_group_membership_is_unique_and_disjoint_from_core():
    seen = set()
    for group in CAPABILITY_GROUPS:
        assert not seen & set(group.tools)
        assert not set(group.tools) & set(CORE_TOOL_NAMES)
        seen.update(group.tools)


def test_common_payload_meets_the_schema_token_target():
    decision = route_tool_schemas(TOOL_DEFINITIONS, "tidy up the code")

    assert decision.group_names == ()
    assert _names(decision) == set(CORE_TOOL_NAMES)
    assert decision.schema_tokens < COMMON_SCHEMA_TOKEN_TARGET


def test_every_single_group_turn_fits_the_default_budget():
    for group in CAPABILITY_GROUPS:
        decision = route_tool_schemas(TOOL_DEFINITIONS, "carry on", extra_groups=[group.name])

        assert decision.dropped_group_names == ()
        assert decision.schema_tokens <= DEFAULT_SCHEMA_BUDGET_TOKENS


def test_routing_reduces_payload_against_the_full_registry():
    decision = route_tool_schemas(TOOL_DEFINITIONS, "read the config and run the tests")

    assert decision.schema_tokens < estimate_schema_tokens(list(TOOL_DEFINITIONS)) // 2


def test_core_tools_are_always_present():
    decision = route_tool_schemas(TOOL_DEFINITIONS, "commit the change and push the branch")

    assert set(CORE_TOOL_NAMES) <= _names(decision)


@pytest.mark.parametrize(
    ("request_text", "expected_group", "expected_tool"),
    [
        ("commit the staged files", "advanced_git", "git_commit"),
        ("fetch https://example.com/docs", "web_research", "web_fetch"),
        ("open the browser and click submit", "browser_automation", "browser_open"),
        ("summarise the pdf in docs", "documents_media", "read_document"),
        ("add the requests dependency", "dependencies", "add_dependency"),
        ("remember my deployment preference", "memory_learning", "save_memory"),
        ("deploy the container to staging", "operations", "deploy"),
        ("run ruff lint over the package", "code_intelligence", "lint_code"),
        ("delete the stale directory", "file_management", "delete_file"),
        ("delegate this plan to a subagent", "delegation", "delegate_task"),
        ("scaffold a new project", "project_setup", "init_project"),
        ("list the available skills", "skills", "list_skills"),
        ("add a custom tool for this repo", "custom_tools", "add_tool"),
    ],
)
def test_requests_select_their_capability_group(request_text, expected_group, expected_tool):
    decision = route_tool_schemas(TOOL_DEFINITIONS, request_text)

    assert expected_group in decision.group_names
    assert expected_tool in _names(decision)


def test_explicit_tool_name_selects_its_group():
    decision = route_tool_schemas(TOOL_DEFINITIONS, "use git_stash before you continue")

    assert "advanced_git" in decision.group_names
    assert "git_stash" in _names(decision)


def test_routing_is_deterministic_for_the_same_request():
    first = route_tool_schemas(TOOL_DEFINITIONS, "fetch the url then commit")
    second = route_tool_schemas(TOOL_DEFINITIONS, "fetch the url then commit")

    assert first.group_names == second.group_names
    assert [tool["name"] for tool in first.tools] == [tool["name"] for tool in second.tools]


def test_routing_preserves_registry_order_and_schema_content():
    decision = route_tool_schemas(TOOL_DEFINITIONS, "commit the change")
    registry_order = [tool["name"] for tool in TOOL_DEFINITIONS if tool["name"] in _names(decision)]

    assert [tool["name"] for tool in decision.tools] == registry_order
    for tool in decision.tools:
        assert tool is TOOL_DEFINITIONS[[t["name"] for t in TOOL_DEFINITIONS].index(tool["name"])]


def test_budget_drops_lowest_priority_groups_first():
    request_text = "commit the branch then deploy the docker container"
    generous = route_tool_schemas(TOOL_DEFINITIONS, request_text, budget_tokens=10_000)
    constrained = route_tool_schemas(TOOL_DEFINITIONS, request_text, budget_tokens=2_500)

    assert generous.group_names == ("advanced_git", "operations")
    assert constrained.group_names == ("advanced_git",)
    assert constrained.dropped_group_names == ("operations",)
    assert constrained.schema_tokens <= 2_500


def test_core_survives_an_impossible_budget():
    decision = route_tool_schemas(TOOL_DEFINITIONS, "commit the branch", budget_tokens=1)

    assert _names(decision) == set(CORE_TOOL_NAMES)
    assert decision.group_names == ()
    assert decision.failed is False


def test_required_names_are_never_routed_away():
    decision = route_tool_schemas(
        TOOL_DEFINITIONS,
        "just read the file",
        budget_tokens=1,
        required_names=["git_commit"],
    )

    assert "git_commit" in _names(decision)


def test_extra_groups_are_honoured_without_matching_keywords():
    decision = route_tool_schemas(TOOL_DEFINITIONS, "carry on", extra_groups=["browser_automation"])

    assert "browser_automation" in decision.group_names
    assert "browser_open" in _names(decision)


def test_unknown_extra_groups_are_ignored():
    decision = route_tool_schemas(TOOL_DEFINITIONS, "carry on", extra_groups=["not_a_group"])

    assert decision.group_names == ()


def test_mcp_tools_are_lazily_loaded_as_the_external_group():
    tools = list(TOOL_DEFINITIONS) + [_mcp_tool("weather_lookup")]

    idle = route_tool_schemas(tools, "read the config file")
    requested = route_tool_schemas(tools, "call weather_lookup for Sydney")

    assert "weather_lookup" not in _names(idle)
    assert "weather_lookup" in _names(requested)
    assert EXTERNAL_GROUP_NAME in requested.group_names


def test_unnamed_schema_fails_open_to_every_tool():
    tools = list(TOOL_DEFINITIONS) + [{"description": "no name"}]

    decision = route_tool_schemas(tools, "read the config file")

    assert decision.failed is True
    assert len(decision.tools) == len(tools)


def test_duplicate_schema_names_fail_open_to_every_tool():
    tools = list(TOOL_DEFINITIONS) + [_mcp_tool("read_file")]

    decision = route_tool_schemas(tools, "read the config file")

    assert decision.failed is True
    assert len(decision.tools) == len(tools)


def test_routing_never_bypasses_confirmation_classification():
    decision = route_tool_schemas(TOOL_DEFINITIONS, "commit the branch and deploy")

    routed_confirmation_tools = _names(decision) & CONFIRMATION_TOOLS
    assert routed_confirmation_tools
    for tool_name in routed_confirmation_tools:
        assert tool_name in CONFIRMATION_TOOLS


def test_group_for_tool_classifies_core_grouped_and_external_names():
    available = {tool["name"] for tool in TOOL_DEFINITIONS} | {"weather_lookup"}

    assert group_for_tool("read_file", available) is None
    assert group_for_tool("git_commit", available) == "advanced_git"
    assert group_for_tool("weather_lookup", available) == EXTERNAL_GROUP_NAME
    assert group_for_tool("never_registered", available) is None


def test_tools_in_group_returns_only_available_names():
    assert tools_in_group("advanced_git", ["git_commit", "read_file"]) == ("git_commit",)
    assert tools_in_group("not_a_group", ["git_commit"]) == ()
    assert tools_in_group(EXTERNAL_GROUP_NAME, ["git_commit", "weather_lookup"]) == (
        "weather_lookup",
    )


def test_matched_group_names_are_returned_in_priority_order():
    matched = matched_group_names("deploy the container after you commit the branch")

    assert matched == ("advanced_git", "operations")


def test_matched_group_names_ignore_substrings_of_other_words():
    assert matched_group_names("recommitment to quality") == ()


def test_matched_group_names_bound_the_scanned_request():
    padded = ("x " * 15_000) + "commit the branch"

    assert matched_group_names(padded) == ()
    assert matched_group_names("commit the branch " + padded) == ("advanced_git",)


def test_estimate_schema_tokens_matches_the_telemetry_rule():
    serialized = json.dumps(
        list(TOOL_DEFINITIONS),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert estimate_schema_tokens(list(TOOL_DEFINITIONS)) == (len(serialized) + 3) // 4
    assert estimate_schema_tokens([]) == 0


def test_routing_is_disabled_unless_explicitly_enabled():
    assert routing_enabled({}) is False
    assert routing_enabled({ROUTING_ENV_VAR: "0"}) is False
    assert routing_enabled({ROUTING_ENV_VAR: "maybe"}) is False
    assert routing_enabled({ROUTING_ENV_VAR: " On "}) is True
    assert routing_enabled({ROUTING_ENV_VAR: "1"}) is True


def test_schema_budget_rejects_unusable_values():
    assert schema_budget_tokens({}) == DEFAULT_SCHEMA_BUDGET_TOKENS
    assert schema_budget_tokens({BUDGET_ENV_VAR: "abc"}) == DEFAULT_SCHEMA_BUDGET_TOKENS
    assert schema_budget_tokens({BUDGET_ENV_VAR: "-5"}) == DEFAULT_SCHEMA_BUDGET_TOKENS
    assert schema_budget_tokens({BUDGET_ENV_VAR: "10"}) == MINIMUM_SCHEMA_BUDGET_TOKENS
    assert schema_budget_tokens({BUDGET_ENV_VAR: " 3000 "}) == 3_000


class _RoutingAgent:
    """Minimal stand-in exposing only the routing surface under test."""

    def __init__(self, telemetry):
        self.performance_telemetry = telemetry
        self._routed_tool_names = None
        self._performance_turn_id = "turn-1"
        self._mcp_manager = None

    _get_all_tools = None  # replaced per test to avoid importing the full agent


def _routing_agent(telemetry, tools):
    from radsim.agent_api import AgentApiMixin

    class Agent(AgentApiMixin, _RoutingAgent):
        def _get_all_tools(self):
            return list(tools)

    return Agent(telemetry)


def test_turn_routing_is_skipped_when_the_flag_is_off(monkeypatch, tmp_path):
    monkeypatch.delenv(ROUTING_ENV_VAR, raising=False)
    telemetry = PerformanceTelemetry(tmp_path / "off.jsonl", enabled=True)
    agent = _routing_agent(telemetry, TOOL_DEFINITIONS)

    agent._route_tool_schemas_for_turn("commit the branch", telemetry, "turn-1")

    assert agent._routed_tool_names is None
    assert len(agent._get_request_tools()) == len(TOOL_DEFINITIONS)
    assert not (tmp_path / "off.jsonl").exists()


def test_turn_routing_filters_request_tools_and_emits_telemetry(monkeypatch, tmp_path):
    monkeypatch.setenv(ROUTING_ENV_VAR, "1")
    path = tmp_path / "routing.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)
    agent = _routing_agent(telemetry, TOOL_DEFINITIONS)

    agent._route_tool_schemas_for_turn("commit the branch", telemetry, "turn-1")
    request_tools = agent._get_request_tools()

    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["event"] == "tool_routing"
    assert record["routed_groups"] == "advanced_git"
    assert record["routed_tool_count"] == len(request_tools)
    assert record["routing_failed"] is False
    assert len(request_tools) < len(TOOL_DEFINITIONS)
    assert {tool["name"] for tool in request_tools} >= set(CORE_TOOL_NAMES)


def test_recovery_restores_a_routed_away_group(monkeypatch, tmp_path):
    monkeypatch.setenv(ROUTING_ENV_VAR, "1")
    path = tmp_path / "recovery.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)
    agent = _routing_agent(telemetry, TOOL_DEFINITIONS)
    agent._route_tool_schemas_for_turn("read the config file", telemetry, "turn-1")

    assert "git_commit" not in agent._routed_tool_names

    agent._recover_routed_tool("git_commit")

    assert {"git_commit", "git_stash"} <= agent._routed_tool_names
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    recovery = [event for event in events if event["event"] == "tool_routing_recovery"]
    assert recovery[0]["routing_recovered_group"] == "advanced_git"
    assert recovery[0]["tool_name"] == "git_commit"


def test_recovery_is_a_no_op_for_already_routed_tools(monkeypatch, tmp_path):
    monkeypatch.setenv(ROUTING_ENV_VAR, "1")
    path = tmp_path / "no-op.jsonl"
    telemetry = PerformanceTelemetry(path, enabled=True)
    agent = _routing_agent(telemetry, TOOL_DEFINITIONS)
    agent._route_tool_schemas_for_turn("read the config file", telemetry, "turn-1")
    before = set(agent._routed_tool_names)

    agent._recover_routed_tool("read_file")

    assert agent._routed_tool_names == before
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [event for event in events if event["event"] == "tool_routing_recovery"] == []


def test_recovery_admits_an_unclassified_tool_without_a_group(monkeypatch, tmp_path):
    monkeypatch.setenv(ROUTING_ENV_VAR, "1")
    telemetry = PerformanceTelemetry(tmp_path / "unknown.jsonl", enabled=True)
    agent = _routing_agent(telemetry, TOOL_DEFINITIONS)
    agent._route_tool_schemas_for_turn("read the config file", telemetry, "turn-1")

    agent._recover_routed_tool("hallucinated_tool")

    assert "hallucinated_tool" in agent._routed_tool_names


def test_fixed_context_tokens_follow_the_routed_schema_set():
    from types import SimpleNamespace

    from radsim.agent import RadSimAgent

    agent = object.__new__(RadSimAgent)
    agent.messages = []
    agent.config = SimpleNamespace(model="test-model")
    agent.system_prompt = ""
    agent._mcp_manager = None
    agent._routed_tool_names = None

    unrouted_tokens = agent._fixed_context_tokens()
    agent._routed_tool_names = set(CORE_TOOL_NAMES)
    routed_tokens = agent._fixed_context_tokens()

    assert routed_tokens < unrouted_tokens


def test_recovery_does_nothing_when_routing_never_ran(tmp_path):
    telemetry = PerformanceTelemetry(tmp_path / "idle.jsonl", enabled=True)
    agent = _routing_agent(telemetry, TOOL_DEFINITIONS)

    agent._recover_routed_tool("git_commit")

    assert agent._routed_tool_names is None
