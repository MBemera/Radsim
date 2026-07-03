"""Tests for session pruning conversation-integrity guarantees.

Pruning must never leave a tool_result whose matching tool_use was
removed — the API rejects such conversations.
"""

from radsim.agent import RadSimAgent


def make_agent_with_messages(messages):
    """Build a bare agent (no API client) with a message history."""
    agent = object.__new__(RadSimAgent)
    agent.messages = messages
    return agent


def tool_result_message(tool_use_id="tool_1"):
    return {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": "{}"}
        ],
    }


class TestDropOrphanedToolMessages:
    def test_removes_leading_orphan_tool_result(self):
        agent = make_agent_with_messages([
            {"role": "user", "content": "context"},
            {"role": "assistant", "content": "ok"},
            tool_result_message(),
            {"role": "assistant", "content": "done"},
        ])

        removed = agent._drop_orphaned_tool_messages(start_index=2)

        assert removed == 1
        assert agent.messages[2] == {"role": "assistant", "content": "done"}

    def test_removes_consecutive_orphan_tool_results(self):
        agent = make_agent_with_messages([
            {"role": "user", "content": "context"},
            {"role": "assistant", "content": "ok"},
            tool_result_message("tool_1"),
            tool_result_message("tool_2"),
            {"role": "user", "content": "next question"},
        ])

        removed = agent._drop_orphaned_tool_messages(start_index=2)

        assert removed == 2
        assert agent.messages[2] == {"role": "user", "content": "next question"}

    def test_keeps_plain_user_message_at_boundary(self):
        agent = make_agent_with_messages([
            {"role": "user", "content": "context"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "plain question"},
        ])

        removed = agent._drop_orphaned_tool_messages(start_index=2)

        assert removed == 0
        assert len(agent.messages) == 3

    def test_keeps_intact_tool_use_result_pair(self):
        agent = make_agent_with_messages([
            {"role": "user", "content": "context"},
            {"role": "assistant", "content": "ok"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tool_1", "name": "read_file", "input": {}}
                ],
            },
            tool_result_message("tool_1"),
        ])

        removed = agent._drop_orphaned_tool_messages(start_index=2)

        assert removed == 0
        assert len(agent.messages) == 4

    def test_no_messages_beyond_boundary(self):
        agent = make_agent_with_messages([
            {"role": "user", "content": "context"},
            {"role": "assistant", "content": "ok"},
        ])

        removed = agent._drop_orphaned_tool_messages(start_index=2)

        assert removed == 0
