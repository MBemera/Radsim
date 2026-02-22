import json
import os
from pathlib import Path

from radsim.config import load_config


def test_config_defaults(tmp_path, monkeypatch):
    # Mock home directory to avoid messing with real config
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Reload SETTINGS_FILE based on mocked home
    import radsim.config

    monkeypatch.setattr(radsim.config, "CONFIG_DIR", fake_home / ".radsim")
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", fake_home / ".radsim" / "settings.json")
    monkeypatch.setattr(radsim.config, "ENV_FILE", fake_home / ".radsim" / ".env")

    # Mock environment
    monkeypatch.setenv("RADSIM_API_KEY", "test-key")

    config = load_config(provider_override="openai")
    assert config.provider == "openai"
    assert config.api_key == "test-key"
    assert config.stream is True  # Default


def test_config_from_settings_json(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    config_dir = fake_home / ".radsim"
    config_dir.mkdir()
    settings_file = config_dir / "settings.json"

    settings = {
        "default_provider": "gemini",
        "default_model": "gemini-2.5-pro",
        "stream": False,
        "verbose": True,
    }
    settings_file.write_text(json.dumps(settings))

    import radsim.config

    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(radsim.config, "ENV_FILE", config_dir / ".env")

    # Mock environment to be empty except for what we want
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setenv("RADSIM_API_KEY", "test-key")

    # Mock load_env_file to avoid reading real .env from CWD
    monkeypatch.setattr(
        radsim.config,
        "load_env_file",
        lambda: {"api_key": None, "provider": None, "model": None, "keys": {}},
    )

    config = load_config()
    assert config.provider == "gemini"
    assert config.model == "gemini-2.5-pro"
    assert config.stream is False
    assert config.verbose is True
