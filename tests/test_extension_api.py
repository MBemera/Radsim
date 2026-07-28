"""Tests for the minimal extension facade over RadSim's live registries."""

from types import SimpleNamespace

import pytest

from radsim.agent_config import AgentConfigManager
from radsim.agent_policy import AgentPolicyMixin
from radsim.commands import CommandRegistry
from radsim.extension_api import ExtensionAPI
from radsim.hooks import HookContext, HookType, get_hooks_manager
from radsim.tools import (
    execute_tool,
    get_extension_tool_metadata,
)


def tool_definition(name, *, properties=None, required=None):
    return {
        "name": name,
        "description": f"Test extension tool {name}",
        "input_schema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
    }


@pytest.fixture
def extension_config(tmp_path, monkeypatch):
    import radsim.agent_config as agent_config

    manager = AgentConfigManager(config_dir=tmp_path / "config")
    manager.set("tools.self_extension", True)
    monkeypatch.setattr(agent_config, "_agent_config_manager", manager)
    return manager


def test_api_registers_and_removes_owned_entries(tmp_path):
    registry = CommandRegistry()
    observed = []
    api = ExtensionAPI(
        "sample-extension",
        {
            "tools.register",
            "commands.register",
            "hooks.observe",
            "storage.read_write",
        },
        registry,
        storage_root=tmp_path / "storage",
    )
    api.register_tool(
        tool_definition(
            "sample_lookup",
            properties={"query": {"type": "string"}},
            required=["query"],
        ),
        lambda tool_input: {"success": True, "value": tool_input["query"].upper()},
        "read_only",
    )
    api.register_command(
        "sample-command",
        lambda agent: setattr(agent, "command_called", True),
        "Run sample command",
    )
    api.on("post_tool", lambda context: observed.append(context.tool_name))
    storage = api.get_extension_storage()
    storage["count"] = 2

    api.activate()

    assert execute_tool("sample_lookup", {"query": "hello"}) == {
        "success": True,
        "value": "HELLO",
    }
    metadata = get_extension_tool_metadata("sample_lookup")
    assert metadata["owner"] == "extension:sample-extension"
    assert metadata["permission_tier"] == "read_only"
    agent = SimpleNamespace(command_called=False)
    assert registry.handle_input("/sample-command", agent) is True
    assert agent.command_called is True
    get_hooks_manager().execute(
        HookType.POST_TOOL,
        HookContext(hook_type=HookType.POST_TOOL, tool_name="sample_lookup"),
    )
    assert observed == ["sample_lookup"]
    assert dict(storage) == {"count": 2}

    api.deactivate()

    assert execute_tool("sample_lookup", {})["success"] is False
    assert "/sample-command" not in registry.commands
    assert all(
        owner != "extension:sample-extension"
        for owner in get_hooks_manager()._owners.values()
    )
    assert "/help" in registry.commands


def test_api_rejects_registry_conflicts_without_touching_builtins():
    registry = CommandRegistry()
    api = ExtensionAPI(
        "conflicting-extension",
        {"tools.register", "commands.register"},
        registry,
    )
    api.register_tool(
        tool_definition("read_file"),
        lambda tool_input: {"success": True},
        "read_only",
    )
    api.register_command("help", lambda agent: None, "Conflict")

    with pytest.raises(ValueError, match="Tool already registered"):
        api.preflight()

    assert "/help" in registry.commands
    assert execute_tool("read_file", {"file_path": "missing"})["success"] is False


@pytest.mark.parametrize(
    ("definition", "tier", "message"),
    [
        ({"name": "Bad", "description": "x", "input_schema": {}}, "read_only", "name"),
        (tool_definition("valid_tool"), "tier-zero", "permission_tier"),
        (
            tool_definition(
                "unsafe_reader",
                properties={"command": {"type": "string"}},
            ),
            "read_only",
            "command input",
        ),
    ],
)
def test_api_rejects_invalid_tool_contracts(definition, tier, message):
    api = ExtensionAPI("validation-extension", {"tools.register"}, CommandRegistry())
    if message == "command input":
        api.register_tool(definition, lambda value: {"success": True}, tier)
        with pytest.raises(ValueError, match=message):
            api.activate()
    else:
        with pytest.raises(ValueError, match=message):
            api.register_tool(definition, lambda value: {"success": True}, tier)


def test_extension_can_toggle_only_its_own_tool():
    registry = CommandRegistry()
    first = ExtensionAPI("first-extension", {"tools.register"}, registry)
    second = ExtensionAPI("second-extension", {"tools.register"}, registry)
    first.register_tool(
        tool_definition("first_lookup"),
        lambda value: {"success": True},
        "read_only",
    )
    first.activate()

    first.set_extension_tool_active("first_lookup", False)
    assert execute_tool("first_lookup", {})["success"] is False
    with pytest.raises(ValueError, match="does not own"):
        second.set_extension_tool_active("first_lookup", True)

    first.deactivate()


def test_registered_tool_contract_is_copied_and_result_is_bounded():
    definition = tool_definition(
        "stable_contract",
        properties={"query": {"type": "string"}},
        required=["query"],
    )
    api = ExtensionAPI("stable-contract", {"tools.register"}, CommandRegistry())
    api.register_tool(
        definition,
        lambda value: {"success": True, "payload": "x" * (600 * 1024)},
        "read_only",
    )
    definition["input_schema"]["required"].clear()
    api.activate()

    assert execute_tool("stable_contract", {})["error"].startswith("Missing required")
    assert "size limit" in execute_tool("stable_contract", {"query": "value"})["error"]
    api.deactivate()


class _PolicyAgent(AgentPolicyMixin):
    def __init__(self):
        self.config = SimpleNamespace(auto_confirm=True)
        self._mcp_manager = None

    def _warn_if_known_error(self, tool_name, tool_input):
        return None


def test_mutation_tool_cannot_bypass_confirmation(
    extension_config,
    monkeypatch,
):
    calls = []
    api = ExtensionAPI("mutation-extension", {"tools.register"}, CommandRegistry())
    api.register_tool(
        tool_definition("mutating_extension_tool"),
        lambda value: calls.append(value) or {"success": True},
        "mutation",
    )
    api.activate()
    monkeypatch.setattr("radsim.agent_policy.confirm_action", lambda *args, **kwargs: False)

    result = _PolicyAgent()._dispatch_tool("mutating_extension_tool", {})

    assert result["success"] is False
    assert "STOPPED" in result["error"]
    assert calls == []
    api.deactivate()


def test_mutation_tool_flows_through_hooks_and_undo(
    extension_config,
    tmp_path,
    monkeypatch,
):
    import radsim.undo as undo

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(undo, "UNDO_ROOT", tmp_path / "undo")
    monkeypatch.setattr("radsim.agent_policy.confirm_action", lambda *args, **kwargs: True)
    target = tmp_path / "owned.txt"
    target.write_text("before")

    api = ExtensionAPI("undo-extension", {"tools.register"}, CommandRegistry())

    def mutate(tool_input):
        target_path = tmp_path / tool_input["file_path"]
        target_path.write_text("after")
        return {"success": True}

    api.register_tool(
        tool_definition(
            "extension_file_update",
            properties={"file_path": {"type": "string"}},
            required=["file_path"],
        ),
        mutate,
        "mutation",
    )
    api.activate()

    result = _PolicyAgent()._execute_with_permission(
        "extension_file_update",
        {"file_path": "owned.txt"},
    )

    assert result["success"] is True
    assert target.read_text() == "after"
    assert undo.undo_last()["success"] is True
    assert target.read_text() == "before"
    api.deactivate()


def test_extension_storage_is_bounded_and_namespaced(tmp_path):
    first = ExtensionAPI(
        "storage-first",
        {"storage.read_write"},
        CommandRegistry(),
        storage_root=tmp_path,
    ).get_extension_storage()
    second = ExtensionAPI(
        "storage-second",
        {"storage.read_write"},
        CommandRegistry(),
        storage_root=tmp_path,
    ).get_extension_storage()
    first["value"] = "one"
    second["value"] = "two"

    assert first["value"] == "one"
    assert second["value"] == "two"
    with pytest.raises(ValueError, match="limited"):
        first["large"] = "x" * (70 * 1024)


def test_observe_hooks_cannot_modify_live_context():
    api = ExtensionAPI(
        "observer-extension",
        {"hooks.observe"},
        CommandRegistry(),
    )

    def try_to_block(context):
        context.should_proceed = False
        context.metadata["changed"] = True
        context.metadata["nested"]["items"].append("changed")
        context.tool_input["nested"]["value"] = "changed"

    api.on("post_tool", try_to_block)
    api.activate()
    original = HookContext(
        hook_type=HookType.POST_TOOL,
        tool_input={"nested": {"value": "original"}},
        metadata={"original": True, "nested": {"items": []}},
    )

    result = get_hooks_manager().execute(HookType.POST_TOOL, original)

    assert result.should_proceed is True
    assert result.metadata == {"original": True, "nested": {"items": []}}
    assert result.tool_input == {"nested": {"value": "original"}}
    api.deactivate()
