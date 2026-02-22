"""Tests for the Mode management system."""


from radsim.modes import Mode, ModeManager


class TestMode:
    """Test Mode dataclass."""

    def test_mode_creation(self):
        mode = Mode(name="test", description="A test mode", shortcut="/test")
        assert mode.name == "test"
        assert mode.description == "A test mode"
        assert mode.shortcut == "/test"
        assert mode.prompt_addition == ""

    def test_mode_with_prompt(self):
        mode = Mode(
            name="verbose",
            description="Verbose mode",
            shortcut="/v",
            prompt_addition="Be very detailed.",
        )
        assert mode.prompt_addition == "Be very detailed."


class TestModeManager:
    """Test ModeManager toggle and query logic."""

    def setup_method(self):
        self.manager = ModeManager()

    def test_default_modes_registered(self):
        modes = self.manager.get_all_modes()
        mode_names = [m.name for m in modes]
        assert "teach" in mode_names
        assert "verbose" in mode_names

    def test_toggle_on(self):
        is_active, message = self.manager.toggle("teach")
        assert is_active is True
        assert "ON" in message

    def test_toggle_off(self):
        self.manager.toggle("teach")  # on
        is_active, message = self.manager.toggle("teach")  # off
        assert is_active is False
        assert "OFF" in message

    def test_is_active(self):
        assert self.manager.is_active("teach") is False
        self.manager.toggle("teach")
        assert self.manager.is_active("teach") is True

    def test_is_active_case_insensitive(self):
        self.manager.toggle("teach")
        assert self.manager.is_active("TEACH") is True
        assert self.manager.is_active("Teach") is True

    def test_unknown_mode_returns_error(self):
        is_active, message = self.manager.toggle("nonexistent")
        assert is_active is False
        assert "Unknown mode" in message

    def test_get_active_modes(self):
        assert self.manager.get_active_modes() == []
        self.manager.toggle("teach")
        assert "teach" in self.manager.get_active_modes()

    def test_get_prompt_additions(self):
        assert self.manager.get_prompt_additions() == ""
        self.manager.toggle("teach")
        additions = self.manager.get_prompt_additions()
        assert len(additions) > 0
        assert "TEACH MODE" in additions

    def test_clear_all(self):
        self.manager.toggle("teach")
        self.manager.toggle("verbose")
        assert len(self.manager.get_active_modes()) == 2

        self.manager.clear_all()
        assert len(self.manager.get_active_modes()) == 0

    def test_register_custom_mode(self):
        custom = Mode(name="debug", description="Debug mode", shortcut="/d")
        self.manager.register(custom)

        is_active, msg = self.manager.toggle("debug")
        assert is_active is True

    def test_get_mode(self):
        mode = self.manager.get_mode("teach")
        assert mode is not None
        assert mode.name == "teach"

    def test_get_mode_nonexistent(self):
        mode = self.manager.get_mode("fake")
        assert mode is None

    def test_on_activate_callback(self):
        activated = []
        custom = Mode(
            name="callback_test",
            description="Test",
            shortcut="/cb",
            on_activate=lambda: activated.append(True),
        )
        self.manager.register(custom)
        self.manager.toggle("callback_test")
        assert activated == [True]

    def test_on_deactivate_callback(self):
        deactivated = []
        custom = Mode(
            name="deactivate_test",
            description="Test",
            shortcut="/dt",
            on_deactivate=lambda: deactivated.append(True),
        )
        self.manager.register(custom)
        self.manager.toggle("deactivate_test")  # on
        self.manager.toggle("deactivate_test")  # off
        assert deactivated == [True]
