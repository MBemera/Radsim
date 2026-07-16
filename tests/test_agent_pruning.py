"""Tests for session pruning conversation-integrity guarantees.

Pruning must never leave a tool_result whose matching tool_use was
removed — the API rejects such conversations.
"""

import json
import random
import time
from pathlib import Path
from types import SimpleNamespace

from radsim.agent import RadSimAgent


def make_agent_with_messages(messages):
    """Build a bare agent (no API client) with a message history."""
    agent = object.__new__(RadSimAgent)
    agent.messages = messages
    agent.config = SimpleNamespace(model="test-model")
    return agent


def tool_result_message(tool_use_id="tool_1"):
    return {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": "{}"}
        ],
    }


def tool_use_message(tool_use_id="tool_1", content_size=0):
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": tool_use_id,
                "name": "read_file",
                "input": {"path": "x" * content_size},
            }
        ],
    }


def build_pruning_cases():
    """Recreate the synthetic conversations used for Phase 0 goldens."""
    tool_result = tool_result_message()
    tool_result["content"][0]["content"] = "x" * 120
    return {
        "text_only": [
            {"role": "user", "content": "system context"},
            {"role": "assistant", "content": "ready"},
            *[
                {"role": "user" if index % 2 == 0 else "assistant", "content": "x" * 120}
                for index in range(8)
            ],
        ],
        "mixed_tool_pair": [
            {"role": "user", "content": "system context"},
            {"role": "assistant", "content": "ready"},
            tool_use_message(),
            tool_result,
            {"role": "assistant", "content": "x" * 120},
            {"role": "user", "content": "x" * 120},
            {"role": "assistant", "content": "done"},
        ],
        "images": [
            {"role": "user", "content": "system context"},
            {"role": "assistant", "content": "ready"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "a" * 240,
                        },
                    },
                ],
            },
            {"role": "assistant", "content": "x" * 120},
            {"role": "user", "content": "next"},
        ],
        "odd_count": [
            {"role": "user", "content": "system context"},
            {"role": "assistant", "content": "ready"},
            {"role": "user", "content": "x" * 120},
            {"role": "assistant", "content": "x" * 120},
            {"role": "user", "content": "x" * 120},
            {"role": "assistant", "content": "x" * 120},
            {"role": "user", "content": "final"},
        ],
        "malformed_legacy": [
            {"role": "user", "content": "system context"},
            {"role": "assistant", "content": "ready"},
            {"role": "user", "content": None},
            {"role": "assistant", "content": {"legacy": "x" * 160}},
            {"role": "user"},
            {"role": "assistant", "content": "x" * 160},
            {"role": "user", "content": "final"},
        ],
    }


def structured_block_ids(messages, block_type, id_field):
    """Collect tool block identifiers from structured messages."""
    identifiers = set()
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == block_type:
                identifiers.add(block.get(id_field))
    return identifiers


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
            tool_use_message(),
            tool_result_message(),
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


class TestLinearPruneSession:
    def test_retained_indices_match_phase_zero_goldens(self, monkeypatch):
        fixture_path = Path(__file__).parent / "fixtures" / "prune_session_golden.json"
        golden_indices = json.loads(fixture_path.read_text())
        monkeypatch.setattr("radsim.config.get_context_limit", lambda model: 100)

        for name, messages in build_pruning_cases().items():
            original_indices = {id(message): index for index, message in enumerate(messages)}
            agent = make_agent_with_messages(messages)

            agent.prune_session(target_percentage=70)

            retained_indices = [original_indices[id(message)] for message in agent.messages]
            assert retained_indices == golden_indices[name]

    def test_pruning_estimates_once_and_refreshes_once(self, monkeypatch):
        messages = build_pruning_cases()["text_only"]
        original_message_count = len(messages)
        agent = make_agent_with_messages(messages)
        estimate_calls = 0
        refresh_calls = 0

        def estimate_tokens(text):
            nonlocal estimate_calls
            estimate_calls += 1
            return len(text) // 4

        def refresh_context_usage():
            nonlocal refresh_calls
            refresh_calls += 1
            return 0, 100, 0

        agent.estimate_tokens = estimate_tokens
        agent.get_context_usage = refresh_context_usage
        monkeypatch.setattr("radsim.config.get_context_limit", lambda model: 100)

        agent.prune_session(target_percentage=70)

        assert estimate_calls == original_message_count
        assert refresh_calls == 1

    def test_random_valid_conversations_keep_tool_exchanges_intact(self, monkeypatch):
        monkeypatch.setattr("radsim.config.get_context_limit", lambda model: 100)

        for seed in range(50):
            random_generator = random.Random(seed)
            messages = [
                {"role": "user", "content": "system context"},
                {"role": "assistant", "content": "ready"},
            ]
            for exchange_index in range(20):
                if random_generator.choice([True, False]):
                    tool_use_id = f"tool_{exchange_index}"
                    messages.extend(
                        [
                            tool_use_message(tool_use_id, content_size=120),
                            tool_result_message(tool_use_id),
                        ]
                    )
                    continue
                messages.extend(
                    [
                        {"role": "user", "content": "x" * 120},
                        {"role": "assistant", "content": "x" * 120},
                    ]
                )

            agent = make_agent_with_messages(messages)
            agent.prune_session(target_percentage=70)

            if len(agent.messages) > 2:
                assert not agent._contains_block_type(agent.messages[2], "tool_result")
            tool_use_ids = structured_block_ids(agent.messages, "tool_use", "id")
            tool_result_ids = structured_block_ids(
                agent.messages, "tool_result", "tool_use_id"
            )
            assert tool_use_ids <= tool_result_ids

    def test_prunes_two_thousand_messages_under_fifty_milliseconds(
        self, monkeypatch, capsys
    ):
        messages = [
            {"role": "user", "content": "system context"},
            {"role": "assistant", "content": "ready"},
            *[
                {"role": "user" if index % 2 == 0 else "assistant", "content": "x" * 120}
                for index in range(1998)
            ],
        ]
        agent = make_agent_with_messages(messages)
        monkeypatch.setattr("radsim.config.get_context_limit", lambda model: 100)

        start_time = time.perf_counter()
        agent.prune_session(target_percentage=70)
        elapsed_seconds = time.perf_counter() - start_time
        capsys.readouterr()

        assert elapsed_seconds < 0.05
        assert len(agent.messages) == 4
