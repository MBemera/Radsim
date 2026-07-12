"""Tests for radsim/tools/shell.py

One test, one thing. Mock the _execute seam for shell tests.
"""

import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from radsim.tools.constants import MAX_OUTPUT_SIZE
from radsim.tools.environment import build_child_environment
from radsim.tools.shell import (
    _execute,
    _kill_windows_process_tree,
    quote_shell_argument,
    run_process,
    run_shell_command,
)


class TestRunShellCommand:
    """Tests for run_shell_command function."""

    @patch("radsim.tools.shell._execute")
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

    @patch("radsim.tools.shell._execute")
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

    @patch("radsim.tools.shell._execute")
    def test_timeout_returns_error(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 999", timeout=5)

        result = run_shell_command("sleep 999", timeout=5)

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    @patch("radsim.tools.shell._execute")
    def test_output_capture_includes_stderr(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="normal output",
            stderr="warning message",
        )

        result = run_shell_command("some_command")

        assert result["stdout"] == "normal output"
        assert result["stderr"] == "warning message"

    @patch("radsim.tools.shell._execute")
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

    @patch("radsim.tools.shell._execute")
    def test_working_dir_is_passed_to_subprocess(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )

        run_shell_command("ls", working_dir=tmp_path)

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["cwd"] == str(tmp_path.resolve())


class TestDangerousCommandValidation:
    """Tests that commands with path traversal are blocked."""

    def test_path_traversal_in_argument_rejected(self):
        result = run_shell_command("cat ../../etc/passwd")

        assert result["success"] is False
        assert "traversal" in result["error"].lower()

    @patch("radsim.tools.shell._execute")
    def test_normal_command_is_allowed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="file.txt",
            stderr="",
        )

        result = run_shell_command("ls -la")

        assert result["success"] is True


class TestRunnerHardening:
    """The runner isolates the environment, validates cwd, and isolates signals."""

    def test_missing_working_dir_is_rejected(self, tmp_path):
        result = run_shell_command("ls", working_dir=tmp_path / "missing")
        assert result["success"] is False
        assert "does not exist" in result["error"].lower()

    @patch("radsim.tools.shell._execute")
    def test_secrets_are_stripped_from_child_env(self, mock_run, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
        monkeypatch.setenv("PATH", "/usr/bin")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        run_shell_command("ls")

        child_env = mock_run.call_args.kwargs["env"]
        assert "ANTHROPIC_API_KEY" not in child_env
        assert "PATH" in child_env

    def test_git_execution_overrides_are_stripped(self):
        base_env = {
            "PATH": "/usr/bin",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "alias.status",
            "GIT_CONFIG_VALUE_0": "!payload",
            "GIT_CONFIG_GLOBAL": "/tmp/hostile-gitconfig",
            "GIT_DIFF_OPTS": "--output=/tmp/leak",
            "GIT_DIR": "/tmp/other-repository",
            "GIT_EXEC_PATH": "/tmp/hostile-git-core",
            "GIT_EXTERNAL_DIFF": "/tmp/payload",
            "GIT_SSH_COMMAND": "/tmp/payload",
            "GIT_TRACE_PACKET": "/tmp/leak",
            "GIT_WORK_TREE": "/tmp/other-worktree",
            "GIT_OPTIONAL_LOCKS": "0",
        }

        child_env = build_child_environment(base_env)

        assert child_env == {"PATH": "/usr/bin", "GIT_OPTIONAL_LOCKS": "0"}

    @patch("radsim.tools.shell.subprocess.Popen")
    def test_child_standard_input_is_disabled(self, mock_popen):
        process = mock_popen.return_value
        process.stdout.read.return_value = b""
        process.stderr.read.return_value = b""
        process.wait.return_value = 0
        process.returncode = 0

        _execute([sys.executable, "--version"], timeout=5, cwd=".", env={})

        assert mock_popen.call_args.kwargs["stdin"] == subprocess.DEVNULL

    @pytest.mark.skipif(os.name == "nt", reason="POSIX session behavior")
    @patch("radsim.tools.shell.subprocess.Popen")
    def test_child_runs_in_new_session_on_posix(self, mock_popen):
        process = mock_popen.return_value
        process.stdout.read.return_value = b""
        process.stderr.read.return_value = b""
        process.wait.return_value = 0
        process.returncode = 0

        _execute(["bash", "-c", "ls"], timeout=5, cwd=".", env={})

        assert mock_popen.call_args.kwargs["start_new_session"] is True

    @pytest.mark.skipif(os.name == "nt", reason="POSIX process-group behavior")
    @patch("radsim.tools.shell.os.killpg")
    @patch("radsim.tools.shell.subprocess.Popen")
    def test_timeout_kills_whole_process_group(self, mock_popen, mock_killpg):
        process = mock_popen.return_value
        process.pid = 4242
        process.stdout.read.return_value = b""
        process.stderr.read.return_value = b""
        process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="sleep 999", timeout=1),
            0,
        ]

        with pytest.raises(subprocess.TimeoutExpired):
            _execute(["bash", "-c", "sleep 999"], timeout=1, cwd=".", env={})

        mock_killpg.assert_called_once_with(4242, signal.SIGKILL)

    def test_real_output_is_bounded_while_process_runs(self):
        result = run_process([sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000)"])

        assert result["success"] is True
        assert len(result["stdout"]) < 100_000
        assert len(result["stdout"]) <= MAX_OUTPUT_SIZE + 100
        assert "truncated" in result["stdout"].lower()

    def test_invalid_timeout_is_rejected_before_execution(self):
        result = run_process([sys.executable, "--version"], timeout=float("inf"))

        assert result["success"] is False
        assert "timeout" in result["error"].lower()

    @pytest.mark.skipif(
        os.name == "nt" or shutil.which("bash") is None,
        reason="Bash startup-hook behavior",
    )
    def test_bash_env_hook_is_not_executed(self, tmp_path, monkeypatch):
        marker = tmp_path / "injected-marker"
        hook = tmp_path / "hook.sh"
        hook.write_text(f"touch {shlex.quote(str(marker))}\n")
        monkeypatch.setenv("BASH_ENV", str(hook))

        result = run_shell_command("printf safe")

        assert result["success"] is True
        assert result["stdout"] == "safe"
        assert not marker.exists()

    def test_timeout_kills_descendant_before_it_can_write(self, tmp_path):
        marker = tmp_path / "descendant-marker"
        child_code = (
            "import pathlib,time; "
            f"time.sleep(1); pathlib.Path({str(marker)!r}).write_text('survived')"
        )
        parent_code = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(5)"
        )

        result = run_process([sys.executable, "-c", parent_code], timeout=0.1)
        time.sleep(1.2)

        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        assert not marker.exists()

    @patch("radsim.tools.shell.os.name", "nt")
    @patch("radsim.tools.shell.subprocess.Popen")
    def test_windows_child_uses_new_process_group(self, mock_popen):
        process = mock_popen.return_value
        process.stdout.read.return_value = b""
        process.stderr.read.return_value = b""
        process.wait.return_value = 0
        process.returncode = 0

        _execute(["powershell", "-Command", "echo ok"], timeout=5, cwd=".", env={})

        expected_flag = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        assert mock_popen.call_args.kwargs["creationflags"] == expected_flag

    @patch("radsim.tools.shell.subprocess.run")
    def test_failed_taskkill_falls_back_to_direct_kill(self, mock_run):
        process = MagicMock(pid=4242)
        mock_run.return_value = subprocess.CompletedProcess([], 1)

        _kill_windows_process_tree(process)

        process.kill.assert_called_once_with()


class TestShellArgumentQuoting:
    @pytest.mark.skipif(
        os.name == "nt" or shutil.which("bash") is None,
        reason="POSIX shell quoting behavior",
    )
    def test_posix_quote_round_trips_apostrophe(self):
        quoted = quote_shell_argument("test's file.py")
        assert (
            subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", f"printf %s {quoted}"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            == "test's file.py"
        )

    @patch("radsim.tools.shell.os.name", "nt")
    def test_powershell_quote_escapes_apostrophe(self):
        assert quote_shell_argument("test's file.py") == "'test''s file.py'"
