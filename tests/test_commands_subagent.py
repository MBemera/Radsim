"""Tests for the /subagent command family.

The registry hands handlers a list of argument tokens, so these exercise the
real dispatch path rather than calling handlers with a pre-joined string.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from radsim.commands import CommandRegistry

VALID_PROVIDER = "openrouter"
VALID_MODEL = "moonshotai/kimi-k2.5"


@pytest.fixture
def registry():
    return CommandRegistry()


@pytest.fixture
def agent():
    return SimpleNamespace(config=SimpleNamespace(auto_confirm=True), _telegram_mode=False)


def _run(registry, agent, command):
    """Dispatch through the registry the same way the input loop does."""
    return registry.handle_input(command, agent)


class TestSubagentDispatch:
    """Every subcommand routes without an argument-shape error."""

    @pytest.mark.parametrize(
        "command",
        [
            "/subagent",
            "/subagent status",
            "/subagent profiles",
            "/subagent show missing-id",
            "/subagent edit missing-id",
            "/subagent delete missing-id",
            "/subagent run",
            "/subagent nonsense",
        ],
    )
    def test_subcommands_dispatch_cleanly(self, registry, agent, command, capsys):
        handled = _run(registry, agent, command)
        output = capsys.readouterr().out

        assert handled is True
        assert "Command error" not in output

    def test_alias_is_registered(self, registry, agent, capsys):
        _run(registry, agent, "/sub profiles")
        assert "capability profiles" in capsys.readouterr().out

    def test_unknown_action_lists_valid_ones(self, registry, agent, capsys):
        _run(registry, agent, "/subagent nonsense")
        output = capsys.readouterr().out

        assert "Unknown /subagent action" in output
        assert "profiles" in output


class TestSubagentStatus:
    """Status reports the saved pair and never a credential."""

    def test_reports_no_selection_by_default(self, registry, agent, capsys):
        _run(registry, agent, "/subagent")
        assert "not selected" in capsys.readouterr().out

    def test_reports_a_saved_selection(self, registry, agent, capsys):
        from radsim.agent_config import get_agent_config_manager

        get_agent_config_manager().set_subagent_selection(VALID_PROVIDER, VALID_MODEL)
        _run(registry, agent, "/subagent status")
        output = capsys.readouterr().out

        assert VALID_PROVIDER in output
        assert VALID_MODEL in output

    def test_never_prints_a_credential(self, registry, agent, capsys, monkeypatch):
        from radsim.agent_config import get_agent_config_manager

        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-super-secret-value")
        get_agent_config_manager().set_subagent_selection(VALID_PROVIDER, VALID_MODEL)
        _run(registry, agent, "/subagent status")

        assert "sk-super-secret-value" not in capsys.readouterr().out

    def test_lists_the_built_in_profiles(self, registry, agent, capsys):
        from radsim.sub_agent_profiles import CAPABILITY_PROFILES

        _run(registry, agent, "/subagent")
        output = capsys.readouterr().out

        for name in CAPABILITY_PROFILES:
            assert name in output


class TestSubagentProfiles:
    """Profile listing shows the real boundaries."""

    def test_shows_limits_per_profile(self, registry, agent, capsys):
        _run(registry, agent, "/subagent profiles")
        output = capsys.readouterr().out

        assert "foreground only" in output
        assert "can edit files" in output
        assert "no network" in output

    def test_shows_custom_profiles(self, registry, agent, capsys, tmp_path, monkeypatch):
        from radsim.sub_agent_profiles import save_custom_profile

        store = tmp_path / "subagents.json"
        save_custom_profile("api-reviewer", "API reviewer", "review", "Check auth.", store)
        monkeypatch.setattr(
            "radsim.sub_agent_profiles.get_custom_profiles_file", lambda: store
        )

        _run(registry, agent, "/subagent profiles")
        output = capsys.readouterr().out

        assert "api-reviewer" in output
        assert "extends review" in output


class TestSubagentProfileManagement:
    """Create, show, edit, and delete operate on the custom store."""

    @pytest.fixture(autouse=True)
    def _isolated_store(self, tmp_path, monkeypatch):
        store = tmp_path / "subagents.json"
        monkeypatch.setattr(
            "radsim.sub_agent_profiles.get_custom_profiles_file", lambda: store
        )
        return store

    def test_create_saves_a_profile(self, registry, agent, capsys):
        answers = iter(["api-reviewer", "API reviewer", "Check auth boundaries."])
        with patch("radsim.menu.safe_input", side_effect=lambda _prompt: next(answers)), patch(
            "radsim.menu.interactive_menu", return_value="review"
        ):
            _run(registry, agent, "/subagent create")

        from radsim.sub_agent_profiles import get_custom_profile

        assert "created" in capsys.readouterr().out
        assert get_custom_profile("api-reviewer")["base_profile"] == "review"

    def test_create_rejects_an_invalid_id(self, registry, agent, capsys):
        answers = iter(["BAD ID", "Name", "Do things."])
        with patch("radsim.menu.safe_input", side_effect=lambda _prompt: next(answers)), patch(
            "radsim.menu.interactive_menu", return_value="review"
        ):
            _run(registry, agent, "/subagent create")

        assert "Profile id must be" in capsys.readouterr().out

    def test_create_cancels_when_the_base_picker_is_dismissed(self, registry, agent, capsys):
        answers = iter(["api-reviewer", "API reviewer"])
        with patch("radsim.menu.safe_input", side_effect=lambda _prompt: next(answers)), patch(
            "radsim.menu.interactive_menu", return_value=None
        ):
            _run(registry, agent, "/subagent create")

        from radsim.sub_agent_profiles import load_custom_profiles

        assert "Cancelled" in capsys.readouterr().out
        assert load_custom_profiles() == []

    def test_show_reports_the_inherited_boundary(self, registry, agent, capsys):
        from radsim.sub_agent_profiles import save_custom_profile

        save_custom_profile("api-reviewer", "API reviewer", "review", "Check auth.")
        _run(registry, agent, "/subagent show api-reviewer")
        output = capsys.readouterr().out

        assert "Base profile:  review" in output
        assert "File changes:  not allowed" in output
        assert "cannot widen the base profile" in output

    def test_edit_replaces_instructions_only(self, registry, agent):
        from radsim.sub_agent_profiles import get_custom_profile, save_custom_profile

        save_custom_profile("api-reviewer", "API reviewer", "review", "Old text.")
        with patch("radsim.menu.safe_input", return_value="New text."):
            _run(registry, agent, "/subagent edit api-reviewer")

        profile = get_custom_profile("api-reviewer")
        assert profile["instructions"] == "New text."
        assert profile["base_profile"] == "review"
        assert profile["name"] == "API reviewer"

    def test_delete_requires_confirmation(self, registry, agent, capsys):
        from radsim.sub_agent_profiles import get_custom_profile, save_custom_profile

        save_custom_profile("api-reviewer", "API reviewer", "review", "Check auth.")
        with patch("radsim.safety.confirm_action", return_value=False):
            _run(registry, agent, "/subagent delete api-reviewer")

        assert "Cancelled" in capsys.readouterr().out
        assert get_custom_profile("api-reviewer") is not None

    def test_delete_removes_after_confirmation(self, registry, agent):
        from radsim.sub_agent_profiles import get_custom_profile, save_custom_profile

        save_custom_profile("api-reviewer", "API reviewer", "review", "Check auth.")
        with patch("radsim.safety.confirm_action", return_value=True):
            _run(registry, agent, "/subagent delete api-reviewer")

        assert get_custom_profile("api-reviewer") is None


class TestSubagentRun:
    """Explicit runs go through the same delegation path as the tool."""

    def test_run_passes_the_profile_and_task(self, registry):
        calls = []
        agent = SimpleNamespace(
            config=SimpleNamespace(auto_confirm=True),
            _telegram_mode=False,
            _handle_delegate_task=lambda payload: calls.append(payload)
            or {"success": True, "content": "done"},
        )

        _run(registry, agent, "/subagent run review check auth.py for gaps")

        assert calls == [
            {
                "task_description": "check auth.py for gaps",
                "profile": "review",
                "background": False,
            }
        ]

    def test_run_reports_failures(self, registry, capsys):
        agent = SimpleNamespace(
            config=SimpleNamespace(auto_confirm=True),
            _telegram_mode=False,
            _handle_delegate_task=lambda _payload: {"success": False, "error": "no model saved"},
        )

        _run(registry, agent, "/subagent run explore look around")

        assert "no model saved" in capsys.readouterr().out

    def test_run_labels_output_as_untrusted(self, registry, capsys):
        agent = SimpleNamespace(
            config=SimpleNamespace(auto_confirm=True),
            _telegram_mode=False,
            _handle_delegate_task=lambda _payload: {"success": True, "content": "findings here"},
        )

        _run(registry, agent, "/subagent run explore look around")
        output = capsys.readouterr().out

        assert "untrusted evidence" in output
        assert "findings here" in output


class TestSubagentIsNotTelegramSafe:
    """Model selection needs an interactive terminal."""

    def test_command_is_marked_not_telegram_safe(self):
        from radsim.commands_metadata import TELEGRAM_SAFE_COMMANDS

        assert "/subagent" not in TELEGRAM_SAFE_COMMANDS
