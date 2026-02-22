"""Tests for radsim/tools/shell.py

One test, one thing. Mock subprocess.run for shell tests.
"""

from unittest.mock import MagicMock, patch

from radsim.tools.shell import run_shell_command


class TestRunShellCommand:
    """Tests for run_shell_command function."""

    @patch("radsim.tools.shell.subprocess.run")
    def test_simple_echo_returns_stdout(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="hello world\n",
            stderr="",
        )

        result = run_shell_command("echo hello world")

        assert result["success"] is True
        assert "hello world" in result["stdout"]
        assert result["returncode"] == 0

    @patch("radsim.tools.shell.subprocess.run")
    def test_nonzero_exit_code_reports_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="command failed\n",
        )

        result = run_shell_command("false")

        assert result["success"] is False
        assert result["returncode"] == 1
        assert "command failed" in result["stderr"]

    @patch("radsim.tools.shell.subprocess.run")
    def test_timeout_returns_error(self, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 999", timeout=5)

        result = run_shell_command("sleep 999", timeout=5)

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    @patch("radsim.tools.shell.subprocess.run")
    def test_output_capture_includes_stderr(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="normal output",
            stderr="warning message",
        )

        result = run_shell_command("some_command")

        assert result["stdout"] == "normal output"
        assert result["stderr"] == "warning message"

    @patch("radsim.tools.shell.subprocess.run")
    def test_large_stdout_is_truncated(self, mock_run):
        large_output = "x" * 100_000
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=large_output,
            stderr="",
        )

        result = run_shell_command("big_output_cmd")

        assert result["success"] is True
        assert "truncated" in result["stdout"].lower()
        assert len(result["stdout"]) < 100_000

    def test_empty_command_rejected(self):
        result = run_shell_command("")

        assert result["success"] is False
        assert "empty" in result["error"].lower()

    @patch("radsim.tools.shell.subprocess.run")
    def test_working_dir_is_passed_to_subprocess(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )

        run_shell_command("ls", working_dir="/tmp")

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["cwd"] == "/tmp"


class TestDangerousCommandValidation:
    """Tests that commands with path traversal are blocked."""

    def test_path_traversal_in_argument_rejected(self):
        result = run_shell_command("cat ../../etc/passwd")

        assert result["success"] is False
        assert "traversal" in result["error"].lower()

    @patch("radsim.tools.shell.subprocess.run")
    def test_normal_command_is_allowed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="file.txt",
            stderr="",
        )

        result = run_shell_command("ls -la")

        assert result["success"] is True
