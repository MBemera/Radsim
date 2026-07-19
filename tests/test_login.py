"""Tests for radsim.login (API-key wizard)."""

import pytest

from radsim import login as login_module


def test_run_login_unknown_provider_returns_2():
    assert login_module.run_login("nope") == 2


def test_run_login_rejects_dropped_providers():
    # gemini and vertex were removed; ensure they're rejected.
    assert login_module.run_login("gemini") == 2
    assert login_module.run_login("vertex") == 2


def test_known_providers():
    assert set(login_module.PROVIDERS) == {"openrouter", "openai", "claude"}


def test_run_logout_unknown_provider_returns_2():
    assert login_module.run_logout("nope") == 2


@pytest.fixture
def isolated_radsim_home(tmp_path, monkeypatch):
    fake_home = tmp_path / ".radsim"
    fake_home.mkdir()
    monkeypatch.setattr("radsim.config.CONFIG_DIR", fake_home)
    monkeypatch.setattr("radsim.config.ENV_FILE", fake_home / ".env")
    monkeypatch.setattr("radsim.config.SETTINGS_FILE", fake_home / "settings.json")
    monkeypatch.setattr("radsim.login.ENV_FILE", fake_home / ".env")
    return fake_home


def test_run_logout_removes_key_from_env(isolated_radsim_home):
    env_file = isolated_radsim_home / ".env"
    env_file.write_text(
        '# RadSim Configuration\n'
        'RADSIM_PROVIDER="openai"\n'
        'OPENAI_API_KEY="sk-test"\n'
    )
    env_file.chmod(0o600)

    rc = login_module.run_logout("openai")
    assert rc == 0
    assert "OPENAI_API_KEY" not in env_file.read_text()


def test_login_preserves_current_model_selection(isolated_radsim_home):
    env_file = isolated_radsim_home / ".env"
    env_file.write_text(
        'RADSIM_PROVIDER="openrouter"\n'
        'RADSIM_MODEL="z-ai/glm-5.2"\n'
        'OPENROUTER_API_KEY="old-key"\n'
    )

    login_module._write_key("OPENROUTER_API_KEY", "new-key", "openrouter")

    content = env_file.read_text()
    assert 'RADSIM_MODEL="z-ai/glm-5.2"' in content
    assert 'OPENROUTER_API_KEY="new-key"' in content


def test_logout_other_provider_preserves_current_model(isolated_radsim_home):
    env_file = isolated_radsim_home / ".env"
    env_file.write_text(
        'RADSIM_PROVIDER="openrouter"\n'
        'RADSIM_MODEL="z-ai/glm-5.2"\n'
        'OPENROUTER_API_KEY="openrouter-key"\n'
        'OPENAI_API_KEY="openai-key"\n'
    )

    assert login_module.run_logout("openai") == 0

    content = env_file.read_text()
    assert 'RADSIM_PROVIDER="openrouter"' in content
    assert 'RADSIM_MODEL="z-ai/glm-5.2"' in content
    assert "OPENAI_API_KEY" not in content
