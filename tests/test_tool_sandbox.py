"""Tests for radsim/tools/sandbox.py

Auto mode approves a test runner by name; the sandbox is what stops the code
that runner executes from writing outside the project.
"""

import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from radsim.agent_config import SECURITY_SWITCHES, AgentConfigManager
from radsim.tools import sandbox
from radsim.tools.shell import run_process, run_shell_command

on_macos = pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS only")


@pytest.fixture
def project(tmp_path):
    """A working directory with one file the sandbox must protect outside it."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    (tmp_path / "outside.txt").write_text("protected\n")
    return workspace


@pytest.fixture
def auto_mode(monkeypatch, project):
    """Run as if RadSim started with --yes, with seatbelt reported available.

    The temp directory is redirected inside the project because pytest's own
    tmp_path lives under TMPDIR, which the real profile makes writable.
    """
    scratch = project / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(sandbox.tempfile, "gettempdir", lambda: str(scratch))
    monkeypatch.setattr(sandbox, "_auto_mode_enabled", True)
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: True)
    monkeypatch.setattr(sandbox, "sandbox_requested", lambda: True)


def test_manual_mode_does_not_sandbox(project):
    assert sandbox.wrap_shell_arguments(["bash", "-c", "ls"], str(project)) == [
        "bash",
        "-c",
        "ls",
    ]


def test_auto_mode_wraps_arguments_with_seatbelt(auto_mode, project):
    arguments = sandbox.wrap_shell_arguments(["bash", "-c", "ls"], str(project))

    assert arguments[0] == "sandbox-exec"
    assert arguments[1] == "-p"
    assert arguments[3:] == ["bash", "-c", "ls"]


def test_disabled_setting_turns_the_sandbox_off(auto_mode, monkeypatch, project):
    monkeypatch.setattr(sandbox, "sandbox_requested", lambda: False)

    assert sandbox.wrap_shell_arguments(["bash", "-c", "ls"], str(project)) == [
        "bash",
        "-c",
        "ls",
    ]


def test_unavailable_platform_turns_the_sandbox_off(auto_mode, monkeypatch, project):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: False)

    assert sandbox.wrap_shell_arguments(["bash", "-c", "ls"], str(project)) == [
        "bash",
        "-c",
        "ls",
    ]


def test_unreadable_setting_keeps_the_sandbox_on(monkeypatch):
    monkeypatch.setattr(
        "radsim.agent_config.get_agent_config_manager", Mock(side_effect=RuntimeError)
    )

    assert sandbox.sandbox_requested() is True


def test_profile_denies_writes_before_allowing_the_working_directory(project):
    profile = sandbox.build_sandbox_profile(str(project))
    lines = profile.splitlines()

    assert lines[0] == "(version 1)"
    assert lines.index("(deny file-write*)") < lines.index(
        f'(allow file-write* (subpath "{os.path.realpath(project)}"))'
    )


def test_profile_resolves_symlinked_paths(project):
    """Seatbelt matches real paths, so /tmp must appear as /private/tmp."""
    profile = sandbox.build_sandbox_profile(str(project))

    assert '(subpath "/tmp")' not in profile
    assert str(project) in profile or os.path.realpath(project) in profile


def test_profile_never_makes_the_whole_filesystem_writable(monkeypatch, project):
    monkeypatch.setattr(sandbox, "WRITABLE_CACHE_PATHS", ("/",))

    profile = sandbox.build_sandbox_profile(str(project))

    assert '(subpath "/")' not in profile


def test_profile_omits_absent_cache_directories(monkeypatch, project):
    monkeypatch.setattr(sandbox, "WRITABLE_CACHE_PATHS", ("/nonexistent-cache-path",))

    assert "/nonexistent-cache-path" not in sandbox.build_sandbox_profile(str(project))


def test_profile_quotes_paths_containing_quotes(tmp_path):
    workspace = tmp_path / 'quote"dir'
    workspace.mkdir()

    profile = sandbox.build_sandbox_profile(str(workspace))

    assert '\\"' in profile


@on_macos
def test_sandbox_blocks_deletion_outside_the_working_directory(auto_mode, project, tmp_path):
    victim = tmp_path / "outside.txt"

    result = run_shell_command(f"rm -f {victim}", working_dir=str(project))

    assert result["success"] is False
    assert victim.read_text() == "protected\n"


@on_macos
def test_sandbox_blocks_project_code_deleting_outside_files(auto_mode, project, tmp_path):
    """The demonstrated gap: an approved runner executing arbitrary project code."""
    victim = tmp_path / "outside.txt"
    (project / "cleanup.py").write_text(f"import os\nos.unlink({str(victim)!r})\n")

    result = run_shell_command("python3 cleanup.py", working_dir=str(project))

    assert result["success"] is False
    assert victim.read_text() == "protected\n"


@on_macos
def test_sandbox_allows_writes_inside_the_working_directory(auto_mode, project):
    result = run_shell_command("echo built > artifact.txt", working_dir=str(project))

    assert result["success"] is True
    assert (project / "artifact.txt").read_text() == "built\n"


@on_macos
def test_sandbox_allows_reads_outside_the_working_directory(auto_mode, project, tmp_path):
    result = run_shell_command(f"cat {tmp_path / 'outside.txt'}", working_dir=str(project))

    assert result["success"] is True
    assert "protected" in result["stdout"]


@on_macos
def test_run_process_is_not_sandboxed(auto_mode, project, tmp_path):
    """RadSim builds this argv itself; git and deploy tools must keep working."""
    victim = tmp_path / "outside.txt"

    result = run_process(["rm", "-f", str(victim)], working_dir=str(project))

    assert result["success"] is True
    assert not victim.exists()


def test_sandbox_is_on_by_default_and_toggleable(tmp_path):
    manager = AgentConfigManager(config_dir=tmp_path / ".radsim")

    assert manager.get("sandbox.auto_mode") is True

    manager.apply_security_switches({"sandbox.auto_mode": False})

    assert manager.get("sandbox.auto_mode") is False
    assert ("sandbox.auto_mode", "Sandbox shell commands in auto mode (macOS)") in SECURITY_SWITCHES


def test_settings_menu_lists_the_sandbox_switch(tmp_path):
    manager = AgentConfigManager(config_dir=tmp_path / ".radsim")

    switches = {switch["key"]: switch for switch in manager.get_security_switches()}

    assert switches["sandbox.auto_mode"]["value"] is True


def test_cli_records_auto_mode_for_the_sandbox(monkeypatch):
    monkeypatch.setattr(sandbox, "_auto_mode_enabled", False)

    sandbox.set_auto_mode(True)

    assert sandbox.auto_mode_enabled() is True


def test_writable_directories_include_the_working_directory(project):
    directories = sandbox.writable_directories(str(project))

    assert os.path.realpath(project) in directories
    assert Path(directories[0]).is_absolute()


def test_prompt_stays_quiet_when_not_sandboxed(monkeypatch):
    from radsim.prompts import get_system_prompt

    monkeypatch.setattr(sandbox, "_auto_mode_enabled", False)

    assert "Sandbox active" not in get_system_prompt()


def test_prompt_tells_the_model_when_it_is_sandboxed(auto_mode):
    from radsim.prompts import get_system_prompt

    prompt = get_system_prompt()

    assert "Sandbox active" in prompt
    assert "Operation not permitted" in prompt


def test_answering_all_turns_on_the_sandbox_too(monkeypatch):
    """Auto mode reached at a prompt must confine commands like --yes does."""
    from types import SimpleNamespace

    from radsim.safety import _enable_auto_confirm

    monkeypatch.setattr(sandbox, "_auto_mode_enabled", False)
    config = SimpleNamespace(auto_confirm=False)

    _enable_auto_confirm(config)

    assert config.auto_confirm is True
    assert sandbox.auto_mode_enabled() is True
