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


def test_confirm_action_accepts_all(monkeypatch):
    """Test that confirm_action still enables auto-confirm on 'all'."""
    from types import SimpleNamespace

    from radsim import safety

    monkeypatch.setattr(safety, "_prompt_for_confirmation", lambda prompt: "all")

    config = SimpleNamespace(auto_confirm=False)
    result = safety.confirm_action("Proceed?", config=config)

    assert result is True
    assert config.auto_confirm is True
