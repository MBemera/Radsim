"""Shell policy on Windows, using the real Windows PowerShell parser.

Commands run in Windows PowerShell there, so PowerShell syntax must pass
and machine-wrecking commands must still be refused.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from radsim.request_classifier import classify_request
from radsim.tools.command_analysis import is_destructive_shell_command
from radsim.tools.command_policy import CommandPolicy
from radsim.tools.constants import DESTRUCTIVE_COMMANDS
from radsim.tools.powershell_parser import parse_powershell, windows_powershell_executable
from radsim.tools.shell import run_shell_command, shell_arguments
from radsim.tools.testing import run_tests
from radsim.tools.validation import validate_shell_command

pytestmark = pytest.mark.skipif(os.name != "nt", reason="needs Windows PowerShell")


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# sample\nanswer = 42\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / ".env").write_text("TOKEN=example\n")
    return tmp_path


class FakeConfigManager:
    def __init__(self, mode="blocklist", whitelist=None):
        self.values = {
            "shell_commands.mode": mode,
            "shell_commands.whitelist": whitelist or [],
            "shell_commands.blocklist": [],
            "shell_commands.custom_destructive": [],
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


class TestParser:
    def test_parser_sees_through_escapes_and_aliases(self):
        parsed = parse_powershell("gci C:\\ | Re`move-Item -Recurse")
        assert [command.name for command in parsed.commands] == ["gci", "Remove-Item"]
        assert parsed.commands[0].alias_of == "Get-ChildItem"
        assert parsed.commands[1].pipeline_index == 1

    def test_parser_reports_variables_and_arrays(self):
        parsed = parse_powershell('Remove-Item "$env:TEMP\\x", build -Force')
        argument = parsed.commands[0].arguments[0]
        assert argument.value is None
        assert argument.items is None
        plain_list = parse_powershell("Remove-Item a, b").commands[0].arguments[0]
        assert plain_list.items == ("a", "b")


@pytest.mark.parametrize(
    "command",
    [
        "$env:PATH -split ';'",
        '& "C:\\Program Files\\Git\\cmd\\git.exe" status',
        "foreach ($file in Get-ChildItem *.md) { $file.Name }",
        "(Get-Item README.md).Length",
        "Get-ChildItem | Where-Object { $_.Length -gt 0 } | Select-Object -First 3",
        'Write-Output "Home is $env:USERPROFILE"',
        "if (Test-Path README.md) { Get-Content README.md -TotalCount 1 }",
        "git log --oneline -n 5; git status --short",
        "Get-ChildItem 2>$null",
    ],
)
def test_ordinary_powershell_is_accepted(project, command):
    assert validate_shell_command(command) == (True, None)


@pytest.mark.parametrize(
    "command,expected",
    [
        ("Remove-Item C:\\ -Recurse -Force", "catastrophic"),
        ("rm -rf /", "catastrophic"),
        ("Re`move-Item $env:USERPROFILE -Recurse", "catastrophic"),
        ('Remove-Item "$env:NOT_A_REAL_VARIABLE_XYZ\\*" -Recurse -Force', "catastrophic"),
        ("Remove-Item $target -Recurse -Force", "literal path"),
        ("Get-ChildItem C:\\ | Remove-Item -Recurse -Force", "catastrophic"),
        ("Format-Volume -DriveLetter C", "catastrophic"),
        ("format C: /q", "catastrophic"),
        ("Start-Process diskpart", "catastrophic"),
        ("bcdedit /set safeboot minimal", "catastrophic"),
        ("vssadmin delete shadows /all", "catastrophic"),
        ("reg delete HKLM\\SOFTWARE\\Something /f", "catastrophic"),
        ("takeown /f C:\\Windows /r", "catastrophic"),
        ('iex "Remove-Item C:\\ -Recurse"', "Invoke-Expression"),
        ("Set-Alias ls Format-Volume", "alias"),
        ("& $cmd", "literally"),
        ("cmd /c dir", "Nested shells"),
        ("powershell -EncodedCommand AAAA", "Nested shells"),
        ("python -c 'print(1)'", "Nested shells"),
        ("& ([scriptblock]::Create('Get-Date'))", "script blocks"),
        ("Get-Content ..\\secret.txt", "traversal"),
        ("git status && git diff", "could not parse"),
        ("Get-Date\nGet-Date", "Newlines"),
    ],
)
def test_dangerous_or_hidden_commands_are_refused(project, command, expected):
    valid, reason = validate_shell_command(command)
    assert valid is False
    assert expected.lower() in reason.lower()


@pytest.mark.parametrize(
    "command",
    [
        r"Set-Location C:\Windows; Remove-Item System32 -Recurse -Force",
        r"cd C:\Windows; Remove-Item System32 -Recurse -Force",
        r"Push-Location C:\Windows; Move-Item System32 build",
        r"Pop-Location; Remove-Item build -Recurse",
        r'$env:TEMP = "C:\Windows"; Remove-Item "$env:TEMP\System32" -Recurse',
        r'${env:TEMP} = "C:\Windows"; Remove-Item "$env:TEMP\System32" -Recurse',
        r'$env:TEMP, $other = "C:\Windows", "x"; Remove-Item "$env:TEMP\System32" -Recurse',
        r"Set-Item Env:TEMP C:\Windows; Remove-Item System32 -Recurse",
        r"$provider_path = 'Env:TEMP'; Set-Item $provider_path C:\Windows; Remove-Item System32 -Recurse",
        r"[Environment]::SetEnvironmentVariable('TEMP', 'C:\Windows'); Remove-Item System32 -Recurse",
        r"[Environment]::CurrentDirectory = 'C:\Windows'; Remove-Item System32 -Recurse",
        r"New-PSDrive -Name X -PSProvider FileSystem -Root C:\Windows; Remove-Item X:\System32 -Recurse",
    ],
)
def test_context_changes_cannot_hide_protected_operations(project, command):
    policy = CommandPolicy(FakeConfigManager())
    assert validate_shell_command(command)[0] is False
    assert policy.is_command_allowed(command)[0] is False
    assert classify_request("run_shell_command", {"command": command}).decision == "block"


@pytest.mark.parametrize(
    "command",
    [
        r'Start-Process powershell -ArgumentList "-Command Remove-Item C:\Windows -Recurse"',
        r'start cmd -ArgumentList "/c echo safe"',
        r'Start-Process -ArgumentList "/c echo safe" -FilePath:cmd',
        r'Start-Process -FilePath C:\Windows\System32\cmd.exe -Args "/c echo safe"',
        r'Start-Process python -ArgumentList "-c print(1)"',
        r'Start-Process python "-c print(1)"',
        r'Start-Process node -ArgumentList "--eval=1"',
        r'Start-Process node -Args "--eval=1"',
        r'Start-Process $program -ArgumentList status',
        r'Start-Process git -ArgumentList $arguments',
        r'gsudo powershell -Command "Get-Date"',
    ],
)
def test_process_launch_cannot_hide_nested_execution(project, command):
    assert validate_shell_command(command)[0] is False
    assert CommandPolicy(FakeConfigManager()).is_command_allowed(command)[0] is False


def test_literal_process_launch_remains_available(project):
    assert validate_shell_command("Start-Process git -ArgumentList status") == (True, None)
    assert validate_shell_command("Set-Location tests; Get-ChildItem") == (True, None)


def test_protected_execution_directory_blocks_before_running(project, monkeypatch):
    execute = Mock(side_effect=AssertionError("Command must not execute"))
    monkeypatch.setattr("radsim.tools.shell._execute", execute)
    command = "Remove-Item System32 -Recurse -Force"
    working_dir = os.environ["SystemRoot"]
    result = run_shell_command(command, working_dir=working_dir)
    assert result["success"] is False
    assert "catastrophic" in result["error"]
    assert classify_request("run_shell_command", {"command": command, "working_dir": working_dir}).decision == "block"
    execute.assert_not_called()


def test_shell_handler_blocks_protected_directory_before_confirmation(project, monkeypatch):
    from radsim.agent_tool_handlers import AgentToolHandlersMixin

    confirm = Mock(side_effect=AssertionError("Command must not prompt"))
    execute = Mock(side_effect=AssertionError("Command must not execute"))
    monkeypatch.setattr("radsim.agent_tool_handlers.ask_confirmation", confirm)
    monkeypatch.setattr("radsim.agent_tool_handlers.execute_tool", execute)
    result = AgentToolHandlersMixin()._handle_shell_command({
        "command": "Remove-Item System32 -Recurse -Force",
        "working_dir": os.environ["SystemRoot"],
    })
    assert result["success"] is False
    assert "catastrophic" in result["error"]
    confirm.assert_not_called()
    execute.assert_not_called()


def test_safe_execution_directory_overrides_parent_directory(project, monkeypatch):
    monkeypatch.chdir(os.environ["SystemRoot"])
    execute = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("radsim.tools.shell._execute", execute)
    result = run_shell_command("Remove-Item build -Recurse", working_dir=project)
    assert result["success"] is True
    assert execute.call_args.kwargs["cwd"] == str(project)


def test_child_environment_is_used_for_path_checks(project, monkeypatch):
    monkeypatch.setenv("REVIEW_SECRET_PATH", str(project))
    execute = Mock(side_effect=AssertionError("Command must not execute"))
    monkeypatch.setattr("radsim.tools.shell._execute", execute)
    result = run_shell_command(r'Remove-Item "$env:REVIEW_SECRET_PATH\*" -Recurse')
    assert result["success"] is False
    assert "catastrophic" in result["error"]
    execute.assert_not_called()


@pytest.mark.parametrize(
    "command,destructive",
    [
        ("Remove-Item build -Recurse -Force", True),
        ("git push", True),
        ("Stop-Process -Name node", True),
        ('"data" > out.txt', True),
        ("[IO.File]::Delete('x.txt')", True),
        ("Get-ChildItem | ForEach-Object Delete", True),
        ("Get-ChildItem -Force", False),
        ("git status --short 2>&1", False),
        ("New-Item -ItemType Directory build", False),
    ],
)
def test_destructive_commands_need_confirmation(project, command, destructive):
    assert is_destructive_shell_command(command, DESTRUCTIVE_COMMANDS) is destructive


@pytest.mark.parametrize(
    "command",
    [
        "git status --short",
        "git diff --stat",
        "Get-ChildItem -Force",
        "ls",
        "Get-Location",
        "Get-Content README.md -TotalCount 5",
        "cat README.md | Select-Object -First 3",
        "Get-Content README.md | Select-String answer",
        "Select-String -Pattern answer -Path README.md",
        "git log --oneline -n 5 | Select-String fix",
        "python -m pytest tests -q",
        "npm test",
        "Write-Output hello",
    ],
)
def test_routine_commands_run_automatically(project, command):
    assert classify_request("run_shell_command", {"command": command}).decision == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "Get-Content .env",
        "Get-Content *",
        "Get-Content Env:PATH",
        "Get-ChildItem Env:",
        "Get-ChildItem | Select-String TOKEN",
        "Get-ChildItem -Recurse",
        "Get-Content README.md -Tot 5",
        "Write-Output $env:USERPROFILE",
        "Get-Content README.md > copy.md",
        "godot --headless --quit",
        "python script.py",
        "Get-Content C:\\Windows\\win.ini",
    ],
)
def test_unrecognised_or_sensitive_commands_are_not_automatic(project, command):
    assert classify_request("run_shell_command", {"command": command}).decision != "allow"


@pytest.mark.parametrize("command", ["Remove-Item README.md", "git push", "Stop-Process -Name node"])
def test_destructive_commands_are_blocked_in_auto_mode(project, command):
    assert classify_request("run_shell_command", {"command": command}).decision == "block"


def test_custom_test_path_is_quoted_for_powershell(project):
    (project / "tests" / "test_sample.py").write_text("def test_sample():\n    assert True\n")
    result = classify_request(
        "run_tests", {"test_command": "python -m pytest -q", "test_path": "tests\\test_sample.py"}
    )
    assert result.decision == "allow"


def test_test_path_cannot_inject_powershell_commands(project, monkeypatch):
    test_path = "x'; Remove-Item README.md; '"
    monkeypatch.setattr(
        "radsim.tools.testing.run_shell_command", lambda command, **options: {"returncode": 0}
    )
    result = run_tests(test_command="python -m pytest", test_path=test_path)
    parsed = parse_powershell(result["command"])
    assert parsed.errors == ()
    assert [command.name for command in parsed.commands] == ["python"]
    assert parsed.commands[0].arguments[-1].value == test_path


class TestWhitelist:
    def test_whitelist_matches_aliases_and_harmless_redirection(self, project):
        policy = CommandPolicy(FakeConfigManager("whitelist", ["git status", "ls", "get-content"]))
        assert policy.is_command_allowed("git status 2>$null") == (True, None)
        assert policy.is_command_allowed("ls")[0] is True
        assert policy.is_command_allowed("Get-Content README.md | ls")[0] is True

    @pytest.mark.parametrize(
        "command",
        [
            "Get-Content README.md > copy.md",
            "Get-Content $env:USERPROFILE",
            "Get-Content README.md; Remove-Item README.md",
            "& git status",
        ],
    )
    def test_whitelist_cannot_be_borrowed(self, project, command):
        policy = CommandPolicy(FakeConfigManager("whitelist", ["git status", "get-content"]))
        assert policy.is_command_allowed(command)[0] is False


class TestExecution:
    def test_commands_run_in_windows_powershell_by_absolute_path(self):
        arguments = shell_arguments("Get-Date")
        assert arguments[0] == windows_powershell_executable()
        assert os.path.isabs(arguments[0])
        assert arguments[-2:] == ["-Command", "Get-Date"]

    def test_powershell_syntax_runs_end_to_end(self, project):
        result = run_shell_command('$name = "rad" + "sim"; Write-Output "$($name.Length) $name"')
        assert result["success"] is True
        assert result["stdout"].strip() == "6 radsim"

    def test_user_bang_command_runs_in_powershell(self, project):
        from radsim.agent_runtime import _run_user_shell_command

        agent = SimpleNamespace(_pending_user_context=[])
        _run_user_shell_command("Write-Output $PSVersionTable.PSEdition", agent)
        assert "Desktop" in agent._pending_user_context[0]

    def test_user_bang_command_still_blocks_catastrophe(self, project):
        from radsim.agent_runtime import _run_user_shell_command

        agent = SimpleNamespace(_pending_user_context=[])
        _run_user_shell_command("Remove-Item C:\\ -Recurse -Force", agent)
        assert agent._pending_user_context == []

    def test_hooks_run_in_powershell(self, project):
        from radsim.user_hooks import UserHook, _run_hook_command

        blocking = UserHook("guard", "pre_tool", "*", "[Console]::Error.WriteLine('no'); exit 2")
        assert _run_hook_command(blocking, {"event": "pre_tool"}) == ("block", "no")
        allowing = UserHook("ok", "pre_tool", "*", "exit 0")
        assert _run_hook_command(allowing, {"event": "pre_tool"})[0] == "allow"
