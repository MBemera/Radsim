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
        "default_provider": "openrouter",
        "default_model": "moonshotai/kimi-k2.5",
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
    assert config.provider == "openrouter"
    assert config.model == "moonshotai/kimi-k2.5"
    assert config.stream is False
    assert config.verbose is True


def test_load_env_file_prefers_memory_preferred_env_path(tmp_path, monkeypatch):
    import radsim.config

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    config_dir = fake_home / ".radsim"
    config_dir.mkdir()
    settings_file = config_dir / "settings.json"
    settings_file.write_text("{}")

    project_root = tmp_path / "project"
    project_root.mkdir()
    preferred_env_file = tmp_path / "preferred.env"
    preferred_env_file.write_text('OPENAI_API_KEY="preferred-key"\n')
    project_env_file = project_root / ".env"
    project_env_file.write_text('OPENAI_API_KEY="project-key"\n')
    global_env_file = config_dir / ".env"
    global_env_file.write_text('OPENAI_API_KEY="global-key"\n')

    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(radsim.config, "ENV_FILE", global_env_file)
    monkeypatch.setattr(radsim.config, "PROJECT_ENV_FILE", project_env_file)
    monkeypatch.setattr(radsim.config, "PACKAGE_DIR", project_root / "radsim")
    monkeypatch.setattr(radsim.config, "get_runtime_context", lambda: _FakeRuntimeContext(preferred_env_file))
    monkeypatch.delenv("RADSIM_ENV_FILE", raising=False)

    env_config = radsim.config.load_env_file()

    assert env_config["keys"]["OPENAI_API_KEY"] == "preferred-key"


def test_load_env_file_prefers_project_env_over_global(tmp_path, monkeypatch):
    import radsim.config

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    config_dir = fake_home / ".radsim"
    config_dir.mkdir()
    settings_file = config_dir / "settings.json"
    settings_file.write_text("{}")

    project_root = tmp_path / "project"
    project_root.mkdir()
    project_env_file = project_root / ".env"
    project_env_file.write_text('OPENAI_API_KEY="project-key"\n')
    global_env_file = config_dir / ".env"
    global_env_file.write_text('OPENAI_API_KEY="global-key"\n')

    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(radsim.config, "ENV_FILE", global_env_file)
    monkeypatch.setattr(radsim.config, "PROJECT_ENV_FILE", project_env_file)
    monkeypatch.setattr(radsim.config, "PACKAGE_DIR", project_root / "radsim")
    monkeypatch.setattr(radsim.config, "get_runtime_context", lambda: _FakeRuntimeContext(None))
    monkeypatch.delenv("RADSIM_ENV_FILE", raising=False)

    env_config = radsim.config.load_env_file()

    assert env_config["keys"]["OPENAI_API_KEY"] == "project-key"


class _FakeRuntimeContext:
    def __init__(self, preferred_env_file):
        self._preferred_env_file = preferred_env_file

    def get_memory(self):
        return _FakeMemory(self._preferred_env_file)


class _FakeMemory:
    def __init__(self, preferred_env_file):
        self.global_mem = _FakeGlobalMemory(preferred_env_file)


class _FakeGlobalMemory:
    def __init__(self, preferred_env_file):
        self._preferred_env_file = preferred_env_file

    def get_preference(self, key, default=None):
        if key == "preferred_env_file":
            return str(self._preferred_env_file) if self._preferred_env_file else default
        return default
