"""Long-session memory bounds and payload-release tests."""

import json

from radsim.agent_api import MAX_SERIALIZED_TOOL_RESULT_CHARS, serialize_tool_result
from radsim.agent_conversation import (
    MAX_RETAINED_MESSAGES,
    RETAINED_MEDIA_TEXT,
    AgentConversationMixin,
)
from radsim.learning.events import (
    MAX_TRACKED_TOOL_RESULTS,
    TaskOutcome,
    TaskOutcomeTracker,
)


class ConversationState(AgentConversationMixin):
    """Minimal concrete owner for conversation-state helpers."""


def _tool_exchange(index):
    return [
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": f"tool-{index}"}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": f"tool-{index}"}],
        },
    ]


def test_message_retention_keeps_complete_tool_exchanges():
    agent = ConversationState()
    first_messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "first answer"},
    ]
    agent.messages = list(first_messages)
    for index in range(MAX_RETAINED_MESSAGES):
        agent.messages.extend(_tool_exchange(index))

    removed = agent._enforce_message_retention()

    assert removed > 0
    assert len(agent.messages) <= MAX_RETAINED_MESSAGES
    assert agent.messages[:2] == first_messages
    for index, message in enumerate(agent.messages[2:], start=2):
        if agent._contains_block_type(message, "tool_result"):
            assert agent._contains_block_type(agent.messages[index - 1], "tool_use")


def test_processed_image_bytes_are_released_from_history():
    agent = ConversationState()
    agent.messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "data": "A" * 50_000},
                }
            ],
        }
    ]

    assert agent._release_processed_media() == 1
    assert agent.messages[0]["content"] == [
        {"type": "text", "text": RETAINED_MEDIA_TEXT}
    ]
    assert agent._release_processed_media() == 0


def test_serialized_tool_results_are_valid_bounded_json():
    serialized = serialize_tool_result({"success": True, "content": "x" * 200_000})
    decoded = json.loads(serialized)

    assert len(serialized) <= MAX_SERIALIZED_TOOL_RESULT_CHARS
    assert decoded["success"] is True
    assert decoded["truncated"] is True
    assert decoded["original_chars"] > MAX_SERIALIZED_TOOL_RESULT_CHARS


def test_tool_outcome_evidence_is_bounded_without_losing_failure_state():
    tracker = TaskOutcomeTracker("long tool turn")
    tracker.record_tool("run_tests", False, error="failed")
    for index in range(MAX_TRACKED_TOOL_RESULTS):
        tracker.record_tool(f"read_{index}", True)

    event = tracker.build_event()

    assert len(tracker.tool_results) == MAX_TRACKED_TOOL_RESULTS
    assert tracker.dropped_tool_results == 1
    assert tracker.resolve() is TaskOutcome.PARTIALLY_SUCCESSFUL
    assert event.metadata["tool_results_dropped"] == 1
