"""Synthetic regressions from the nested-repository and usage incident."""

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from radsim.commands_core import CoreCommandHandlersMixin
from radsim.request_classifier import classify_request
from radsim.tools import execute_tool
from radsim.tools.git import validate_stage_paths


def init_repository(path):
    path.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_nested_git_tools_preserve_outer_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_repository(tmp_path)
    nested = tmp_path / "nested"
    init_repository(nested)
    (tmp_path / "personal.txt").write_text("synthetic outer fixture")
    (nested / "code.py").write_text("answer = 42\n")
    result = execute_tool("git_add", {"working_dir": "nested", "file_paths": ["code.py"]})
    assert result["success"], result
    assert result["staged_files"] == ["code.py"]
    outer = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True)
    assert outer == ""
    assert validate_stage_paths(["code.py"], "nested")
    for paths in (["nested"], ["nested/code.py"], ["."], ["*.txt"], [":(glob)**"]):
        assert not validate_stage_paths(paths)
    nested_status = execute_tool("git_status", {"working_dir": "nested"})
    assert "code.py" in nested_status["stdout"]
    assert "personal.txt" not in nested_status["stdout"]


def test_git_explicit_directory_cannot_escape(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    init_repository(workspace)
    monkeypatch.chdir(workspace)
    result = execute_tool("git_add", {"working_dir": str(tmp_path), "file_paths": ["x"]})
    assert not result["success"]


@pytest.mark.parametrize(
    "command",
    [
        "git -C nested status --short --branch",
        "git -C nested rev-parse --show-toplevel",
        "git -C nested show --raw HEAD",
        "git -C nested diff --cached --name-status",
    ],
)
def test_classifier_allows_scoped_git_metadata(command, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "nested").mkdir()
    assert classify_request("run_shell_command", {"command": command}).decision == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "git -C / status",
        "git -C nested -c core.pager=evil log",
        "git -C nested reset --hard",
        "git -C nested add -A",
        "git -C nested show HEAD:.env",
        "git -C nested show HEAD",
        "git -C nested show --output=leak --raw HEAD",
    ],
)
def test_classifier_does_not_widen_git_mutation_or_content_access(command, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "nested").mkdir()
    assert classify_request("run_shell_command", {"command": command}).decision != "allow"


def test_explicit_github_glob_finds_workflow_but_hides_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "test.yml").write_text("name: synthetic\n")
    (tmp_path / ".env").write_text("synthetic fixture only")
    result = execute_tool("glob_files", {"pattern": ".github/**/*.yml"})
    assert result["matches"] == [".github/workflows/test.yml"]
    assert execute_tool("glob_files", {"pattern": ".env"})["matches"] == []


def test_openrouter_usage_has_account_browser_only_on_request(monkeypatch, capsys):
    opener = Mock(return_value=True)
    monkeypatch.setattr("webbrowser.open_new_tab", opener)
    agent = SimpleNamespace(
        config=SimpleNamespace(provider="openrouter", model="model"),
        usage_stats={"reported_cost_usd": 0.125, "reported_cost_requests": 1, "request_count": 2},
    )
    handler = CoreCommandHandlersMixin()
    handler._cmd_usage(agent)
    output = capsys.readouterr().out
    assert "$0.1250" in output and "partial" in output
    assert "Est. cost:" not in output and "account-wide" in output
    opener.assert_not_called()
    handler._cmd_usage(agent, ["browser"])
    opener.assert_called_once_with("https://openrouter.ai/activity")


def test_native_writes_cannot_change_radsim_settings(tmp_path, monkeypatch):
    from pathlib import Path

    from radsim.tools.validation import is_protected_path

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert is_protected_path(tmp_path / ".radsim" / "agent_config.json")[0]
    assert not is_protected_path(tmp_path / "project" / "agent_config.json")[0]


def test_requested_unavailable_sandbox_refuses_execution(monkeypatch, tmp_path):
    from radsim.tools import sandbox
    from radsim.tools.shell import run_shell_command

    monkeypatch.setattr(sandbox, "_auto_mode_enabled", True)
    monkeypatch.setattr(sandbox, "sandbox_requested", lambda: True)
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: False)
    result = run_shell_command("echo safe", working_dir=str(tmp_path))
    assert not result["success"] and "BLOCKED:" in result["error"]


def test_auto_commit_refuses_preexisting_staged_files(tmp_path, monkeypatch):
    from radsim.tools.git import validate_commit_index

    monkeypatch.chdir(tmp_path)
    init_repository(tmp_path)
    for name in ("intended.py", "unrelated.txt"):
        (tmp_path / name).write_text("synthetic fixture\n")
    execute_tool("git_add", {"file_paths": ["intended.py", "unrelated.txt"]})
    allowed = {str(tmp_path / "intended.py")}
    assert not validate_commit_index(str(tmp_path), allowed)
    allowed.add(str(tmp_path / "unrelated.txt"))
    assert validate_commit_index(str(tmp_path), allowed)


def test_auto_stash_mutations_never_execute(monkeypatch):
    from radsim.agent import RadSimAgent

    agent = object.__new__(RadSimAgent)
    agent.config = SimpleNamespace(auto_confirm=True)
    executor = Mock()
    monkeypatch.setattr("radsim.agent_tool_handlers.execute_tool", executor)
    for action in ("push", "pop", "drop"):
        assert agent._handle_git_stash({"action": action})["blocked"]
    executor.assert_not_called()
