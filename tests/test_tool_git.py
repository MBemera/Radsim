"""Tests for radsim/tools/git.py

One test, one thing. Mock subprocess.run since git operations
should not depend on a real repository.
"""

from unittest.mock import MagicMock, patch

from radsim.tools.git import git_add, git_diff, git_status

# =============================================================================
# git_status tests
# =============================================================================


class TestGitStatus:
    """Tests for git_status function."""

    @patch("radsim.tools.shell.subprocess.run")
    def test_clean_repository(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="## main\n",
            stderr="",
        )

        result = git_status()

        assert result["success"] is True
        assert "main" in result["stdout"]

    @patch("radsim.tools.shell.subprocess.run")
    def test_dirty_repository_with_changes(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="## main\n M src/app.py\n?? new_file.txt\n",
            stderr="",
        )

        result = git_status()

        assert result["success"] is True
        assert "app.py" in result["stdout"]
        assert "new_file.txt" in result["stdout"]

    @patch("radsim.tools.shell.subprocess.run")
    def test_not_a_git_repo(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository\n",
        )

        result = git_status()

        assert result["success"] is False
        assert result["returncode"] == 128


# =============================================================================
# git_add tests
# =============================================================================


class TestGitAdd:
    """Tests for git_add function."""

    @patch("radsim.tools.shell.subprocess.run")
    def test_add_specific_files(self, mock_run):
        # First call: git add, second call: git diff --cached --name-only
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="file1.py\nfile2.py\n", stderr=""),
        ]

        result = git_add(file_paths=["file1.py", "file2.py"])

        assert result["success"] is True
        assert "file1.py" in result["staged_files"]
        assert "file2.py" in result["staged_files"]

    @patch("radsim.tools.shell.subprocess.run")
    def test_add_all_files(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="everything.py\n", stderr=""),
        ]

        result = git_add(all_files=True)

        assert result["success"] is True
        assert "git add -A" in result["command"]

    def test_add_no_files_and_no_all_flag_returns_error(self):
        result = git_add(file_paths=None, all_files=False)

        assert result["success"] is False
        assert "specify" in result["error"].lower()

    @patch("radsim.tools.shell.subprocess.run")
    def test_add_fails_on_git_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository\n",
        )

        result = git_add(file_paths=["file.py"])

        assert result["success"] is False
        assert "fatal" in result["error"].lower()

    @patch("radsim.tools.shell.subprocess.run")
    def test_add_single_string_path_converted_to_list(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="single.py\n", stderr=""),
        ]

        result = git_add(file_paths="single.py")

        assert result["success"] is True
        assert "single.py" in result["staged_files"]


# =============================================================================
# git_diff tests
# =============================================================================


class TestGitDiff:
    """Tests for git_diff function."""

    @patch("radsim.tools.shell.subprocess.run")
    def test_diff_with_changes(self, mock_run):
        diff_output = (
            "diff --git a/file.py b/file.py\n"
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-old line\n"
            "+new line\n"
        )
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=diff_output,
            stderr="",
        )

        result = git_diff()

        assert result["success"] is True
        assert "-old line" in result["stdout"]
        assert "+new line" in result["stdout"]

    @patch("radsim.tools.shell.subprocess.run")
    def test_diff_no_changes(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )

        result = git_diff()

        assert result["success"] is True
        assert result["stdout"] == ""

    @patch("radsim.tools.shell.subprocess.run")
    def test_diff_staged_flag(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="staged changes\n",
            stderr="",
        )

        result = git_diff(staged=True)

        assert result["success"] is True
        # Verify --staged was included in the command
        called_command = mock_run.call_args[0][0]
        command_string = " ".join(called_command)
        assert "--staged" in command_string

    @patch("radsim.tools.shell.subprocess.run")
    def test_diff_specific_file(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="file-specific diff\n",
            stderr="",
        )

        result = git_diff(file_path="specific.py")

        assert result["success"] is True
        called_command = mock_run.call_args[0][0]
        command_string = " ".join(called_command)
        assert "specific.py" in command_string
