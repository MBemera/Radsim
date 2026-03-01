from radsim.commands import CommandRegistry


class MockAgent:
    def __init__(self):
        self.reset_called = False
        self.system_prompt = "test prompt"

    def reset(self):
        self.reset_called = True

    def update_config(self, p, k, m):
        pass


def test_command_registry_registration():
    registry = CommandRegistry()

    def my_handler(agent):
        return "custom"

    registry.register("/custom", my_handler, "Custom command")
    assert "/custom" in registry.commands
    assert registry.commands["/custom"]["description"] == "Custom command"


def test_command_registry_execution():
    registry = CommandRegistry()
    agent = MockAgent()

    # Test built-in command execution
    result = registry.handle_input("/clear", agent)
    assert result is True
    assert agent.reset_called is True


def test_command_registry_aliases():
    registry = CommandRegistry()
    agent = MockAgent()

    # Test alias
    result = registry.handle_input("/c", agent)
    assert result is True
    assert agent.reset_called is True


def test_command_registry_non_command():
    registry = CommandRegistry()
    agent = MockAgent()

    result = registry.handle_input("hello world", agent)
    assert result is False


def test_help_with_topic(capsys):
    """Test that /help <topic> shows detailed help."""
    registry = CommandRegistry()
    agent = MockAgent()

    result = registry.handle_input("/help skill", agent)
    assert result is True
    output = capsys.readouterr().out
    assert "Custom Skills" in output
    assert "/skill" in output


def test_help_with_alias_topic(capsys):
    """Test that /h <topic> works the same as /help <topic>."""
    registry = CommandRegistry()
    agent = MockAgent()

    result = registry.handle_input("/h plan", agent)
    assert result is True
    output = capsys.readouterr().out
    assert "Plan Mode" in output


def test_help_unknown_topic(capsys):
    """Test that /help <unknown> shows 'not found' gracefully."""
    registry = CommandRegistry()
    agent = MockAgent()

    result = registry.handle_input("/help nonexistent", agent)
    assert result is True
    output = capsys.readouterr().out
    assert "No help found" in output
    assert "Available topics" in output


def test_help_no_args(capsys):
    """Test that /help with no args shows overview menu."""
    registry = CommandRegistry()
    agent = MockAgent()

    result = registry.handle_input("/help", agent)
    assert result is True
    output = capsys.readouterr().out
    assert "RadSim Help Menu" in output
    assert "/help <command>" in output


def test_detect_help_intent_skills():
    from radsim.commands import detect_help_intent

    assert detect_help_intent("how do I use skills?") == "skill"


def test_detect_help_intent_plan():
    from radsim.commands import detect_help_intent

    assert detect_help_intent("what does plan do?") == "plan"


def test_detect_help_intent_memory():
    from radsim.commands import detect_help_intent

    assert detect_help_intent("help with memory") == "memory"


def test_detect_help_intent_no_match():
    from radsim.commands import detect_help_intent

    assert detect_help_intent("write a python script") is None


def test_detect_help_intent_slash_command():
    from radsim.commands import detect_help_intent

    assert detect_help_intent("/help") is None


def test_detect_help_intent_empty():
    from radsim.commands import detect_help_intent

    assert detect_help_intent("") is None
    assert detect_help_intent(None) is None
