"""Tests for the slash-command inline dropdown completer."""

import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.document import Document

from radsim.command_completer import SlashCommandCompleter, build_completer
from radsim.commands import CommandRegistry
from radsim.commands_metadata import DEFAULT_COMMAND_SPECS


def _collect(completer, text):
    doc = Document(text=text, cursor_position=len(text))
    return list(completer.get_completions(doc, complete_event=None))


def test_every_registered_command_appears_for_slash():
    registry = CommandRegistry()
    completer = build_completer(registry)

    completions = _collect(completer, "/")
    emitted = {c.text for c in completions}

    assert emitted == set(registry.commands.keys())


def test_every_spec_name_is_registered_and_dropdown_visible():
    registry = CommandRegistry()
    completer = build_completer(registry)
    completions = _collect(completer, "/")
    emitted = {c.text for c in completions}

    for spec in DEFAULT_COMMAND_SPECS:
        for name in spec["names"]:
            assert name in registry.commands, f"{name} missing from registry"
            assert name in emitted, f"{name} missing from dropdown"


def test_every_spec_alias_is_dispatchable():
    class MockAgent:
        def __init__(self):
            self.system_prompt = "test"

        def reset(self):
            pass

        def update_config(self, p, k, m):
            pass

    registry = CommandRegistry()

    for spec in DEFAULT_COMMAND_SPECS:
        for name in spec["names"]:
            assert name in registry.commands, f"{name} not registered"
            info = registry.commands[name]
            assert callable(info["handler"]), f"{name} has no handler"
            assert info["primary"] == spec["names"][0], (
                f"{name} primary mismatch"
            )


def test_completions_are_alphabetical():
    registry = CommandRegistry()
    completer = build_completer(registry)

    completions = _collect(completer, "/")
    names = [c.text for c in completions]

    assert names == sorted(registry.commands.keys())


def test_prefix_filter_narrows_to_help():
    registry = CommandRegistry()
    completer = build_completer(registry)

    completions = _collect(completer, "/help")
    assert [c.text for c in completions] == ["/help"]


def test_prefix_filter_narrows_c_group():
    registry = CommandRegistry()
    completer = build_completer(registry)

    completions = _collect(completer, "/c")
    names = [c.text for c in completions]

    assert names == sorted(n for n in registry.commands if n.startswith("/c"))
    for expected in ("/c", "/clear", "/commands"):
        assert expected in names


def test_non_slash_input_yields_no_completions():
    registry = CommandRegistry()
    completer = build_completer(registry)

    assert _collect(completer, "") == []
    assert _collect(completer, "hello") == []
    assert _collect(completer, "T") == []
    assert _collect(completer, "write a python script") == []


def test_all_completions_have_display_meta():
    registry = CommandRegistry()
    completer = build_completer(registry)

    for completion in _collect(completer, "/"):
        assert completion.display_meta_text, f"{completion.text} has no meta"


def test_alias_meta_points_to_primary():
    registry = CommandRegistry()
    completer = build_completer(registry)

    completions = {c.text: c for c in _collect(completer, "/")}

    assert "→ /help" in completions["/h"].display_meta_text
    assert "→ /help" in completions["/?"].display_meta_text
    assert "→ /clear" in completions["/c"].display_meta_text


def test_build_completer_returns_instance():
    registry = CommandRegistry()
    completer = build_completer(registry)
    assert isinstance(completer, SlashCommandCompleter)
