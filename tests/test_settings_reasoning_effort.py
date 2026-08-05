"""Reasoning effort must be reachable and persistent from /settings."""

import json
from types import SimpleNamespace

import pytest

from radsim import config
from radsim.commands import CommandRegistry


class FakeClient:
    def __init__(self, reasoning_effort=None):
        self.reasoning_effort = reasoning_effort


def make_agent():
    """Build the minimum agent surface /settings reads and writes."""
    return SimpleNamespace(
        config=SimpleNamespace(
            provider="openrouter",
            model="z-ai/glm-5.2",
            api_key="test-key",
            reasoning_effort="high",
        ),
        client=FakeClient("high"),
    )


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Redirect settings.json so no test touches the real one."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", path)
    return path


@pytest.fixture
def supported_efforts(monkeypatch):
    """Pin the model capability table so tests never hit the network."""
    monkeypatch.setattr(
        config,
        "get_reasoning_effort_options",
        lambda provider, model: ("high", "xhigh"),
    )


@pytest.fixture
def client_factory(monkeypatch):
    """Record every client rebuild instead of constructing a real one."""
    created = []

    def create_client(provider, api_key, model=None, reasoning_effort=None, **kwargs):
        client = FakeClient(reasoning_effort)
        created.append(client)
        return client

    monkeypatch.setattr("radsim.api_client.create_client", create_client)
    return created


class TestReasoningEffortMenu:
    def test_bare_subcommand_opens_a_menu_and_saves_the_choice(
        self, settings_file, supported_efforts, client_factory, monkeypatch
    ):
        """Zero typed arguments must reach a menu, never a usage error."""
        seen_options = []

        def fake_menu(title, options, **kwargs):
            seen_options.append((title, [key for key, _label in options]))
            return "xhigh"

        monkeypatch.setattr("radsim.menu.interactive_menu", fake_menu)
        registry = CommandRegistry()
        agent = make_agent()

        registry._cmd_settings(agent, ["reasoning"])

        title, keys = seen_options[0]
        assert keys == ["high", "xhigh"]
        assert "current: high" in title
        assert json.loads(settings_file.read_text())["reasoning_effort"] == "xhigh"

    def test_choice_applies_to_the_live_session_and_persists(
        self, settings_file, supported_efforts, client_factory, monkeypatch
    ):
        monkeypatch.setattr("radsim.menu.interactive_menu", lambda *a, **k: "xhigh")
        registry = CommandRegistry()
        agent = make_agent()

        registry._cmd_settings(agent, ["reasoning"])

        assert agent.config.reasoning_effort == "xhigh"
        assert agent.client.reasoning_effort == "xhigh"
        assert client_factory[-1] is agent.client
        assert config.load_reasoning_effort() == "xhigh"

    def test_cancelling_the_menu_changes_nothing(
        self, settings_file, supported_efforts, client_factory, monkeypatch
    ):
        monkeypatch.setattr("radsim.menu.interactive_menu", lambda *a, **k: None)
        registry = CommandRegistry()
        agent = make_agent()

        registry._cmd_settings(agent, ["reasoning"])

        assert not settings_file.exists()
        assert agent.config.reasoning_effort == "high"
        assert client_factory == []

    def test_settings_menu_shows_the_active_value(
        self, settings_file, supported_efforts, client_factory, monkeypatch
    ):
        labels = []

        def fake_menu(title, options, **kwargs):
            labels.extend(label for _key, label in options)
            return None

        monkeypatch.setattr("radsim.menu.interactive_menu", fake_menu)
        config.save_reasoning_effort("xhigh")
        registry = CommandRegistry()

        registry._cmd_settings(make_agent(), None)

        assert "Reasoning effort [xhigh]" in labels


class TestReasoningEffortFailsClosed:
    def test_unsupported_level_is_refused_without_writing(
        self, settings_file, supported_efforts, client_factory, capsys
    ):
        config.save_reasoning_effort("high")
        registry = CommandRegistry()
        agent = make_agent()

        registry._cmd_settings(agent, ["reasoning", "ludicrous"])

        assert config.load_reasoning_effort() == "high"
        assert agent.config.reasoning_effort == "high"
        assert client_factory == []
        assert "Unsupported reasoning effort" in capsys.readouterr().out

    def test_model_without_the_dial_reports_instead_of_writing(
        self, settings_file, client_factory, monkeypatch, capsys
    ):
        monkeypatch.setattr(config, "get_reasoning_effort_options", lambda *a: ())
        registry = CommandRegistry()
        agent = make_agent()

        registry._cmd_settings(agent, ["reasoning"])

        assert not settings_file.exists()
        assert client_factory == []
        assert "does not expose a reasoning effort" in capsys.readouterr().out

    def test_menu_label_marks_an_unsupported_model(
        self, settings_file, client_factory, monkeypatch
    ):
        labels = []
        monkeypatch.setattr(config, "get_reasoning_effort_options", lambda *a: ())

        def fake_menu(title, options, **kwargs):
            labels.extend(label for _key, label in options)
            return None

        monkeypatch.setattr("radsim.menu.interactive_menu", fake_menu)
        registry = CommandRegistry()

        registry._cmd_settings(make_agent(), None)

        assert "Reasoning effort [unsupported by this model]" in labels
