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
