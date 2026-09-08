"""Auto mode permits routine work and keeps approval boundaries explicit."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from radsim.agent_tool_handlers import AgentToolHandlersMixin
from radsim.request_classifier import classify_request


@pytest.fixture
def project(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX command classification cases")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sample.py").write_text("answer = 42\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / ".env").write_text("TOKEN=example\n")
    return tmp_path


@pytest.mark.parametrize("command", [
    "pwd", "echo hello", "ls -lah", "git status --short", "git diff --stat",
    "git log --oneline -n 5", "pytest -q", "python -m pytest tests -q",
    "python3 -m pytest tests -k 'works or passes' --maxfail=1",
    "ruff check .", "python -m ruff check .", "ruff format --check .",
    "cat sample.py", "head -n 20 sample.py", "tail --lines=10 sample.py",
    "rg -n answer sample.py", "grep -n answer sample.py", "rg --files",
    "git status && python -m pytest -q", "cat sample.py | head -n 5 sample.py",
])
def test_routine_commands_are_allowed(project, command):
    assert classify_request("run_shell_command", {"command": command}).decision == "allow"


@pytest.mark.parametrize("command", [
    "rm sample.py", "sudo ls", "git push", "git reset --hard",
    "custom-runner --all", "python script.py", "env pytest", "timeout 10 pytest",
    "git -c alias.status=oops status", "git diff --output=result.txt",
    "rg --pre custom-runner answer sample.py", "ruff format .", "ruff check --fix .",
    "pytest --basetemp=/tmp", "pytest -p custom_plugin", "cat .env",
    "cat *", "cat /etc/passwd", "rg answer .", "grep -R answer .",
    "cat sample.py > result.txt", "git status && custom-runner",
    "git status | custom-runner", "git status; custom-runner", "git status || custom-runner",
    "pytest -k", "python -m", "./pytest", "LC_ALL=C pytest",
    "pytest --override-ini=addopts=--basetemp=/tmp", "rg --hidden answer sample.py",
])
def test_unrecognised_or_sensitive_commands_ask(project, command):
    assert classify_request("run_shell_command", {"command": command}).decision != "allow"


@pytest.mark.parametrize("command", ["", "rm -rf /", "echo $(id)", "pwd\nid", "python -c 'print(1)'", "cat ../secret"])
def test_invalid_or_blocked_commands_stay_blocked(project, command):
    assert classify_request("run_shell_command", {"command": command}).decision == "block"


def test_policy_denial_overrides_routine_classification(project, monkeypatch):
    monkeypatch.setattr(
        "radsim.tools.command_policy.CommandPolicy.is_command_allowed",
        lambda self, command: (False, "Blocked by configured policy"),
    )
    result = classify_request("run_shell_command", {"command": "pytest -q"})
    assert result.decision == "block"


@pytest.mark.parametrize("target", [".env", "../outside.txt"])
def test_symlink_cannot_hide_sensitive_target(project, target):
    (project / "alias.txt").symlink_to(target)
    assert classify_request("run_shell_command", {"command": "cat alias.txt"}).decision == "ask"


def test_working_directory_is_used_for_secret_checks(project):
    directory = project / "tests"
    (directory / "sample.py").symlink_to(project / ".env")
    result = classify_request("run_shell_command", {"command": "cat sample.py", "working_dir": str(directory)})
    assert result.decision == "ask"


def test_outside_working_directory_requires_approval(project):
    result = classify_request("run_shell_command", {"command": "pytest", "working_dir": str(project.parent)})
    assert result.decision == "ask"


@pytest.mark.parametrize("test_path", [".env", "--basetemp=/tmp", "../tests"])
def test_custom_test_extra_path_is_checked(project, test_path):
    result = classify_request("run_tests", {"test_command": "pytest -q", "test_path": test_path})
    assert result.decision == "ask"


def make_handler(monkeypatch, auto=True):
    handler = AgentToolHandlersMixin()
    handler.config = SimpleNamespace(auto_confirm=auto)
    handler._session_approve_shell = False
    monkeypatch.setattr("radsim.agent_tool_handlers._confirmation_required", lambda kind: True)
    execution = Mock(return_value={"success": True, "returncode": 0})
    monkeypatch.setattr("radsim.agent_tool_handlers.execute_tool", execution)
    return handler, execution


@pytest.mark.parametrize("tool_name,arguments", [
    ("shell_command", {"command": "git status --short"}),
    ("run_tests", {"test_command": "python -m pytest -q", "test_path": "tests"}),
])
def test_auto_handlers_execute_without_prompt(project, monkeypatch, tool_name, arguments):
    handler, execution = make_handler(monkeypatch)
    prompt = Mock(side_effect=AssertionError("Routine auto request must not prompt"))
    monkeypatch.setattr("radsim.agent_tool_handlers.ask_confirmation", prompt)
    monkeypatch.setattr("radsim.agent_tool_handlers.confirm_action", prompt)
    assert getattr(handler, f"_handle_{tool_name}")(arguments)["success"]
    execution.assert_called_once()
    assert handler._session_approve_shell is False


def test_manual_mode_still_prompts(project, monkeypatch):
    handler, execution = make_handler(monkeypatch, auto=False)
    prompt = Mock(return_value="no")
    monkeypatch.setattr("radsim.agent_tool_handlers.ask_confirmation", prompt)
    assert not handler._handle_shell_command({"command": "git status"})["success"]
    prompt.assert_called_once()
    execution.assert_not_called()


def test_auto_toggle_is_checked_for_every_request(project, monkeypatch):
    handler, execution = make_handler(monkeypatch)
    prompt = Mock(return_value="no")
    monkeypatch.setattr("radsim.agent_tool_handlers.ask_confirmation", prompt)
    assert handler._handle_shell_command({"command": "git status"})["success"]
    handler.config.auto_confirm = False
    assert not handler._handle_shell_command({"command": "git status"})["success"]
    execution.assert_called_once()
    prompt.assert_called_once()


def test_classifier_failure_prompts_without_executing(project, monkeypatch):
    handler, execution = make_handler(monkeypatch)
    monkeypatch.setattr("radsim.agent_tool_handlers.classify_request", Mock(side_effect=RuntimeError))
    monkeypatch.setattr("radsim.agent_tool_handlers.ask_confirmation", Mock(return_value="no"))
    assert not handler._handle_shell_command({"command": "git status"})["success"]
    execution.assert_not_called()


def test_protected_classifier_cannot_rewrite_itself():
    import radsim.request_classifier
    from radsim.safety import is_core_policy_path

    assert is_core_policy_path(radsim.request_classifier.__file__)[0]


def test_windows_shell_falls_back_to_confirmation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("radsim.request_classifier.os", SimpleNamespace(name="nt"))
    assert classify_request("run_shell_command", {"command": "git status"}).decision == "ask"
