import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import radsim.ui as ui
from radsim.output import print_shell_output, print_tool_call, print_tool_result_verbose
from radsim.theme import load_active_animation_level, save_animation_level


def test_animation_level_round_trip(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    import radsim.config
    import radsim.theme

    config_dir = fake_home / ".radsim"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", config_dir / "settings.json")
    monkeypatch.setattr(radsim.config, "ENV_FILE", config_dir / ".env")
    monkeypatch.setattr(radsim.theme, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.theme, "SETTINGS_FILE", config_dir / "settings.json")
    monkeypatch.setattr("radsim.theme.supports_color", lambda: True)

    save_animation_level("subtle")

    settings = json.loads((config_dir / "settings.json").read_text())
    assert settings["animation_level"] == "subtle"
    assert load_active_animation_level() == "subtle"


def test_tool_call_renders_single_line_result(capsys):
    handle = print_tool_call("read_file", {"file_path": "src/app.py"})
    print_tool_result_verbose(handle, "read_file", {"success": True, "line_count": 42}, 34)

    output = capsys.readouterr().out
    assert "[read]" in output
    assert "src/app.py" in output
    assert "42 lines" in output
    assert "34ms" in output
    assert "┌" not in output
    assert "│" not in output


def test_shell_output_is_indented_and_truncated(capsys):
    print_shell_output("line 1\nline 2\nline 3\nline 4")

    output_lines = capsys.readouterr().out.splitlines()
    assert output_lines[0].startswith("    ")
    assert output_lines[1].startswith("    ")
    assert output_lines[2].startswith("    ")
    assert "(1 more lines)" in output_lines[3]


def test_plain_prompt_does_not_load_prompt_toolkit(monkeypatch):
    monkeypatch.setattr(ui.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        ui,
        "_load_prompt_toolkit",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected prompt_toolkit import")),
    )
    monkeypatch.setattr(ui.console, "input", lambda prompt: "plain input")

    assert ui.print_prompt(registry=SimpleNamespace(commands={})) == "plain input"


def test_missing_prompt_toolkit_falls_back_to_plain_input(monkeypatch):
    monkeypatch.setattr(ui.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(ui, "_load_prompt_toolkit", lambda: None)
    monkeypatch.setattr(ui.console, "input", lambda prompt: "fallback input")

    assert ui.print_prompt(registry=SimpleNamespace(commands={})) == "fallback input"


def test_interactive_prompt_keeps_command_completion(monkeypatch):
    recorded = {}

    class FakeSession:
        def prompt(self, prompt, **kwargs):
            recorded["prompt"] = prompt
            recorded.update(kwargs)
            return "/help"

    monkeypatch.setattr(ui, "_prompt_session", None)
    prompt_toolkit = (
        lambda: FakeSession(),
        lambda value: f"ansi:{value}",
        lambda raw: nullcontext(),
    )

    result = ui._prompt_with_completions(
        "[primary]>[/primary] ",
        SimpleNamespace(commands={}),
        prompt_toolkit,
    )

    assert result == "/help"
    assert recorded["prompt"].startswith("ansi:")
    assert recorded["complete_while_typing"] is True
