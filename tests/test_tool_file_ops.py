"""Tests for radsim/tools/file_ops.py

One test, one thing. Clear names, obvious assertions.
"""


from radsim.tools.file_ops import (
    delete_file,
    read_file,
    rename_file,
    replace_in_file,
    write_file,
)

# =============================================================================
# read_file tests
# =============================================================================


class TestReadFile:
    """Tests for read_file function."""

    def test_read_existing_file_returns_content(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "hello.txt"
        test_file.write_text("Hello World")

        result = read_file("hello.txt")

        assert result["success"] is True
        assert result["content"] == "Hello World"
        assert result["line_count"] == 1

    def test_read_missing_file_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = read_file("nonexistent.txt")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_read_protected_env_file_still_readable(self, tmp_path, monkeypatch):
        """read_file does NOT check protected patterns -- only write/replace do."""
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / "config.txt"
        env_file.write_text("DATA=value")

        result = read_file("config.txt")

        assert result["success"] is True
        assert "DATA=value" in result["content"]

    def test_read_file_outside_project_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = read_file("/etc/passwd")

        assert result["success"] is False
        assert "outside project" in result["error"].lower()

    def test_read_large_file_rejected(self, tmp_path, monkeypatch):
        """Files exceeding MAX_FILE_SIZE (100KB) are rejected."""
        monkeypatch.chdir(tmp_path)
        large_file = tmp_path / "large.txt"
        large_file.write_text("x" * 200_000)

        result = read_file("large.txt")

        assert result["success"] is False
        assert "too large" in result["error"].lower()

    def test_read_file_content_truncated_at_max_display_size(self, tmp_path, monkeypatch):
        """Content exceeding MAX_TRUNCATED_SIZE (20KB) is truncated."""
        monkeypatch.chdir(tmp_path)
        # Create file just under MAX_FILE_SIZE but over MAX_TRUNCATED_SIZE
        content = "a" * 50_000
        big_file = tmp_path / "big.txt"
        big_file.write_text(content)

        result = read_file("big.txt")

        assert result["success"] is True
        assert "Truncated" in result["content"]
        assert len(result["content"]) < 50_000

    def test_read_file_with_offset_and_limit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "lines.txt"
        test_file.write_text("line0\nline1\nline2\nline3\nline4")

        result = read_file("lines.txt", offset=1, limit=2)

        assert result["success"] is True
        assert result["content"] == "line1\nline2"
        assert result["offset"] == 1
        assert result["limit"] == 2


# =============================================================================
# write_file tests
# =============================================================================


class TestWriteFile:
    """Tests for write_file function."""

    def test_write_new_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = write_file("new.txt", "hello")

        assert result["success"] is True
        assert result["is_new_file"] is True
        assert (tmp_path / "new.txt").read_text() == "hello"

    def test_write_overwrites_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        existing = tmp_path / "existing.txt"
        existing.write_text("old content")

        result = write_file("existing.txt", "new content", show_diff=False)

        assert result["success"] is True
        assert result["is_new_file"] is False
        assert existing.read_text() == "new content"

    def test_write_creates_parent_directories(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = write_file("deep/nested/dir/file.txt", "nested content")

        assert result["success"] is True
        assert (tmp_path / "deep/nested/dir/file.txt").read_text() == "nested content"

    def test_write_protected_env_file_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = write_file(".env", "SECRET=bad")

        assert result["success"] is False
        assert "cannot write" in result["error"].lower()

    def test_write_protected_credentials_file_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = write_file("credentials.json", "{}")

        assert result["success"] is False
        assert "cannot write" in result["error"].lower()

    def test_write_outside_project_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = write_file("/tmp/outside.txt", "data")

        assert result["success"] is False
        assert "outside project" in result["error"].lower()

    def test_write_returns_bytes_written(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = write_file("size.txt", "abc")

        assert result["success"] is True
        assert result["bytes_written"] == 3


# =============================================================================
# replace_in_file tests
# =============================================================================


class TestReplaceInFile:
    """Tests for replace_in_file function."""

    def test_replace_single_occurrence(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = replace_in_file("test.txt", "World", "Python", show_diff=False)

        assert result["success"] is True
        assert result["replacements_made"] == 1
        assert test_file.read_text() == "Hello Python"

    def test_replace_all_occurrences(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo bar foo baz foo")

        result = replace_in_file(
            "test.txt", "foo", "qux", replace_all=True, show_diff=False
        )

        assert result["success"] is True
        assert result["replacements_made"] == 3
        assert test_file.read_text() == "qux bar qux baz qux"

    def test_replace_multiple_without_flag_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo foo foo")

        result = replace_in_file("test.txt", "foo", "bar", show_diff=False)

        assert result["success"] is False
        assert "multiple" in result["error"].lower()

    def test_replace_pattern_not_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = replace_in_file("test.txt", "MISSING", "replacement", show_diff=False)

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_replace_in_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = replace_in_file("nonexistent.txt", "a", "b", show_diff=False)

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_replace_in_protected_file_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value")

        result = replace_in_file(".env", "KEY", "NEW_KEY", show_diff=False)

        assert result["success"] is False
        assert "cannot modify" in result["error"].lower()


# =============================================================================
# delete_file tests
# =============================================================================


class TestDeleteFile:
    """Tests for delete_file function."""

    def test_delete_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "doomed.txt"
        target.write_text("bye")

        result = delete_file("doomed.txt")

        assert result["success"] is True
        assert not target.exists()

    def test_delete_missing_file_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = delete_file("ghost.txt")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_delete_outside_project_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = delete_file("/etc/important")

        assert result["success"] is False
        assert "outside project" in result["error"].lower()


# =============================================================================
# rename_file tests
# =============================================================================


class TestRenameFile:
    """Tests for rename_file function."""

    def test_rename_basic(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        old = tmp_path / "old.txt"
        old.write_text("content")

        result = rename_file("old.txt", "new.txt")

        assert result["success"] is True
        assert not old.exists()
        assert (tmp_path / "new.txt").read_text() == "content"

    def test_rename_cross_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        old = tmp_path / "old.txt"
        old.write_text("moved")

        result = rename_file("old.txt", "subdir/moved.txt")

        assert result["success"] is True
        assert (tmp_path / "subdir/moved.txt").read_text() == "moved"

    def test_rename_target_exists_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        source = tmp_path / "source.txt"
        source.write_text("source")
        dest = tmp_path / "dest.txt"
        dest.write_text("destination")

        result = rename_file("source.txt", "dest.txt")

        assert result["success"] is False
        assert "already exists" in result["error"].lower()

    def test_rename_missing_source_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = rename_file("nonexistent.txt", "new.txt")

        assert result["success"] is False
        assert "not found" in result["error"].lower()
