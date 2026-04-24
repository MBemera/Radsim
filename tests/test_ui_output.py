import json
from pathlib import Path

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
