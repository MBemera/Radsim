"""Property tests for capability-based tool-schema routing invariants."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from radsim.tool_router import (
    CAPABILITY_GROUPS,
    COMMON_SCHEMA_TOKEN_TARGET,
    CORE_TOOL_NAMES,
    EXTERNAL_GROUP_NAME,
    MINIMUM_SCHEMA_BUDGET_TOKENS,
    estimate_schema_tokens,
    group_for_tool,
    matched_group_names,
    route_tool_schemas,
    tools_in_group,
)
from radsim.tools import TOOL_DEFINITIONS

PROPERTY_TEST_SETTINGS = settings(max_examples=100, deadline=None)

REGISTRY_NAMES = tuple(tool["name"] for tool in TOOL_DEFINITIONS)
GROUP_NAMES = tuple(group.name for group in CAPABILITY_GROUPS)
KEYWORDS = tuple(keyword for group in CAPABILITY_GROUPS for keyword in group.keywords)

request_text = st.one_of(
    st.text(max_size=200),
    st.lists(st.sampled_from(KEYWORDS + REGISTRY_NAMES), max_size=8).map(" ".join),
)


@PROPERTY_TEST_SETTINGS
@given(text=request_text, budget=st.integers(min_value=1, max_value=20_000))
def test_core_tools_survive_every_request_and_budget(text, budget):
    decision = route_tool_schemas(TOOL_DEFINITIONS, text, budget_tokens=budget)

    assert set(CORE_TOOL_NAMES) <= decision.tool_names


@PROPERTY_TEST_SETTINGS
@given(text=request_text)
def test_routing_never_invents_or_duplicates_a_schema(text):
    decision = route_tool_schemas(TOOL_DEFINITIONS, text)
    routed = [tool["name"] for tool in decision.tools]

    assert len(routed) == len(set(routed))
    assert set(routed) <= set(REGISTRY_NAMES)


@PROPERTY_TEST_SETTINGS
@given(text=request_text)
def test_every_matched_capability_group_is_fully_routed(text):
    decision = route_tool_schemas(TOOL_DEFINITIONS, text, budget_tokens=20_000)

    for group_name in matched_group_names(text, REGISTRY_NAMES):
        assert set(tools_in_group(group_name, REGISTRY_NAMES)) <= decision.tool_names


@PROPERTY_TEST_SETTINGS
@given(
    text=request_text,
    budget=st.integers(min_value=MINIMUM_SCHEMA_BUDGET_TOKENS, max_value=20_000),
)
def test_routed_payload_respects_the_budget_once_core_fits(text, budget):
    decision = route_tool_schemas(TOOL_DEFINITIONS, text, budget_tokens=budget)
    core_tokens = estimate_schema_tokens(
        [tool for tool in TOOL_DEFINITIONS if tool["name"] in CORE_TOOL_NAMES]
    )

    if core_tokens <= budget:
        assert decision.schema_tokens <= budget


@PROPERTY_TEST_SETTINGS
@given(text=request_text)
def test_common_requests_stay_under_the_schema_token_target(text):
    decision = route_tool_schemas(TOOL_DEFINITIONS, text)

    if not decision.group_names:
        assert decision.schema_tokens < COMMON_SCHEMA_TOKEN_TARGET


@PROPERTY_TEST_SETTINGS
@given(text=request_text, budget=st.integers(min_value=1, max_value=20_000))
def test_required_names_are_never_routed_away(text, budget):
    decision = route_tool_schemas(
        TOOL_DEFINITIONS,
        text,
        budget_tokens=budget,
        required_names=REGISTRY_NAMES[:5],
    )

    assert set(REGISTRY_NAMES[:5]) <= decision.tool_names


@PROPERTY_TEST_SETTINGS
@given(text=request_text, tool_name=st.sampled_from(REGISTRY_NAMES))
def test_a_routed_away_tool_is_always_recoverable_through_its_group(text, tool_name):
    decision = route_tool_schemas(TOOL_DEFINITIONS, text)
    if tool_name in decision.tool_names:
        return

    group_name = group_for_tool(tool_name, REGISTRY_NAMES)
    assert group_name is not None
    assert tool_name in tools_in_group(group_name, REGISTRY_NAMES)


@PROPERTY_TEST_SETTINGS
@given(text=request_text, groups=st.lists(st.sampled_from(GROUP_NAMES), max_size=4))
def test_selected_groups_keep_declaration_priority_order(text, groups):
    decision = route_tool_schemas(
        TOOL_DEFINITIONS,
        text,
        budget_tokens=20_000,
        extra_groups=groups,
    )
    priority = {name: index for index, name in enumerate(GROUP_NAMES)}

    positions = [priority[name] for name in decision.group_names]
    assert positions == sorted(positions)


@PROPERTY_TEST_SETTINGS
@given(text=request_text)
def test_routing_is_deterministic(text):
    first = route_tool_schemas(TOOL_DEFINITIONS, text)
    second = route_tool_schemas(TOOL_DEFINITIONS, text)

    assert first.group_names == second.group_names
    assert [tool["name"] for tool in first.tools] == [tool["name"] for tool in second.tools]


@PROPERTY_TEST_SETTINGS
@given(
    text=request_text,
    external_names=st.lists(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=3, max_size=20),
        max_size=5,
        unique=True,
    ),
)
def test_unclassified_tools_are_routed_only_as_the_external_group(text, external_names):
    extras = [name for name in external_names if name not in set(REGISTRY_NAMES)]
    tools = list(TOOL_DEFINITIONS) + [
        {"name": name, "description": name, "input_schema": {"type": "object", "properties": {}}}
        for name in extras
    ]

    decision = route_tool_schemas(tools, text, budget_tokens=20_000)
    routed_extras = decision.tool_names & set(extras)

    if routed_extras:
        assert EXTERNAL_GROUP_NAME in decision.group_names
