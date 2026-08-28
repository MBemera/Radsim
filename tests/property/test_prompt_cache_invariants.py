"""Property tests for provider prompt-caching invariants."""

from __future__ import annotations

import copy

from hypothesis import given, settings
from hypothesis import strategies as st

from radsim.prompt_cache import (
    CACHING_ENV_VAR,
    EPHEMERAL_CACHE_CONTROL,
    mark_conversation_breakpoint,
    minimum_cacheable_tokens,
    plan_system_cache,
)
from radsim.prompts import get_static_prompt

PROPERTY_TEST_SETTINGS = settings(max_examples=100, deadline=None)
MAX_CACHE_BREAKPOINTS = 4

CACHEABLE_MODELS = (
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-6",
    "anthropic/claude-sonnet-5",
)
ANY_MODEL = CACHEABLE_MODELS + ("gpt-5.2", "qwen/qwen3-coder:free", "")

system_prompt = st.one_of(
    st.text(max_size=200),
    st.text(max_size=200).map(lambda suffix: get_static_prompt() + suffix),
)

content_block = st.fixed_dictionaries(
    {
        "type": st.sampled_from(["text", "tool_result"]),
        "text": st.text(max_size=20),
    }
)

message = st.fixed_dictionaries(
    {
        "role": st.sampled_from(["user", "assistant"]),
        "content": st.one_of(st.text(max_size=20), st.lists(content_block, max_size=4)),
    }
)


@PROPERTY_TEST_SETTINGS
@given(
    prompt=system_prompt,
    model=st.sampled_from(ANY_MODEL),
    tool_tokens=st.integers(min_value=0, max_value=20_000),
)
def test_cached_blocks_always_reconstruct_the_prompt_exactly(prompt, model, tool_tokens):
    plan = plan_system_cache(prompt, model=model, tool_schema_tokens=tool_tokens, environ={})

    if plan.is_cached:
        assert "".join(block["text"] for block in plan.blocks) == prompt


@PROPERTY_TEST_SETTINGS
@given(
    prompt=system_prompt,
    model=st.sampled_from(ANY_MODEL),
    tool_tokens=st.integers(min_value=0, max_value=20_000),
)
def test_system_carries_exactly_one_breakpoint_when_cached(prompt, model, tool_tokens):
    plan = plan_system_cache(prompt, model=model, tool_schema_tokens=tool_tokens, environ={})

    if not plan.is_cached:
        return

    breakpoints = [block for block in plan.blocks if "cache_control" in block]
    assert len(breakpoints) == 1
    assert breakpoints[0] is plan.blocks[0]
    assert breakpoints[0]["cache_control"] == EPHEMERAL_CACHE_CONTROL
    assert len(plan.blocks) <= MAX_CACHE_BREAKPOINTS


@PROPERTY_TEST_SETTINGS
@given(
    prompt=system_prompt,
    model=st.sampled_from(ANY_MODEL),
    tool_tokens=st.integers(min_value=0, max_value=20_000),
)
def test_a_cached_prefix_never_falls_below_the_provider_minimum(prompt, model, tool_tokens):
    plan = plan_system_cache(prompt, model=model, tool_schema_tokens=tool_tokens, environ={})

    if plan.is_cached:
        assert plan.prefix_tokens >= minimum_cacheable_tokens(model)


@PROPERTY_TEST_SETTINGS
@given(
    prompt=system_prompt,
    model=st.sampled_from(ANY_MODEL),
    tool_tokens=st.integers(min_value=0, max_value=20_000),
)
def test_disabling_caching_always_skips_with_a_reason(prompt, model, tool_tokens):
    plan = plan_system_cache(
        prompt,
        model=model,
        tool_schema_tokens=tool_tokens,
        environ={CACHING_ENV_VAR: "0"},
    )

    assert plan.blocks is None
    assert plan.skipped_reason == "disabled"


@PROPERTY_TEST_SETTINGS
@given(prompt=system_prompt, model=st.sampled_from(ANY_MODEL))
def test_a_skipped_plan_always_explains_itself(prompt, model):
    plan = plan_system_cache(prompt, model=model, environ={})

    assert plan.is_cached is (plan.skipped_reason == "")


@PROPERTY_TEST_SETTINGS
@given(messages=st.lists(message, max_size=6))
def test_conversation_breakpoint_preserves_message_and_block_structure(messages):
    original = copy.deepcopy(messages)

    marked = mark_conversation_breakpoint(messages)

    assert messages == original
    assert len(marked) == len(messages)
    for marked_message, source_message in zip(marked, messages, strict=True):
        assert marked_message["role"] == source_message["role"]
        source_content = source_message["content"]
        if isinstance(source_content, list):
            assert len(marked_message["content"]) == len(source_content)
        else:
            assert marked_message["content"] == source_content


@PROPERTY_TEST_SETTINGS
@given(messages=st.lists(message, max_size=6))
def test_conversation_breakpoint_adds_at_most_one_marker(messages):
    marked = mark_conversation_breakpoint(messages)

    markers = [
        block
        for marked_message in marked
        if isinstance(marked_message["content"], list)
        for block in marked_message["content"]
        if isinstance(block, dict) and "cache_control" in block
    ]
    assert len(markers) <= 1
