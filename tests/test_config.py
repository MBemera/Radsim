import json
import os
from pathlib import Path

import pytest

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


def test_openrouter_first_run_default_is_glm_5_2(tmp_path, monkeypatch):
    import radsim.config

    _isolate_config(tmp_path, monkeypatch)
    monkeypatch.setenv("RADSIM_API_KEY", "test-key")
    monkeypatch.delenv("RADSIM_MODEL", raising=False)
    monkeypatch.delenv("RADSIM_PROVIDER", raising=False)

    config = load_config()

    assert radsim.config.DEFAULT_MODELS["openrouter"] == "z-ai/glm-5.2"
    assert config.model == "z-ai/glm-5.2"


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
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    preferred_env_file = tmp_path / "preferred.env"
    preferred_env_file.write_text('OPENAI_API_KEY="preferred-key"\n')
    project_env_file = project_root / ".env"
    project_env_file.write_text('OPENAI_API_KEY="project-key"\n')
    global_env_file = config_dir / ".env"
    global_env_file.write_text('OPENAI_API_KEY="global-key"\n')

    monkeypatch.chdir(cwd_dir)
    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(radsim.config, "ENV_FILE", global_env_file)
    monkeypatch.setattr(radsim.config, "PROJECT_ENV_FILE", project_env_file)
    monkeypatch.setattr(radsim.config, "PACKAGE_DIR", project_root / "radsim")
    monkeypatch.setattr(radsim.config, "get_runtime_context", lambda: _FakeRuntimeContext(preferred_env_file))
    monkeypatch.delenv("RADSIM_ENV_FILE", raising=False)

    env_config = radsim.config.load_env_file()

    assert env_config["keys"]["OPENAI_API_KEY"] == "preferred-key"


def test_project_env_ignored_for_credentials_by_default(tmp_path, monkeypatch):
    """R-08: an untrusted project/cwd .env must not override global config."""
    import radsim.config

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    config_dir = fake_home / ".radsim"
    config_dir.mkdir()
    settings_file = config_dir / "settings.json"
    settings_file.write_text("{}")

    project_root = tmp_path / "project"
    project_root.mkdir()
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    cwd_env_file = cwd_dir / ".env"
    cwd_env_file.write_text('OPENAI_API_KEY="cwd-key"\n')
    project_env_file = project_root / ".env"
    project_env_file.write_text('OPENAI_API_KEY="project-key"\n')
    global_env_file = config_dir / ".env"
    global_env_file.write_text('OPENAI_API_KEY="global-key"\n')

    monkeypatch.chdir(cwd_dir)
    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(radsim.config, "ENV_FILE", global_env_file)
    monkeypatch.setattr(radsim.config, "PROJECT_ENV_FILE", project_env_file)
    monkeypatch.setattr(radsim.config, "PACKAGE_DIR", project_root / "radsim")
    monkeypatch.setattr(radsim.config, "get_runtime_context", lambda: _FakeRuntimeContext(None))
    monkeypatch.delenv("RADSIM_ENV_FILE", raising=False)
    monkeypatch.delenv("RADSIM_TRUST_PROJECT_ENV", raising=False)

    env_config = radsim.config.load_env_file()

    # Neither the cwd nor the source-checkout .env is trusted: global wins.
    assert env_config["keys"]["OPENAI_API_KEY"] == "global-key"


def test_project_env_used_when_explicitly_trusted(tmp_path, monkeypatch):
    """R-08: opting in with RADSIM_TRUST_PROJECT_ENV restores project override."""
    import radsim.config

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    config_dir = fake_home / ".radsim"
    config_dir.mkdir()
    settings_file = config_dir / "settings.json"
    settings_file.write_text("{}")

    project_root = tmp_path / "project"
    project_root.mkdir()
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    cwd_env_file = cwd_dir / ".env"
    cwd_env_file.write_text('OPENAI_API_KEY="cwd-key"\n')
    project_env_file = project_root / ".env"
    project_env_file.write_text('OPENAI_API_KEY="project-key"\n')
    global_env_file = config_dir / ".env"
    global_env_file.write_text('OPENAI_API_KEY="global-key"\n')

    monkeypatch.chdir(cwd_dir)
    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(radsim.config, "ENV_FILE", global_env_file)
    monkeypatch.setattr(radsim.config, "PROJECT_ENV_FILE", project_env_file)
    monkeypatch.setattr(radsim.config, "PACKAGE_DIR", project_root / "radsim")
    monkeypatch.setattr(radsim.config, "get_runtime_context", lambda: _FakeRuntimeContext(None))
    monkeypatch.delenv("RADSIM_ENV_FILE", raising=False)
    monkeypatch.setenv("RADSIM_TRUST_PROJECT_ENV", "1")

    env_config = radsim.config.load_env_file()

    # cwd .env is highest-priority project source when trust is enabled.
    assert env_config["keys"]["OPENAI_API_KEY"] == "cwd-key"


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


def test_model_belongs_to_provider():
    from radsim.config import model_belongs_to_provider

    assert model_belongs_to_provider("claude-opus-4-8", "claude")
    assert model_belongs_to_provider("gpt-5.2", "openai")
    # A model listed under another provider must be rejected
    assert not model_belongs_to_provider("claude-opus-4-8", "openai")
    assert not model_belongs_to_provider("gpt-5.2", "claude")
    # Custom/unknown model IDs are allowed for any provider
    assert model_belongs_to_provider("my-fine-tuned-model", "openai")


def test_stale_model_dropped_on_provider_switch(tmp_path, monkeypatch):
    """A saved Claude model must not leak into an OpenAI session."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    import radsim.config

    monkeypatch.setattr(radsim.config, "CONFIG_DIR", fake_home / ".radsim")
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", fake_home / ".radsim" / "settings.json")
    monkeypatch.setattr(radsim.config, "ENV_FILE", fake_home / ".radsim" / ".env")

    monkeypatch.setenv("RADSIM_API_KEY", "test-key")
    monkeypatch.setenv("RADSIM_MODEL", "claude-opus-4-8")

    config = load_config(provider_override="openai")
    assert config.provider == "openai"
    assert config.model == radsim.config.DEFAULT_MODELS["openai"]


def test_model_override_wins(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    import radsim.config

    monkeypatch.setattr(radsim.config, "CONFIG_DIR", fake_home / ".radsim")
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", fake_home / ".radsim" / "settings.json")
    monkeypatch.setattr(radsim.config, "ENV_FILE", fake_home / ".radsim" / ".env")

    monkeypatch.setenv("RADSIM_API_KEY", "test-key")

    config = load_config(provider_override="openai", model_override="gpt-5-mini")
    assert config.model == "gpt-5-mini"


def _isolate_config(tmp_path, monkeypatch):
    """Point config file paths at a temp dir and return the .env path."""
    import radsim.config

    config_dir = tmp_path / ".radsim"
    env_file = config_dir / ".env"
    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.config, "SETTINGS_FILE", config_dir / "settings.json")
    monkeypatch.setattr(radsim.config, "ENV_FILE", env_file)
    monkeypatch.setattr(radsim.config, "PROJECT_ENV_FILE", tmp_path / "nonexistent.env")
    return env_file


def test_save_config_never_persists_none_model(tmp_path, monkeypatch):
    """A None model (from /login) must not overwrite the saved model."""
    from radsim.config import load_env_file, save_config

    _isolate_config(tmp_path, monkeypatch)

    save_config("test-key", "openrouter", "z-ai/glm-5.2")
    assert load_env_file()["model"] == "z-ai/glm-5.2"

    # Simulate /login: credentials change, model is None
    save_config("test-key", "openrouter", None)

    saved = load_env_file()
    assert saved["model"] == "z-ai/glm-5.2"  # preserved, not "None"
    assert 'RADSIM_MODEL="None"' not in (tmp_path / ".radsim" / ".env").read_text()


def test_save_config_falls_back_to_default_when_no_prior_model(tmp_path, monkeypatch):
    """With no prior saved model, a None model uses the provider default."""
    from radsim.config import DEFAULT_MODELS, load_env_file, save_config

    _isolate_config(tmp_path, monkeypatch)

    save_config("test-key", "openrouter", None)

    assert load_env_file()["model"] == DEFAULT_MODELS["openrouter"]


def test_last_model_selection_wins_over_legacy_global_model(tmp_path, monkeypatch):
    from radsim.config import load_config, save_last_model_selection

    env_file = _isolate_config(tmp_path, monkeypatch)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        'RADSIM_PROVIDER="openrouter"\n'
        'RADSIM_MODEL="deepseek/deepseek-v4-flash"\n'
        'OPENROUTER_API_KEY="test-key"\n'
    )

    save_last_model_selection("openrouter", "z-ai/glm-5.2")
    config = load_config()

    assert config.model == "z-ai/glm-5.2"


def test_process_model_override_wins_over_last_selection(tmp_path, monkeypatch):
    from radsim.config import load_config, save_last_model_selection

    _isolate_config(tmp_path, monkeypatch)
    save_last_model_selection("openrouter", "z-ai/glm-5.2")
    monkeypatch.setenv("RADSIM_API_KEY", "test-key")
    monkeypatch.setenv("RADSIM_MODEL", "moonshotai/kimi-k3")

    config = load_config()

    assert config.model == "moonshotai/kimi-k3"


def test_model_preference_rejects_terminal_controls(tmp_path, monkeypatch):
    from radsim.config import save_last_model_selection

    _isolate_config(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="invalid"):
        save_last_model_selection("openrouter", "z-ai/glm-5.2\u202ehidden")
