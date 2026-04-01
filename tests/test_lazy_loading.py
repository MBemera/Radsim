"""Regression tests for lazy-loading boundaries."""

import importlib
import json
import subprocess
import sys


def run_python(code):
    """Run a short Python snippet in a clean interpreter."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )


def test_import_radsim_does_not_load_runtime_modules():
    """Package import should stay lightweight until exports are accessed."""
    code = """
import json
import sys
import radsim

module_names = [
    "radsim.health",
    "radsim.hooks",
    "radsim.model_router",
    "radsim.skill_registry",
    "radsim.sub_agent",
    "radsim.task_logger",
    "radsim.vector_memory",
]
print(json.dumps({name: name in sys.modules for name in module_names}))
"""
    result = run_python(code)
    loaded_modules = json.loads(result.stdout.strip())
    assert all(not is_loaded for is_loaded in loaded_modules.values())


def test_import_radsim_cli_does_not_load_agent_module():
    """CLI import should not build the full agent stack."""
    code = """
import json
import sys
import radsim.cli

module_names = [
    "radsim.agent",
    "radsim.config",
    "radsim.output",
]
print(json.dumps({name: name in sys.modules for name in module_names}))
"""
    result = run_python(code)
    loaded_modules = json.loads(result.stdout.strip())
    assert loaded_modules["radsim.agent"] is False
    assert loaded_modules["radsim.config"] is False
    assert loaded_modules["radsim.output"] is False


def test_import_radsim_tools_does_not_load_tool_modules():
    """Tool package import should keep tool implementations unloaded."""
    code = """
import json
import sys
import radsim.tools

module_names = [
    "radsim.tools.file_ops",
    "radsim.tools.search",
    "radsim.tools.shell",
    "radsim.tools.git",
]
print(json.dumps({name: name in sys.modules for name in module_names}))
"""
    result = run_python(code)
    loaded_modules = json.loads(result.stdout.strip())
    assert all(not is_loaded for is_loaded in loaded_modules.values())


def test_package_export_loads_on_first_access():
    """Accessing a lazily exported name should load only its source module."""
    import radsim

    sys.modules.pop("radsim.skill_registry", None)

    load_skill = radsim.load_skill

    assert callable(load_skill)
    assert "radsim.skill_registry" in sys.modules


def test_execute_tool_imports_module_on_demand(tmp_path, monkeypatch):
    """Dispatcher should import the implementation module only when needed."""
    from radsim import tools

    monkeypatch.chdir(tmp_path)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    imported_modules = []
    original_import_module = importlib.import_module

    def tracking_import(module_name, package=None):
        imported_modules.append((module_name, package))
        return original_import_module(module_name, package)

    monkeypatch.setattr(tools, "import_module", tracking_import)

    result = tools.execute_tool("read_file", {"file_path": "hello.txt"})

    assert result["success"] is True
    assert result["content"] == "hello"
    assert (".file_ops", "radsim.tools") in imported_modules
