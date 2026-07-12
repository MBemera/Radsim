"""End-to-end skill learning: chat-taught skills must reach the system prompt.

The agent teaches itself via the add_skill/remove_skill/list_skills tools,
so these tests drive the same execute_tool path the model uses in chat.
"""

import pytest

import radsim.skills as skills_module
from radsim.tools import execute_tool


@pytest.fixture(autouse=True)
def isolated_skills(tmp_path, monkeypatch):
    """Point skill storage at a temp file so tests never touch ~/.radsim."""
    monkeypatch.setattr(skills_module, "SKILLS_FILE", tmp_path / "skills.json")


class TestSkillToolsFromChat:
    """The tool path the model calls when taught something in conversation."""

    def test_add_skill_tool_persists_the_instruction(self):
        result = execute_tool("add_skill", {"instruction": "Always use pytest fixtures"})

        assert result["success"] is True
        saved = [skill["instruction"] for skill in skills_module.list_skills()]
        assert saved == ["Always use pytest fixtures"]

    def test_duplicate_skill_is_rejected(self):
        execute_tool("add_skill", {"instruction": "Prefer dataclasses"})
        result = execute_tool("add_skill", {"instruction": "prefer dataclasses"})

        assert result["success"] is False
        assert len(skills_module.list_skills()) == 1

    def test_empty_instruction_is_rejected(self):
        result = execute_tool("add_skill", {"instruction": "   "})
        assert result["success"] is False

    def test_list_skills_tool_returns_saved_skills(self):
        execute_tool("add_skill", {"instruction": "Use type hints everywhere"})

        result = execute_tool("list_skills", {})

        assert result["success"] is True
        assert result["count"] == 1
        assert result["skills"][0]["instruction"] == "Use type hints everywhere"

    def test_remove_skill_tool_uses_one_based_index(self):
        execute_tool("add_skill", {"instruction": "Prefer dataclasses"})

        result = execute_tool("remove_skill", {"index": 1})

        assert result["success"] is True
        assert skills_module.list_skills() == []


class TestSkillsReachTheSystemPrompt:
    """A saved skill is useless unless the model actually sees it."""

    def test_saved_skill_appears_in_system_prompt(self):
        instruction = "Always use pytest fixtures instead of setUp methods"
        execute_tool("add_skill", {"instruction": instruction})

        from radsim.prompts import get_system_prompt

        assert instruction in get_system_prompt()

    def test_removed_skill_leaves_the_system_prompt(self):
        instruction = "Temporarily prefer tabs over spaces"
        execute_tool("add_skill", {"instruction": instruction})
        execute_tool("remove_skill", {"index": 1})

        from radsim.prompts import get_system_prompt

        assert instruction not in get_system_prompt()
