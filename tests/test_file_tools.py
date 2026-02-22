"""Tests for file_tools module."""

import pytest

from radsim.file_tools import (
    clear_cwd_cache,
    is_protected_path,
    read_file,
    replace_in_file,
    validate_path,
    write_file,
)


@pytest.fixture(autouse=True)
def reset_cwd_cache():
    """Reset CWD cache before each test to handle chdir."""
    clear_cwd_cache()
    yield
    clear_cwd_cache()


class TestValidatePath:
    """Tests for path validation."""

    def test_empty_path_rejected(self):
        is_safe, path, error = validate_path("")
        assert is_safe is False
        assert "cannot be empty" in error

    def test_valid_path_accepted(self, tmp_path, monkeypatch):
        # Change to tmp_path directory
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.touch()

        is_safe, path, error = validate_path("test.txt")
        assert is_safe is True
        assert error is None

    def test_path_outside_project_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        is_safe, path, error = validate_path("/etc/passwd")
        assert is_safe is False
        assert "outside project" in error


class TestProtectedPath:
    """Tests for protected path detection."""

    def test_env_file_protected(self):
        is_protected, reason = is_protected_path(".env")
        assert is_protected is True

    def test_credentials_protected(self):
        is_protected, reason = is_protected_path("config/credentials.json")
        assert is_protected is True

    def test_ssh_key_protected(self):
        is_protected, reason = is_protected_path("id_rsa")
        assert is_protected is True

    def test_normal_file_not_protected(self):
        is_protected, reason = is_protected_path("src/main.py")
        assert is_protected is False


class TestReadFile:
    """Tests for read_file function."""

    def test_read_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = read_file("test.txt")
        assert result["success"] is True
        assert result["content"] == "Hello World"
        assert result["line_count"] == 1

    def test_read_nonexistent_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = read_file("does_not_exist.txt")
        assert result["success"] is False
        assert "not found" in result["error"]


class TestWriteFile:
    """Tests for write_file function."""

    def test_write_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = write_file("new_file.txt", "content")
        assert result["success"] is True
        assert (tmp_path / "new_file.txt").read_text() == "content"

    def test_write_creates_parent_dirs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = write_file("a/b/c/file.txt", "nested")
        assert result["success"] is True
        assert (tmp_path / "a/b/c/file.txt").read_text() == "nested"

    def test_write_protected_file_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = write_file(".env", "SECRETS")
        assert result["success"] is False
        assert "Protected" in result["error"]


class TestReplaceInFile:
    """Tests for replace_in_file function."""

    def test_replace_single_occurrence(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = replace_in_file("test.txt", "World", "Python")
        assert result["success"] is True
        assert test_file.read_text() == "Hello Python"

    def test_replace_multiple_requires_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo foo foo")

        result = replace_in_file("test.txt", "foo", "bar")
        assert result["success"] is False
        assert "Multiple" in result["error"]

    def test_replace_all_occurrences(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo foo foo")

        result = replace_in_file("test.txt", "foo", "bar", replace_all=True)
        assert result["success"] is True
        assert test_file.read_text() == "bar bar bar"
