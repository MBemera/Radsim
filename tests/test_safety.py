"""Tests for radsim/safety.py"""

from radsim.safety import is_extension_safe, is_path_safe


def test_is_path_safe():
    # Safe paths
    assert is_path_safe("src/utils.py")[0] is True
    assert is_path_safe("README.md")[0] is True

    # Unsafe paths
    assert is_path_safe(".env")[0] is False
    assert is_path_safe("secrets/keys.txt")[0] is False
    assert is_path_safe("path/to/id_rsa")[0] is False


def test_is_extension_safe():
    # Safe extensions
    assert is_extension_safe("test.py")[0] is True
    assert is_extension_safe("style.css")[0] is True
    assert is_extension_safe("Makefile")[0] is True

    # Unsafe/uncommon extensions
    assert is_extension_safe("data.exe")[0] is False
    assert is_extension_safe("image.psd")[0] is False


def test_prompt_for_confirmation_uses_plain_input(monkeypatch):
    """Test that the confirmation prompt prints first, then reads input() cleanly."""
    from radsim import safety

    calls = []

    monkeypatch.setattr(safety, "_flush_stdin_buffer", lambda: calls.append("flush"))
    monkeypatch.setattr(
        "radsim.escape_listener.pause_escape_listener",
        lambda: calls.append("pause"),
    )
    monkeypatch.setattr(
        "radsim.escape_listener.resume_escape_listener",
        lambda: calls.append("resume"),
    )

    def fake_print(*args, **kwargs):
        calls.append(("print", args, kwargs))

    def fake_input(*args, **kwargs):
        calls.append(("input", args, kwargs))
        return "  y  "

    monkeypatch.setattr("builtins.print", fake_print)
    monkeypatch.setattr("builtins.input", fake_input)

    response = safety._prompt_for_confirmation("Confirm action? [y/n/all]: ")

    assert response == "y"
    assert calls[0] == "pause"
    assert calls[1] == "flush"
    assert calls[2][0] == "print"
    assert calls[3][0] == "input"
    assert calls[3][1] == ()
    assert calls[-1] == "resume"


def test_prompt_escapes_terminal_controls(monkeypatch):
    """Untrusted confirmation text cannot clear or rewrite the terminal."""
    from radsim import safety

    printed = []
    monkeypatch.setattr(safety, "_flush_stdin_buffer", lambda: None)
    monkeypatch.setattr("radsim.escape_listener.pause_escape_listener", lambda: None)
    monkeypatch.setattr("radsim.escape_listener.resume_escape_listener", lambda: None)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: printed.append(args[0]))
    monkeypatch.setattr("builtins.input", lambda: "n")

    safety._prompt_for_confirmation("danger\x1b[2K\rhidden\ncontinue")

    assert printed == ["\ndanger\\x1b[2K\\x0dhidden\\x0acontinue"]


def test_prompt_escapes_layout_control_characters(monkeypatch):
    """Untrusted messages cannot inject extra prompt lines or tab spacing."""
    from radsim import safety

    printed = []
    monkeypatch.setattr(safety, "_flush_stdin_buffer", lambda: None)
    monkeypatch.setattr("radsim.escape_listener.pause_escape_listener", lambda: None)
    monkeypatch.setattr("radsim.escape_listener.resume_escape_listener", lambda: None)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: printed.append(args[0]))
    monkeypatch.setattr("builtins.input", lambda: "n")

    safety._prompt_for_confirmation("real\nfake\tcontext\u202ereversed")

    assert printed == ["\nreal\\x0afake\\x09context\\u202ereversed"]


def test_write_preview_escapes_terminal_controls(monkeypatch, capsys):
    """A file preview cannot clear the terminal before approval."""
    from radsim import safety

    monkeypatch.setattr(safety, "is_path_safe", lambda path: (True, None))
    monkeypatch.setattr(safety, "is_extension_safe", lambda path: (False, "Review required"))
    monkeypatch.setattr(safety, "_prompt_for_confirmation", lambda prompt: "n")

    result = safety.confirm_write("safe\n\t\x1b[2K.py", "visible\n\t\x9b2Khidden")

    output = capsys.readouterr().out
    assert result is False
    assert "\x1b" not in output
    assert "\x9b" not in output
    assert "\\x1b[2K" in output
    assert "\\x9b2K" in output
    assert "safe\\x0a\\x09" in output
    assert "visible\n\\x09" in output


def test_confirm_action_accepts_all(monkeypatch):
    """Test that confirm_action still enables auto-confirm on 'all'."""
    from types import SimpleNamespace

    from radsim import safety

    monkeypatch.setattr(safety, "_prompt_for_confirmation", lambda prompt: "all")

    config = SimpleNamespace(auto_confirm=False)
    result = safety.confirm_action("Proceed?", config=config)

    assert result is True
    assert config.auto_confirm is True


def test_confirm_action_without_config_never_offers_all(monkeypatch):
    """The prompt must not advertise 'all' when nothing can persist it."""
    from radsim import safety

    prompts = []
    monkeypatch.setattr(
        safety, "_prompt_for_confirmation", lambda prompt: prompts.append(prompt) or "all"
    )

    result = safety.confirm_action("Proceed?")

    assert result is False  # 'all' is not accepted when it was not offered
    assert "[y/n]:" in prompts[0]
    assert "all" not in prompts[0]


def test_ask_confirmation_returns_all_only_when_offered(monkeypatch):
    """'all' answers round-trip only for callers that can honor them."""
    from radsim import safety

    prompts = []
    monkeypatch.setattr(
        safety, "_prompt_for_confirmation", lambda prompt: prompts.append(prompt) or "all"
    )

    assert safety.ask_confirmation("Run?", offer_all=True) == "all"
    assert "[y/n/all]:" in prompts[0]
    assert safety.ask_confirmation("Run?") == "no"


def test_ask_confirmation_yes_and_no(monkeypatch):
    from radsim import safety

    monkeypatch.setattr(safety, "_prompt_for_confirmation", lambda prompt: "y")
    assert safety.ask_confirmation("Run?") == "yes"

    monkeypatch.setattr(safety, "_prompt_for_confirmation", lambda prompt: "nope")
    assert safety.ask_confirmation("Run?") == "no"
