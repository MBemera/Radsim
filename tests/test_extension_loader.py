"""Security and lifecycle tests for trusted extension loading."""

import json
from pathlib import Path

import pytest

from radsim.agent_config import AgentConfigManager
from radsim.commands import CommandRegistry
from radsim.extension_loader import ExtensionLoader, validate_manifest_data
from radsim.tools import execute_tool


def extension_source(tool_name, version="one", *, sentinel=None):
    prefix = ""
    if sentinel is not None:
        prefix = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n\n"
    return (
        prefix
        + f"VERSION = {version!r}\n\n"
        + "def setup(api):\n"
        + "    def execute(tool_input):\n"
        + "        return {'success': True, 'version': VERSION}\n"
        + "    api.register_tool(\n"
        + "        {\n"
        + f"            'name': {tool_name!r},\n"
        + "            'description': 'Test loader tool',\n"
        + "            'input_schema': {'type': 'object', 'properties': {}, 'required': []},\n"
        + "        },\n"
        + "        execute,\n"
        + "        'read_only',\n"
        + "    )\n"
    )


def write_extension(
    root: Path,
    extension_id: str,
    *,
    source: str,
    version="1.0.0",
    permissions=None,
    tests="",
):
    directory = root / extension_id
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": extension_id,
        "name": extension_id.replace("-", " ").title(),
        "version": version,
        "entrypoint": "extension.py",
        "permissions": permissions or ["tools.register"],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "extension.py").write_text(source)
    if tests:
        (directory / "test_extension.py").write_text(tests)
    return directory


@pytest.fixture
def enabled_loader(tmp_path, monkeypatch):
    import radsim.agent_config as agent_config

    manager = AgentConfigManager(config_dir=tmp_path / "config")
    manager.set("tools.self_extension", True)
    monkeypatch.setattr(agent_config, "_agent_config_manager", manager)
    loader = ExtensionLoader(
        CommandRegistry(),
        global_root=tmp_path / "global",
        project_root=tmp_path / "project" / ".radsim" / "extensions",
        state_file=tmp_path / "approvals.json",
    )
    yield loader
    for loaded in list(loader.loaded.values()):
        loaded.api.deactivate()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"id": "../bad"}, "id"),
        ({"version": "1.0"}, "semantic"),
        ({"permissions": ["network.unrestricted"]}, "Unknown"),
        ({"entrypoint": "../escape.py"}, "inside"),
    ],
)
def test_manifest_validation_fails_closed(change, message):
    manifest = {
        "id": "valid-extension",
        "name": "Valid Extension",
        "version": "1.0.0",
        "entrypoint": "extension.py",
        "permissions": [],
    }
    manifest.update(change)

    with pytest.raises(ValueError, match=message):
        validate_manifest_data(manifest)


def test_discovery_parses_manifest_before_executing_code(enabled_loader, tmp_path):
    sentinel = tmp_path / "executed"
    write_extension(
        enabled_loader.global_root,
        "discover-only",
        source=extension_source("discover_tool", sentinel=sentinel),
    )

    candidates = enabled_loader.discover()

    assert [candidate.manifest.extension_id for candidate in candidates] == [
        "discover-only"
    ]
    assert not sentinel.exists()
    assert enabled_loader.load("discover-only")["success"] is False
    assert not sentinel.exists()


def test_discovery_rejects_extension_directory_symlink_escape(
    enabled_loader,
    tmp_path,
):
    outside = tmp_path / "outside"
    write_extension(
        outside,
        "linked-extension",
        source=extension_source("linked_tool"),
    )
    enabled_loader.global_root.mkdir(parents=True)
    (enabled_loader.global_root / "linked-extension").symlink_to(
        outside / "linked-extension",
        target_is_directory=True,
    )

    assert enabled_loader.discover() == []


def test_discovery_rejects_entrypoint_symlink_escape(enabled_loader, tmp_path):
    directory = enabled_loader.global_root / "entrypoint-link"
    directory.mkdir(parents=True)
    outside_source = tmp_path / "outside.py"
    outside_source.write_text(extension_source("escaped_tool"))
    (directory / "extension.py").symlink_to(outside_source)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "id": "entrypoint-link",
                "name": "Entrypoint Link",
                "version": "1.0.0",
                "entrypoint": "extension.py",
                "permissions": ["tools.register"],
            }
        )
    )

    assert enabled_loader.discover() == []


def test_global_extension_requires_exact_approval(enabled_loader, tmp_path):
    sentinel = tmp_path / "loaded"
    write_extension(
        enabled_loader.global_root,
        "approved-global",
        source=extension_source("approved_tool", sentinel=sentinel),
    )

    assert enabled_loader.approve("approved-global")["success"] is True
    assert not sentinel.exists()
    assert enabled_loader.load("approved-global")["success"] is True

    assert sentinel.read_text() == "executed"
    assert execute_tool("approved_tool", {})["version"] == "one"


def test_project_extension_requires_project_trust(enabled_loader, tmp_path):
    sentinel = tmp_path / "project-loaded"
    write_extension(
        enabled_loader.project_root,
        "project-extension",
        source=extension_source("project_tool", sentinel=sentinel),
    )

    approval = enabled_loader.approve("project-extension")
    assert approval["success"] is False
    assert "project trust" in approval["error"].lower()
    assert enabled_loader.load("project-extension")["success"] is False
    assert not sentinel.exists()

    trust = enabled_loader.trust_project()
    assert trust["success"] is True
    assert not sentinel.exists()
    assert enabled_loader.load("project-extension")["success"] is True
    assert sentinel.exists()


def test_source_or_permission_change_requires_another_approval(enabled_loader):
    directory = write_extension(
        enabled_loader.global_root,
        "changing-extension",
        source=extension_source("stable_tool", "one"),
    )
    enabled_loader.approve("changing-extension")
    enabled_loader.load("changing-extension")

    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["version"] = "1.1.0"
    manifest["permissions"].append("storage.read_write")
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "extension.py").write_text(extension_source("stable_tool", "two"))

    result = enabled_loader.reload("changing-extension")

    assert result["success"] is False
    assert "approval" in result["error"].lower()
    assert execute_tool("stable_tool", {})["version"] == "one"


def test_change_to_importable_helper_requires_another_approval(enabled_loader):
    directory = write_extension(
        enabled_loader.global_root,
        "helper-extension",
        source=extension_source("helper_tool"),
    )
    helper = directory / "helper.py"
    helper.write_text("VALUE = 'one'\n")
    enabled_loader.approve("helper-extension")

    helper.write_text("VALUE = 'two'\n")

    result = enabled_loader.load("helper-extension")

    assert result["success"] is False
    assert "approval" in result["error"].lower()


def test_discovery_rejects_nested_file_symlink(enabled_loader, tmp_path):
    directory = write_extension(
        enabled_loader.global_root,
        "nested-link",
        source=extension_source("nested_link_tool"),
    )
    outside = tmp_path / "outside-helper.py"
    outside.write_text("VALUE = 'outside'\n")
    (directory / "helper.py").symlink_to(outside)

    assert enabled_loader.discover() == []


def test_failed_reload_preserves_last_working_registrations(enabled_loader):
    directory = write_extension(
        enabled_loader.global_root,
        "reload-fallback",
        source=extension_source("fallback_tool", "working"),
    )
    enabled_loader.approve("reload-fallback")
    enabled_loader.load("reload-fallback")

    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["version"] = "2.0.0"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "extension.py").write_text(
        "def setup(api):\n    raise RuntimeError('broken reload')\n"
    )
    enabled_loader.approve("reload-fallback")

    result = enabled_loader.reload("reload-fallback")

    assert result["success"] is False
    assert "previous version remains active" in result["error"]
    assert execute_tool("fallback_tool", {})["version"] == "working"


def test_reload_removes_stale_owned_tools(enabled_loader):
    directory = write_extension(
        enabled_loader.global_root,
        "clean-reload",
        source=extension_source("removed_tool", "old"),
    )
    enabled_loader.approve("clean-reload")
    enabled_loader.load("clean-reload")

    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["version"] = "1.1.0"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "extension.py").write_text(extension_source("replacement_tool", "new"))
    enabled_loader.approve("clean-reload")

    assert enabled_loader.reload("clean-reload")["success"] is True
    assert execute_tool("removed_tool", {})["success"] is False
    assert execute_tool("replacement_tool", {})["version"] == "new"


def test_duplicate_ids_are_deterministic_and_never_execute(enabled_loader):
    write_extension(
        enabled_loader.global_root,
        "duplicate-extension",
        source=extension_source("global_duplicate"),
    )
    write_extension(
        enabled_loader.project_root,
        "duplicate-extension",
        source=extension_source("project_duplicate"),
    )

    result = enabled_loader.approve("duplicate-extension")

    assert result["success"] is False
    assert result["error"] == (
        "Duplicate extension id 'duplicate-extension' in: global, project"
    )


def test_unload_removes_extension_entries_but_not_builtins(enabled_loader):
    write_extension(
        enabled_loader.global_root,
        "unload-extension",
        source=extension_source("temporary_tool"),
    )
    enabled_loader.approve("unload-extension")
    enabled_loader.load("unload-extension")

    assert enabled_loader.unload("unload-extension")["success"] is True
    assert execute_tool("temporary_tool", {})["success"] is False
    assert "/help" in enabled_loader.command_registry.commands
    assert execute_tool("git_status", {})["success"] in (True, False)


def test_staged_install_and_one_command_rollback(enabled_loader):
    first_stage = write_extension(
        enabled_loader.staging_root,
        "staged-extension",
        source=extension_source("staged_tool", "one"),
        tests="from extension import VERSION\nassert VERSION == 'one'\n",
    )

    first = enabled_loader.install_staged_extension(first_stage)

    assert first["success"] is True
    assert execute_tool("staged_tool", {})["version"] == "one"
    assert not first_stage.exists()

    second_stage = write_extension(
        enabled_loader.staging_root,
        "staged-extension",
        source=extension_source("staged_tool", "two"),
        version="2.0.0",
        tests="from extension import VERSION\nassert VERSION == 'two'\n",
    )
    second = enabled_loader.install_staged_extension(second_stage)
    assert second["success"] is True
    assert execute_tool("staged_tool", {})["version"] == "two"

    rollback = enabled_loader.rollback("staged-extension")

    assert rollback["success"] is True
    assert execute_tool("staged_tool", {})["version"] == "one"


def test_failed_staged_validation_never_enters_active_directory(enabled_loader):
    stage = write_extension(
        enabled_loader.staging_root,
        "failed-stage",
        source=extension_source("failed_stage_tool"),
        tests="raise AssertionError('nope')\n",
    )

    result = enabled_loader.install_staged_extension(stage)

    assert result["success"] is False
    assert not (enabled_loader.global_root / "failed-stage").exists()
    assert execute_tool("failed_stage_tool", {})["success"] is False


def test_staged_test_symlink_is_rejected_without_execution(enabled_loader, tmp_path):
    sentinel = tmp_path / "test-executed"
    stage = write_extension(
        enabled_loader.staging_root,
        "linked-stage-test",
        source=extension_source("linked_stage_tool"),
    )
    outside_test = tmp_path / "outside-test.py"
    outside_test.write_text(f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n")
    (stage / "test_extension.py").symlink_to(outside_test)

    result = enabled_loader.install_staged_extension(stage)

    assert result["success"] is False
    assert not sentinel.exists()
    assert not (enabled_loader.global_root / "linked-stage-test").exists()


def test_self_extension_setting_blocks_activation(enabled_loader, monkeypatch):
    import radsim.agent_config as agent_config

    agent_config.get_agent_config_manager().set("tools.self_extension", False)
    write_extension(
        enabled_loader.global_root,
        "disabled-extension",
        source=extension_source("disabled_tool"),
    )
    enabled_loader.approve("disabled-extension")

    assert enabled_loader.load("disabled-extension") == {
        "success": False,
        "error": "Self-extension is disabled",
    }
    assert not enabled_loader.load_approved()
    assert enabled_loader.reload("disabled-extension") == {
        "success": False,
        "error": "Self-extension is disabled",
    }
    assert enabled_loader.rollback("disabled-extension") == {
        "success": False,
        "error": "Self-extension is disabled",
    }
