"""Regression tests for agent safety confirmations."""

from types import SimpleNamespace

from radsim.agent import RadSimAgent


def build_agent(auto_confirm=False):
    """Create a minimal agent instance for handler tests."""
    agent = object.__new__(RadSimAgent)
    agent.config = SimpleNamespace(auto_confirm=auto_confirm, trust_mode="medium", verbose=False)
    agent._rejected_writes = set()
    agent._mcp_manager = None
    return agent


def test_write_file_rejection_stops_without_executing(monkeypatch):
    agent = build_agent(auto_confirm=False)
    execute_calls = []

    monkeypatch.setattr("radsim.agent.confirm_write", lambda *args, **kwargs: False)
    monkeypatch.setattr("radsim.agent.is_path_safe", lambda file_path: (True, None))
    monkeypatch.setattr("radsim.modes.is_mode_active", lambda mode: False)
    monkeypatch.setattr(
        "radsim.response_validator.validate_content_for_write",
        lambda content, file_ext: (True, None),
    )
    monkeypatch.setattr("radsim.safety.is_self_modification", lambda file_path: (False, None))
    monkeypatch.setattr(
        "radsim.agent.execute_tool",
        lambda tool_name, tool_input: execute_calls.append((tool_name, tool_input)),
    )

    result = agent._handle_write_file({"file_path": "demo.py", "content": "print('hi')\n"})

    assert result["success"] is False
    assert "STOPPED" in result["error"]
    assert "demo.py" in agent._rejected_writes
    assert execute_calls == []


def test_safe_shell_command_auto_confirm_skips_prompt(monkeypatch):
    agent = build_agent(auto_confirm=True)
    confirm_calls = []

    monkeypatch.setattr(
        "radsim.agent.confirm_action",
        lambda *args, **kwargs: confirm_calls.append((args, kwargs)) or True,
    )
    monkeypatch.setattr(
        "radsim.agent.execute_tool",
        lambda tool_name, tool_input: {"success": True, "returncode": 0, "stdout": "", "stderr": ""},
    )

    result = agent._handle_shell_command({"command": "echo hello"})

    assert result["success"] is True
    assert confirm_calls == []


def test_destructive_shell_command_still_requires_confirmation(monkeypatch):
    agent = build_agent(auto_confirm=True)
    confirm_calls = []
    execute_calls = []

    monkeypatch.setattr(
        "radsim.agent.confirm_action",
        lambda *args, **kwargs: confirm_calls.append((args, kwargs)) or False,
    )
    monkeypatch.setattr(
        "radsim.agent.execute_tool",
        lambda tool_name, tool_input: execute_calls.append((tool_name, tool_input)),
    )

    result = agent._handle_shell_command({"command": "rm -rf build"})

    assert result["success"] is False
    assert "STOPPED" in result["error"]
    assert len(confirm_calls) == 1
    assert execute_calls == []


def test_git_commit_rejection_preserved(monkeypatch):
    agent = build_agent(auto_confirm=False)
    confirm_calls = []
    execute_calls = []

    monkeypatch.setattr(
        "radsim.agent.confirm_action",
        lambda *args, **kwargs: confirm_calls.append((args, kwargs)) or False,
    )
    monkeypatch.setattr(
        "radsim.agent.execute_tool",
        lambda tool_name, tool_input: execute_calls.append((tool_name, tool_input)),
    )

    result = agent._handle_git_commit({"message": "test commit", "amend": False})

    assert result["success"] is False
    assert "STOPPED" in result["error"]
    assert len(confirm_calls) == 1
    assert execute_calls == []


def test_web_fetch_rejection_preserved(monkeypatch):
    agent = build_agent(auto_confirm=False)
    confirm_calls = []
    execute_calls = []

    monkeypatch.setattr(
        "radsim.agent.confirm_action",
        lambda *args, **kwargs: confirm_calls.append((args, kwargs)) or False,
    )
    monkeypatch.setattr(
        "radsim.agent.execute_tool",
        lambda tool_name, tool_input: execute_calls.append((tool_name, tool_input)),
    )

    result = agent._handle_web_fetch({"url": "https://example.com"})

    assert result["success"] is False
    assert "STOPPED" in result["error"]
    assert len(confirm_calls) == 1
    assert execute_calls == []


def test_generic_confirmation_uses_trust_bandit(monkeypatch):
    agent = build_agent(auto_confirm=False)
    confirm_calls = []

    def fake_confirm_with_bandit(tool_name, tool_input, message, config=None):
        confirm_calls.append((tool_name, tool_input, message, config))
        return True

    monkeypatch.setattr(
        "radsim.trust_bandit_integration.confirm_with_bandit",
        fake_confirm_with_bandit,
    )
    monkeypatch.setattr(
        "radsim.agent_policy.execute_tool",
        lambda tool_name, tool_input: {"success": True},
    )

    result = agent._run_tool_with_confirmation(
        "type_check",
        {"file_path": "src/example.py"},
        "Type check src/example.py",
    )

    assert result["success"] is True
    assert len(confirm_calls) == 1
    assert confirm_calls[0][0] == "type_check"
