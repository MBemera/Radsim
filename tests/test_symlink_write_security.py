"""Security regression tests for symlink-safe write controls (R-03).

validate_path resolved the path but is_protected_path checked the original
display string, so a repository-controlled symlink (safe.txt -> .env) passed
the protected check and the write landed on .env. These tests prove writes,
edits, multi-edits, and patches all refuse to follow a symlink and evaluate
protected patterns against the canonical resolved target.
"""

import pytest

from radsim.patch import apply_patch
from radsim.tools.file_ops import multi_edit, replace_in_file, write_file
from radsim.tools.validation import clear_path_validation_cache, contains_symlink


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clear_path_validation_cache()
    return tmp_path


def _make_env_symlink(project, link_name="safe.txt"):
    secret = project / ".env"
    secret.write_text("ANTHROPIC_API_KEY=sk-must-not-be-overwritten")
    link = project / link_name
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    return secret, link


class TestContainsSymlink:
    def test_detects_symlinked_target(self, project):
        _secret, _link = _make_env_symlink(project)
        has_symlink, offending = contains_symlink("safe.txt")
        assert has_symlink is True
        assert offending.endswith("safe.txt")

    def test_detects_symlinked_parent(self, project):
        (project / "realdir").mkdir()
        try:
            (project / "linkdir").symlink_to(project / "realdir")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")
        has_symlink, _ = contains_symlink("linkdir/file.txt")
        assert has_symlink is True

    def test_plain_path_is_not_symlink(self, project):
        has_symlink, _ = contains_symlink("src/module.py")
        assert has_symlink is False


class TestWriteThroughSymlink:
    def test_write_file_refuses_symlink_to_env(self, project):
        secret, _link = _make_env_symlink(project)
        result = write_file("safe.txt", "pwned = True")
        assert result["success"] is False
        assert "symlink" in result["error"].lower() or "protected" in result["error"].lower()
        # The secret must be untouched.
        assert secret.read_text() == "ANTHROPIC_API_KEY=sk-must-not-be-overwritten"

    def test_replace_in_file_refuses_symlink(self, project):
        _secret, _link = _make_env_symlink(project)
        result = replace_in_file("safe.txt", "ANTHROPIC_API_KEY", "x")
        assert result["success"] is False

    def test_multi_edit_refuses_symlink(self, project):
        _secret, _link = _make_env_symlink(project)
        result = multi_edit("safe.txt", [{"old_string": "ANTHROPIC_API_KEY", "new_string": "x"}])
        assert result["success"] is False

    def test_apply_patch_refuses_symlink(self, project):
        secret, _link = _make_env_symlink(project)
        patch = (
            "--- a/safe.txt\n"
            "+++ b/safe.txt\n"
            "@@\n"
            "-ANTHROPIC_API_KEY=sk-must-not-be-overwritten\n"
            "+ANTHROPIC_API_KEY=stolen\n"
        )
        result = apply_patch(patch)
        assert result["success"] is False
        assert secret.read_text() == "ANTHROPIC_API_KEY=sk-must-not-be-overwritten"


class TestDirectProtectedWrite:
    def test_write_file_refuses_direct_env(self, project):
        result = write_file(".env", "SECRET=1")
        assert result["success"] is False
        assert "protected" in result["error"].lower() or "cannot write" in result["error"].lower()


class TestNormalWritesStillWork:
    def test_plain_write_succeeds(self, project):
        result = write_file("hello.py", "print('hi')")
        assert result["success"] is True
        assert (project / "hello.py").read_text() == "print('hi')"

    def test_plain_edit_succeeds(self, project):
        (project / "a.txt").write_text("one two three")
        result = replace_in_file("a.txt", "two", "TWO")
        assert result["success"] is True
        assert (project / "a.txt").read_text() == "one TWO three"
