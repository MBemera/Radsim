# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Tests for apply_patch multi-file unified diff tool."""

import pytest

from radsim.patch import _parse_patch, apply_patch


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """Create a temp project with two files and chdir there."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hello.py").write_text(
        "def hello():\n    return 'hello'\n", encoding="utf-8"
    )
    (tmp_path / "world.py").write_text(
        "def world():\n    return 'world'\n", encoding="utf-8"
    )
    return tmp_path


class TestApplyPatchModify:
    def test_single_file_modify(self, project_dir):
        patch = (
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@\n"
            "-    return 'hello'\n"
            "+    return 'hi'\n"
        )
        result = apply_patch(patch)
        assert result["success"] is True
        assert "hello.py" in result["files_modified"]
        content = (project_dir / "hello.py").read_text()
        assert "return 'hi'" in content

    def test_multi_file_modify(self, project_dir):
        patch = (
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@\n"
            "-    return 'hello'\n"
            "+    return 'hi'\n"
            "--- a/world.py\n"
            "+++ b/world.py\n"
            "@@\n"
            "-    return 'world'\n"
            "+    return 'earth'\n"
        )
        result = apply_patch(patch)
        assert result["success"] is True
        assert len(result["files_modified"]) == 2

    def test_multiple_hunks_in_one_file(self, project_dir):
        (project_dir / "multi.py").write_text(
            "x = 1\ny = 2\nz = 3\n", encoding="utf-8"
        )
        patch = (
            "--- a/multi.py\n"
            "+++ b/multi.py\n"
            "@@\n"
            "-x = 1\n"
            "+x = 10\n"
            "@@\n"
            "-z = 3\n"
            "+z = 30\n"
        )
        result = apply_patch(patch)
        assert result["success"] is True
        content = (project_dir / "multi.py").read_text()
        assert "x = 10" in content
        assert "y = 2" in content
        assert "z = 30" in content


class TestApplyPatchCreate:
    def test_create_new_file(self, project_dir):
        patch = (
            "--- /dev/null\n"
            "+++ b/new_file.py\n"
            "@@\n"
            "+def new_func():\n"
            "+    return 42\n"
        )
        result = apply_patch(patch)
        assert result["success"] is True
        assert "new_file.py" in result["files_created"]
        content = (project_dir / "new_file.py").read_text()
        assert "def new_func():" in content

    def test_create_file_already_exists(self, project_dir):
        patch = (
            "--- /dev/null\n"
            "+++ b/hello.py\n"
            "@@\n"
            "+overwrite\n"
        )
        result = apply_patch(patch)
        assert result["success"] is False
        assert "already exists" in result["error"]


class TestApplyPatchDelete:
    def test_delete_file(self, project_dir):
        patch = (
            "--- a/world.py\n"
            "+++ /dev/null\n"
        )
        result = apply_patch(patch)
        assert result["success"] is True
        assert "world.py" in result["files_deleted"]
        assert not (project_dir / "world.py").exists()

    def test_delete_nonexistent_file(self, project_dir):
        patch = (
            "--- a/ghost.py\n"
            "+++ /dev/null\n"
        )
        result = apply_patch(patch)
        assert result["success"] is False
        assert "not found" in result["error"]


class TestApplyPatchValidation:
    def test_empty_patch(self, project_dir):
        result = apply_patch("")
        assert result["success"] is False
        assert "Empty" in result["error"]

    def test_no_operations_in_patch(self, project_dir):
        result = apply_patch("just some random text\nwith no diff markers\n")
        assert result["success"] is False
        assert "No valid operations" in result["error"]

    def test_bad_hunk_rejects_all(self, project_dir):
        """If one hunk fails validation, the entire patch is rejected."""
        original_hello = (project_dir / "hello.py").read_text()
        patch = (
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@\n"
            "-    return 'hello'\n"
            "+    return 'hi'\n"
            "--- a/world.py\n"
            "+++ b/world.py\n"
            "@@\n"
            "-NONEXISTENT LINE\n"
            "+something\n"
        )
        result = apply_patch(patch)
        assert result["success"] is False
        # Atomic: hello.py should be unchanged
        assert (project_dir / "hello.py").read_text() == original_hello

    def test_protected_file_rejected(self, project_dir):
        (project_dir / ".env").write_text("SECRET=123", encoding="utf-8")
        patch = (
            "--- a/.env\n"
            "+++ b/.env\n"
            "@@\n"
            "-SECRET=123\n"
            "+SECRET=456\n"
        )
        result = apply_patch(patch)
        assert result["success"] is False


class TestParsePatch:
    def test_parse_modify(self):
        patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@\n"
            "-old\n"
            "+new\n"
        )
        ops = _parse_patch(patch)
        assert len(ops) == 1
        assert ops[0]["type"] == "modify"
        assert ops[0]["path"] == "file.py"

    def test_parse_create(self):
        patch = (
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@\n"
            "+content\n"
        )
        ops = _parse_patch(patch)
        assert len(ops) == 1
        assert ops[0]["type"] == "create"

    def test_parse_delete(self):
        patch = (
            "--- a/old.py\n"
            "+++ /dev/null\n"
        )
        ops = _parse_patch(patch)
        assert len(ops) == 1
        assert ops[0]["type"] == "delete"

    def test_parse_context_lines(self):
        patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@\n"
            " context line\n"
            "-old line\n"
            "+new line\n"
            " another context\n"
        )
        ops = _parse_patch(patch)
        hunk = ops[0]["hunks"][0]
        assert "context line" in hunk["old"]
        assert "context line" in hunk["new"]
        assert "old line" in hunk["old"]
        assert "new line" in hunk["new"]


class TestApplyPatchSummary:
    def test_summary_includes_file_names(self, project_dir):
        patch = (
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@\n"
            "-    return 'hello'\n"
            "+    return 'hi'\n"
        )
        result = apply_patch(patch)
        assert result["success"] is True
        assert "hello.py" in result["summary"]
