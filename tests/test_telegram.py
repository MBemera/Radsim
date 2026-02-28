"""Tests for radsim.telegram module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """Set up a fake ~/.radsim directory with a clean .env."""
    config_dir = tmp_path / ".radsim"
    config_dir.mkdir()
    env_file = config_dir / ".env"
    env_file.write_text(
        '# RadSim Configuration\n'
        'RADSIM_PROVIDER="openrouter"\n'
        'OPENROUTER_API_KEY="sk-test-key"\n'
    )
    env_file.chmod(0o600)

    import radsim.config
    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(radsim.config, "ENV_FILE", env_file)

    return env_file


# ---------------------------------------------------------------------------
# save_telegram_config
# ---------------------------------------------------------------------------


class TestSaveTelegramConfig:
    """Tests for save_telegram_config upsert and validation."""

    def test_fresh_save_appends_keys(self, fake_env):
        from radsim.telegram import save_telegram_config

        save_telegram_config("1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ", "7779435210")
        content = fake_env.read_text()

        assert 'TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ"' in content
        assert 'TELEGRAM_CHAT_ID="7779435210"' in content
        # Original keys preserved
        assert 'RADSIM_PROVIDER="openrouter"' in content
        assert 'OPENROUTER_API_KEY="sk-test-key"' in content

    def test_upsert_replaces_existing(self, fake_env):
        from radsim.telegram import save_telegram_config

        # First save
        save_telegram_config("1234567890:OldTokenOldToken", "1111111111")
        # Second save (update)
        save_telegram_config("1234567890:NewTokenNewToken", "2222222222")

        content = fake_env.read_text()
        # Old values gone
        assert "OldTokenOldToken" not in content
        assert "1111111111" not in content
        # New values present
        assert 'TELEGRAM_BOT_TOKEN="1234567890:NewTokenNewToken"' in content
        assert 'TELEGRAM_CHAT_ID="2222222222"' in content
        # Only one occurrence of each key
        assert content.count("TELEGRAM_BOT_TOKEN=") == 1
        assert content.count("TELEGRAM_CHAT_ID=") == 1

    def test_preserves_other_keys(self, fake_env):
        from radsim.telegram import save_telegram_config

        save_telegram_config("1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ", "7779435210")
        content = fake_env.read_text()

        assert 'RADSIM_PROVIDER="openrouter"' in content
        assert 'OPENROUTER_API_KEY="sk-test-key"' in content

    def test_rejects_empty_token(self, fake_env):
        from radsim.telegram import save_telegram_config

        with pytest.raises(ValueError, match="empty"):
            save_telegram_config("", "7779435210")

    def test_rejects_short_token(self, fake_env):
        from radsim.telegram import save_telegram_config

        with pytest.raises(ValueError, match="too short"):
            save_telegram_config("abc", "7779435210")

    def test_rejects_non_numeric_chat_id(self, fake_env):
        from radsim.telegram import save_telegram_config

        with pytest.raises(ValueError, match="numeric"):
            save_telegram_config("1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ", "not-a-number")

    def test_accepts_negative_chat_id(self, fake_env):
        """Group chat IDs can be negative."""
        from radsim.telegram import save_telegram_config

        save_telegram_config("1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ", "-1001234567890")
        content = fake_env.read_text()
        assert 'TELEGRAM_CHAT_ID="-1001234567890"' in content

    def test_file_permissions(self, fake_env):
        from radsim.telegram import save_telegram_config

        save_telegram_config("1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ", "7779435210")
        assert oct(fake_env.stat().st_mode & 0o777) == "0o600"


# ---------------------------------------------------------------------------
# load_telegram_config
# ---------------------------------------------------------------------------


class TestLoadTelegramConfig:
    """Tests for load_telegram_config."""

    def test_loads_saved_config(self, fake_env):
        from radsim.telegram import load_telegram_config, save_telegram_config

        save_telegram_config("1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ", "7779435210")
        token, chat_id = load_telegram_config()

        assert token == "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ"
        assert chat_id == "7779435210"

    def test_returns_none_when_missing(self, fake_env):
        from radsim.telegram import load_telegram_config

        token, chat_id = load_telegram_config()
        assert token is None
        assert chat_id is None


# ---------------------------------------------------------------------------
# send_telegram_message
# ---------------------------------------------------------------------------


class TestSendTelegramMessage:
    """Tests for send_telegram_message error handling."""

    def test_missing_token_returns_error(self, fake_env):
        from radsim.telegram import send_telegram_message

        result = send_telegram_message("hello")
        assert result["success"] is False
        assert "TELEGRAM_BOT_TOKEN" in result["error"]

    def test_missing_chat_id_returns_error(self, fake_env):
        from radsim.telegram import send_telegram_message

        # Write only token, no chat_id
        fake_env.write_text(
            fake_env.read_text() + '\nTELEGRAM_BOT_TOKEN="1234567890:FakeToken1234"\n'
        )
        result = send_telegram_message("hello")
        assert result["success"] is False
        assert "TELEGRAM_CHAT_ID" in result["error"]

    def test_empty_string_token_returns_error(self, fake_env):
        from radsim.telegram import send_telegram_message

        result = send_telegram_message("hello", token="", chat_id="123")
        assert result["success"] is False

    def test_http_401_gives_token_hint(self, fake_env):
        from urllib.error import HTTPError

        from radsim.telegram import send_telegram_message

        def mock_urlopen(*args, **kwargs):
            raise HTTPError(
                url="https://api.telegram.org", code=401,
                msg="Unauthorized", hdrs=None, fp=None,
            )

        with patch("radsim.telegram.urlopen", side_effect=mock_urlopen):
            result = send_telegram_message(
                "hello", token="1234567890:FakeToken1234", chat_id="123"
            )
        assert result["success"] is False
        assert "401" in result["error"]
        assert "token" in result["error"].lower()

    def test_http_400_gives_chat_id_hint(self, fake_env):
        from urllib.error import HTTPError

        from radsim.telegram import send_telegram_message

        def mock_urlopen(*args, **kwargs):
            raise HTTPError(
                url="https://api.telegram.org", code=400,
                msg="Bad Request", hdrs=None, fp=None,
            )

        with patch("radsim.telegram.urlopen", side_effect=mock_urlopen):
            result = send_telegram_message(
                "hello", token="1234567890:FakeToken1234", chat_id="123"
            )
        assert result["success"] is False
        assert "400" in result["error"]
        assert "chat_id" in result["error"].lower()
