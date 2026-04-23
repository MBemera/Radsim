"""Tests for runtime reload lifecycle and self-modification classification."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from radsim import commands_core
from radsim.agent import RadSimAgent
from radsim.commands import CommandRegistry
from radsim.runtime_context import get_runtime_context


def build_agent(auto_confirm=False):
    """Minimal agent instance for handler-level tests."""
    agent = object.__new__(RadSimAgent)
    agent.config = SimpleNamespace(auto_confirm=auto_confirm, verbose=False)
    agent._rejected_writes = set()
    agent._mcp_manager = None
    agent._runtime_dirty = False
    agent._restart_required = False
    agent._restart_reason = None
    return agent


def test_reload_command_is_registered():
    registry = CommandRegistry()
    assert "/reload" in registry.commands
    assert registry.commands["/reload"]["accepts_args"] is True


def test_build_system_prompt_reflects_custom_prompt_changes(monkeypatch, tmp_path):
    """Changing custom_prompt.txt must affect the next prompt build."""
    custom_prompt_file = tmp_path / "custom_prompt.txt"

    monkeypatch.setattr("radsim.prompts.CUSTOM_PROMPT_FILE", custom_prompt_file, raising=False)
    monkeypatch.setattr("radsim.config.CUSTOM_PROMPT_FILE", custom_prompt_file, raising=False)

    get_runtime_context().clear_all()

    agent = build_agent()

    custom_prompt_file.write_text("FIRST_VERSION", encoding="utf-8")
    first = agent.build_system_prompt()
    assert "FIRST_VERSION" in first

    custom_prompt_file.write_text("SECOND_VERSION", encoding="utf-8")
    second = agent.build_system_prompt()
    assert "SECOND_VERSION" in second
    assert "FIRST_VERSION" not in second


def test_mark_runtime_change_for_custom_prompt(monkeypatch, tmp_path):
    custom_prompt_file = tmp_path / "custom_prompt.txt"
    custom_prompt_file.write_text("hello", encoding="utf-8")

    monkeypatch.setattr("radsim.config.CUSTOM_PROMPT_FILE", custom_prompt_file, raising=False)

    agent = build_agent()
    kind = agent._mark_runtime_change(str(custom_prompt_file))

    assert kind == "soft"
    assert agent._runtime_dirty is True
    assert agent._restart_required is False


def test_mark_runtime_change_for_core_python_source(monkeypatch, tmp_path):
    package_dir = tmp_path / "radsim_pkg"
    package_dir.mkdir()
    core_file = package_dir / "agent.py"
    core_file.write_text("print('hi')\n", encoding="utf-8")

    monkeypatch.setattr("radsim.config.PACKAGE_DIR", package_dir, raising=False)
    monkeypatch.setattr(
        "radsim.config.CUSTOM_PROMPT_FILE",
        tmp_path / "custom_prompt.txt",
        raising=False,
    )

    agent = build_agent()
    kind = agent._mark_runtime_change(str(core_file))

    assert kind == "restart"
    assert agent._restart_required is True
    assert agent._restart_reason and "agent.py" in agent._restart_reason


def test_mark_runtime_change_for_non_python_package_file(monkeypatch, tmp_path):
    package_dir = tmp_path / "radsim_pkg"
    package_dir.mkdir()
    skill_file = package_dir / "skill.md"
    skill_file.write_text("hi", encoding="utf-8")

    monkeypatch.setattr("radsim.config.PACKAGE_DIR", package_dir, raising=False)
    monkeypatch.setattr(
        "radsim.config.CUSTOM_PROMPT_FILE",
        tmp_path / "custom_prompt.txt",
        raising=False,
    )

    agent = build_agent()
    kind = agent._mark_runtime_change(str(skill_file))

    assert kind == "soft"
    assert agent._runtime_dirty is True
    assert agent._restart_required is False


def test_mark_runtime_change_for_user_file_outside_package(monkeypatch, tmp_path):
    package_dir = tmp_path / "radsim_pkg"
    package_dir.mkdir()
    user_file = tmp_path / "user_code.py"
    user_file.write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr("radsim.config.PACKAGE_DIR", package_dir, raising=False)
    monkeypatch.setattr(
        "radsim.config.CUSTOM_PROMPT_FILE",
        tmp_path / "custom_prompt.txt",
        raising=False,
    )

    agent = build_agent()
    kind = agent._mark_runtime_change(str(user_file))

    assert kind == "none"
    assert agent._runtime_dirty is False
    assert agent._restart_required is False


def test_refresh_runtime_state_clears_caches_and_dirty_flag():
    runtime = get_runtime_context()
    runtime.get_cached_prompt_fragment("probe", [], lambda: "cached_value")
    assert runtime._prompt_fragment_cache

    agent = build_agent()
    agent._runtime_dirty = True

    agent.refresh_runtime_state()

    assert runtime._prompt_fragment_cache == {}
    assert agent._runtime_dirty is False


def test_reload_soft_clears_caches_and_keeps_process_alive():
    runtime = get_runtime_context()
    runtime.get_cached_prompt_fragment("probe", [], lambda: "cached_value")

    agent = build_agent()
    agent._runtime_dirty = True

    commands_core._reload_soft(agent)

    assert runtime._prompt_fragment_cache == {}
    assert agent._runtime_dirty is False


def test_reload_auto_picks_restart_when_required(monkeypatch):
    agent = build_agent()
    agent._restart_required = True
    agent._restart_reason = "core changed"

    called = {}

    def fake_execv(python, argv):
        called["python"] = python
        called["argv"] = argv

    monkeypatch.setattr(commands_core.os, "execv", fake_execv)

    registry = CommandRegistry()
    registry.commands["/reload"]["handler"](agent, [])

    assert called, "expected os.execv to be called for restart"
    assert called["argv"][0] == called["python"]


def test_reload_auto_does_soft_when_not_required(monkeypatch):
    agent = build_agent()
    agent._restart_required = False

    monkeypatch.setattr(
        commands_core.os,
        "execv",
        lambda *args, **kwargs: pytest.fail("auto must not restart here"),
    )

    runtime = get_runtime_context()
    runtime.get_cached_prompt_fragment("probe", [], lambda: "cached_value")

    registry = CommandRegistry()
    registry.commands["/reload"]["handler"](agent, [])

    assert runtime._prompt_fragment_cache == {}


def test_reload_unknown_mode_does_not_restart(monkeypatch, capsys):
    agent = build_agent()

    monkeypatch.setattr(
        commands_core.os,
        "execv",
        lambda *args, **kwargs: pytest.fail("unknown mode must not restart"),
    )

    registry = CommandRegistry()
    registry.commands["/reload"]["handler"](agent, ["bogus"])

    out = capsys.readouterr().out
    assert "Unknown /reload mode" in out


def test_write_file_classifies_restart_when_editing_package_python(monkeypatch, tmp_path):
    package_dir = tmp_path / "radsim_pkg"
    package_dir.mkdir()
    target = package_dir / "some_module.py"

    monkeypatch.setattr("radsim.config.PACKAGE_DIR", package_dir, raising=False)
    monkeypatch.setattr(
        "radsim.config.CUSTOM_PROMPT_FILE",
        tmp_path / "custom_prompt.txt",
        raising=False,
    )

    agent = build_agent(auto_confirm=True)

    monkeypatch.setattr("radsim.agent.confirm_write", lambda *a, **k: True)
    monkeypatch.setattr("radsim.agent.is_path_safe", lambda file_path: (True, None))
    monkeypatch.setattr("radsim.modes.is_mode_active", lambda mode: False)
    monkeypatch.setattr(
        "radsim.response_validator.validate_content_for_write",
        lambda content, file_ext: (True, None),
    )
    monkeypatch.setattr(
        "radsim.safety.is_self_modification",
        lambda file_path: (True, package_dir),
    )
    monkeypatch.setattr(
        "radsim.agent.execute_tool",
        lambda tool_name, tool_input: {"success": True},
    )

    result = agent._handle_write_file(
        {"file_path": str(target), "content": "print('hi')\n"}
    )

    assert result["success"] is True
    assert agent._restart_required is True
    assert "reload_hint" in result
    assert "/reload restart" in result["reload_hint"]


def test_write_file_classifies_soft_for_custom_prompt(monkeypatch, tmp_path):
    custom_prompt_file = tmp_path / "custom_prompt.txt"

    monkeypatch.setattr("radsim.config.CUSTOM_PROMPT_FILE", custom_prompt_file, raising=False)
    monkeypatch.setattr(
        "radsim.config.PACKAGE_DIR",
        tmp_path / "radsim_pkg",
        raising=False,
    )

    agent = build_agent(auto_confirm=True)

    monkeypatch.setattr("radsim.agent.confirm_write", lambda *a, **k: True)
    monkeypatch.setattr("radsim.agent.is_path_safe", lambda file_path: (True, None))
    monkeypatch.setattr("radsim.modes.is_mode_active", lambda mode: False)
    monkeypatch.setattr(
        "radsim.response_validator.validate_content_for_write",
        lambda content, file_ext: (True, None),
    )
    monkeypatch.setattr(
        "radsim.safety.is_self_modification",
        lambda file_path: (False, None),
    )
    monkeypatch.setattr(
        "radsim.agent.execute_tool",
        lambda tool_name, tool_input: {"success": True},
    )

    result = agent._handle_write_file(
        {"file_path": str(custom_prompt_file), "content": "custom rules"}
    )

    assert result["success"] is True
    assert agent._runtime_dirty is False, "refresh_runtime_state should clear the flag"
    assert agent._restart_required is False
    assert "reload_hint" in result
    assert "next turn" in result["reload_hint"].lower()


def test_core_prompt_integrity_still_blocks_write(monkeypatch, tmp_path):
    """Safety regression: destructive prompts.py edits must still be blocked."""
    from radsim import safety
    from radsim.config import PACKAGE_DIR

    target = PACKAGE_DIR / "prompts.py"

    agent = build_agent(auto_confirm=True)

    monkeypatch.setattr("radsim.agent.is_path_safe", lambda file_path: (True, None))
    monkeypatch.setattr("radsim.modes.is_mode_active", lambda mode: False)
    monkeypatch.setattr(
        "radsim.response_validator.validate_content_for_write",
        lambda content, file_ext: (True, None),
    )
    monkeypatch.setattr(
        "radsim.safety.is_self_modification",
        lambda file_path: (True, PACKAGE_DIR),
    )
    execute_calls = []
    monkeypatch.setattr(
        "radsim.agent.execute_tool",
        lambda tool_name, tool_input: execute_calls.append((tool_name, tool_input)),
    )

    result = agent._handle_write_file(
        {"file_path": str(target), "content": "# wiped out\n"}
    )

    assert result["success"] is False
    assert "BLOCKED" in result["error"]
    assert execute_calls == []
