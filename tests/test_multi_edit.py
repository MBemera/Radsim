# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Tests for multi_edit atomic batch editing."""

import pytest

from radsim.tools.file_ops import multi_edit


@pytest.fixture
def temp_file(tmp_path, monkeypatch):
    """Create a temporary file and chdir to its parent."""
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "test.py"
    test_file.write_text(
        "def hello():\n"
        "    return 'hello'\n"
        "\n"
        "def world():\n"
        "    return 'world'\n"
        "\n"
        "def main():\n"
        "    print(hello(), world())\n",
        encoding="utf-8",
    )
    return test_file


class TestMultiEditSuccess:
    def test_single_edit(self, temp_file):
        result = multi_edit(
            "test.py",
            [{"old_string": "def hello():", "new_string": "def greet():"}],
        )
        assert result["success"] is True
        assert result["edits_applied"] == 1
        content = temp_file.read_text()
        assert "def greet():" in content
        assert "def hello():" not in content

    def test_multiple_edits(self, temp_file):
        result = multi_edit(
            "test.py",
            [
                {"old_string": "def hello():", "new_string": "def greet():"},
                {"old_string": "def world():", "new_string": "def planet():"},
            ],
        )
        assert result["success"] is True
        assert result["edits_applied"] == 2
        content = temp_file.read_text()
        assert "def greet():" in content
        assert "def planet():" in content

    def test_sequential_edits_that_depend_rejected(self, temp_file):
        """Edit 2 references text introduced by edit 1 — rejected during validation."""
        original = temp_file.read_text()
        result = multi_edit(
            "test.py",
            [
                {"old_string": "return 'hello'", "new_string": "return 'hi'"},
                {"old_string": "return 'hi'", "new_string": "return 'hey'"},
            ],
        )
        assert result["success"] is False
        assert "not found" in result["error"]
        # Atomic: original file unchanged
        assert temp_file.read_text() == original


class TestMultiEditValidation:
    def test_empty_edits_rejected(self, temp_file):
        result = multi_edit("test.py", [])
        assert result["success"] is False
        assert "No edits" in result["error"]

    def test_missing_old_string_rejected(self, temp_file):
        result = multi_edit(
            "test.py",
            [{"old_string": "NONEXISTENT", "new_string": "replacement"}],
        )
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_non_unique_old_string_rejected(self, temp_file):
        result = multi_edit(
            "test.py",
            [{"old_string": "return", "new_string": "yield"}],
        )
        assert result["success"] is False
        assert "matches" in result["error"]

    def test_all_or_nothing_on_validation_failure(self, temp_file):
        """If one edit fails validation, no edits are applied."""
        original = temp_file.read_text()
        result = multi_edit(
            "test.py",
            [
                {"old_string": "def hello():", "new_string": "def greet():"},
                {"old_string": "NONEXISTENT", "new_string": "foo"},
            ],
        )
        assert result["success"] is False
        assert temp_file.read_text() == original

    def test_empty_old_string_rejected(self, temp_file):
        result = multi_edit(
            "test.py",
            [{"old_string": "", "new_string": "something"}],
        )
        assert result["success"] is False
        assert "empty" in result["error"]


class TestMultiEditEdgeCases:
    def test_file_not_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = multi_edit("nonexistent.py", [{"old_string": "a", "new_string": "b"}])
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_protected_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=123", encoding="utf-8")
        result = multi_edit(".env", [{"old_string": "SECRET", "new_string": "KEY"}])
        assert result["success"] is False

    def test_details_list_returned(self, temp_file):
        result = multi_edit(
            "test.py",
            [{"old_string": "def hello():", "new_string": "def greet():"}],
        )
        assert result["success"] is True
        assert len(result["details"]) == 1
        assert "Edit 1" in result["details"][0]
