"""/auto and /sandbox must switch both states without opening a menu."""

from types import SimpleNamespace

import pytest

from radsim import agent_config
from radsim.commands import CommandRegistry
from radsim.tools import sandbox


@pytest.fixture
def agent():
    return SimpleNamespace(config=SimpleNamespace(auto_confirm=False))


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Point the config manager at a scratch directory, not the real one."""
    monkeypatch.setattr(
        agent_config, "_agent_config_manager", agent_config.AgentConfigManager(tmp_path / ".radsim")
    )
    monkeypatch.setattr(sandbox, "_auto_mode_enabled", False)
    return CommandRegistry()


def test_auto_on_enables_auto_mode_and_the_sandbox(registry, agent):
    registry._cmd_auto(agent, ["on"])

    assert agent.config.auto_confirm is True
    assert sandbox.auto_mode_enabled() is True


def test_auto_off_disables_both(registry, agent):
    registry._cmd_auto(agent, ["on"])
    registry._cmd_auto(agent, ["off"])

    assert agent.config.auto_confirm is False
    assert sandbox.auto_mode_enabled() is False


def test_sandbox_command_persists_the_setting(registry, agent):
    registry._cmd_sandbox(agent, ["off"])

    assert agent_config.get_agent_config_manager().get("sandbox.auto_mode") is False

    registry._cmd_sandbox(agent, ["on"])

    assert agent_config.get_agent_config_manager().get("sandbox.auto_mode") is True


def test_sandbox_setting_survives_without_auto_mode(registry, agent):
    """Turning the sandbox on does not silently turn auto mode on."""
    registry._cmd_sandbox(agent, ["on"])

    assert agent.config.auto_confirm is False


@pytest.mark.parametrize("word", ["on", "true", "yes", "enable"])
def test_switch_words_read_as_on(registry, word):
    assert registry._read_switch_argument([word]) is True


@pytest.mark.parametrize("word", ["off", "false", "no", "disable"])
def test_switch_words_read_as_off(registry, word):
    assert registry._read_switch_argument([word]) is False


def test_unknown_word_falls_back_to_the_menu(registry):
    assert registry._read_switch_argument(["maybe"]) is None
    assert registry._read_switch_argument([]) is None


def test_state_label_reports_why_the_sandbox_is_idle(registry, agent, monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: True)

    assert registry._sandbox_state_label(agent) == "idle (applies in auto mode)"

    agent.config.auto_confirm = True

    assert registry._sandbox_state_label(agent) == "active"


def test_state_label_reports_a_disabled_setting(registry, agent, monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: True)
    agent.config.auto_confirm = True
    registry._cmd_sandbox(agent, ["off"])

    assert registry._sandbox_state_label(agent) == "off (disabled in settings)"


def test_commands_are_registered(registry):
    assert "/auto" in registry.commands
    assert "/sandbox" in registry.commands
