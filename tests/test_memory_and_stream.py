"""Tests for memory persistence and stream configuration."""

import json


class TestMemoryPersistence:
    """Test memory save/load functionality."""

    def test_memory_save_and_load(self, tmp_path, monkeypatch):
        """Test that memory saves and loads correctly."""
        # Setup fake memory directory
        fake_memory_dir = tmp_path / "memory"
        fake_memory_dir.mkdir()

        import radsim.config

        monkeypatch.setattr(radsim.config, "MEMORY_DIR", fake_memory_dir)

        # Reload memory module to use new path
        from radsim.memory import load_memory, save_memory

        # Force Memory to use the new directory
        monkeypatch.setattr("radsim.memory.MEMORY_DIR", fake_memory_dir)

        # Test save
        result = save_memory("test_key", "test_value", "preference")
        assert result["success"] is True
        assert result["key"] == "test_key"
        assert result["memory_type"] == "preference"

        # Test load
        result = load_memory("test_key", "preference")
        assert result["success"] is True
        assert result["data"] == "test_value"

    def test_memory_file_created(self, tmp_path, monkeypatch):
        """Test that memory file is actually created on disk."""
        fake_memory_dir = tmp_path / "memory"
        fake_memory_dir.mkdir()

        import radsim.config

        monkeypatch.setattr(radsim.config, "MEMORY_DIR", fake_memory_dir)
        monkeypatch.setattr("radsim.memory.MEMORY_DIR", fake_memory_dir)

        from radsim.memory import save_memory

        save_memory("persistent_key", "persistent_value", "preference")

        # Check file exists
        prefs_file = fake_memory_dir / "preferences.json"
        assert prefs_file.exists(), "Preferences file should be created"

        # Check content
        data = json.loads(prefs_file.read_text())
        assert "persistent_key" in data
        assert data["persistent_key"] == "persistent_value"


class TestStreamConfiguration:
    """Test stream configuration handling."""

    def test_stream_default_true(self, tmp_path, monkeypatch):
        """Test that stream defaults to True."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        import radsim.config

        config_dir = fake_home / ".radsim"
        config_dir.mkdir()

        monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(radsim.config, "SETTINGS_FILE", config_dir / "settings.json")
        monkeypatch.setattr(radsim.config, "ENV_FILE", config_dir / ".env")
        monkeypatch.setenv("RADSIM_API_KEY", "test-key")

        from radsim.config import load_config

        config = load_config(provider_override="openai")

        assert config.stream is True

    def test_stream_disabled_via_cli(self, tmp_path, monkeypatch):
        """Test that stream=False from CLI overrides settings."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        import radsim.config

        config_dir = fake_home / ".radsim"
        config_dir.mkdir()

        # Settings has stream=True
        settings_file = config_dir / "settings.json"
        settings_file.write_text(json.dumps({"stream": True}))

        monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(radsim.config, "SETTINGS_FILE", settings_file)
        monkeypatch.setattr(radsim.config, "ENV_FILE", config_dir / ".env")
        monkeypatch.setenv("RADSIM_API_KEY", "test-key")

        from radsim.config import load_config

        # CLI passes stream=False (--no-stream)
        config = load_config(provider_override="openai", stream=False)

        assert config.stream is False, "CLI --no-stream should override settings"

    def test_stream_from_settings(self, tmp_path, monkeypatch):
        """Test that stream value is read from settings.json."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        import radsim.config

        config_dir = fake_home / ".radsim"
        config_dir.mkdir()

        # Settings has stream=False
        settings_file = config_dir / "settings.json"
        settings_file.write_text(json.dumps({"stream": False}))

        monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(radsim.config, "SETTINGS_FILE", settings_file)
        monkeypatch.setattr(radsim.config, "ENV_FILE", config_dir / ".env")
        monkeypatch.setenv("RADSIM_API_KEY", "test-key")

        from radsim.config import load_config

        # CLI passes stream=True (default)
        config = load_config(provider_override="openai", stream=True)

        assert config.stream is False, (
            "Settings should override default when CLI doesn't explicitly disable"
        )


class TestMemoryHandlerIntegration:
    """Test that memory handler is properly routed."""

    def test_save_memory_in_confirmation_tools(self):
        """Test that save_memory is in CONFIRMATION_TOOLS."""
        from radsim.agent import CONFIRMATION_TOOLS

        assert "save_memory" in CONFIRMATION_TOOLS

    def test_schedule_task_in_confirmation_tools(self):
        """Test that schedule_task is in CONFIRMATION_TOOLS."""
        from radsim.agent import CONFIRMATION_TOOLS

        assert "schedule_task" in CONFIRMATION_TOOLS

    def test_handler_methods_exist(self):
        """Test that handler methods exist for memory tools."""
        from radsim.agent import RadSimAgent

        assert hasattr(RadSimAgent, "_handle_save_memory"), (
            "_handle_save_memory method should exist"
        )
        assert hasattr(RadSimAgent, "_handle_schedule_task"), (
            "_handle_schedule_task method should exist"
        )
