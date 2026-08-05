"""Smoke test: every tool in TOOL_DEFINITIONS executes without raising.

Each tool is called with benign inputs in a temp workspace. Tools may
return success=False (missing binaries, no git repo, etc.) but must
always return a well-formed result dict and must be dispatchable —
an "Unknown tool" error means a definition/dispatch gap.

No network: web_fetch targets a closed local port, telegram's urlopen
is stubbed, and browser tools run with playwright disabled.
"""

import base64
import subprocess

import pytest

from radsim.tools import TOOL_DEFINITIONS, execute_tool


@pytest.fixture
def smoke_workspace(tmp_path, monkeypatch):
    """Hermetic workspace: all storage redirected, no network, tmp cwd."""
    import radsim.jobs
    import radsim.memory
    import radsim.skills
    import radsim.telegram
    import radsim.tools

    confdir = tmp_path / "confdir"
    monkeypatch.setattr(radsim.memory, "CONFIG_DIR", confdir)
    # schedule_task/list_schedules delegate to jobs.py; isolate its
    # store and never let the smoke run touch the real crontab.
    monkeypatch.setattr(radsim.jobs, "JOBS_FILE", confdir / "jobs.json")
    monkeypatch.setattr("radsim.jobs.sync_crontab", lambda: None)
    monkeypatch.setattr(radsim.skills, "SKILLS_FILE", confdir / "skills.json")

    # add_tool persists generated code — never let tests write into the package
    import radsim.tools.self_extend as self_extend

    custom_tools_copy = tmp_path / "custom_tools.py"
    custom_tools_copy.write_text(self_extend.CUSTOM_TOOLS_FILE.read_text())
    monkeypatch.setattr(self_extend, "CUSTOM_TOOLS_FILE", custom_tools_copy)
    # Browser tools lazy-import radsim.browser at call time; stub them so
    # tests exercise dispatch without launching a real (headed) Chromium.
    import radsim.browser

    def browser_disabled(*args, **kwargs):
        return {"success": False, "error": "browser disabled in tests"}

    for browser_fn in (
        "browser_open",
        "browser_click",
        "browser_type",
        "browser_screenshot",
    ):
        monkeypatch.setattr(radsim.browser, browser_fn, browser_disabled)

    def refuse_network(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(radsim.telegram, "urlopen", refuse_network, raising=False)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sample.py").write_text("def main():\n    return 1\n")
    (workspace / "notes.txt").write_text("hello notes\n")
    (workspace / "to_rename.txt").write_text("rename me\n")
    (workspace / "to_delete.txt").write_text("delete me\n")
    (workspace / "multi.txt").write_text("multi edit target\n")
    (workspace / "pixel.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        )
    )
    monkeypatch.chdir(workspace)
    return workspace


def build_smoke_inputs(ws):
    """Benign inputs for every defined tool."""
    return {
        "browser_open": {"url": "about:blank"},
        "browser_click": {"selector": "#button"},
        "browser_type": {"selector": "#field", "text": "x"},
        "browser_screenshot": {},
        "install_system_tool": {"tool_name": ""},
        "read_file": {"file_path": "sample.py"},
        "read_many_files": {"file_paths": ["sample.py", "notes.txt"]},
        "read_document": {"file_path": "notes.txt"},
        "read_image": {"file_path": "pixel.png"},
        "write_file": {"file_path": "generated.txt", "content": "generated\n"},
        "replace_in_file": {
            "file_path": "notes.txt",
            "old_string": "hello",
            "new_string": "hallo",
        },
        "rename_file": {"old_path": "to_rename.txt", "new_path": "renamed.txt"},
        "delete_file": {"file_path": "to_delete.txt"},
        "list_directory": {},
        "create_directory": {"directory_path": "newdir"},
        "glob_files": {"pattern": "*.py"},
        "grep_search": {"pattern": "def"},
        "search_files": {"pattern": "main"},
        "run_shell_command": {"command": "echo radsim_smoke"},
        "web_fetch": {"url": "http://127.0.0.1:9/"},
        "http_request": {"url": "http://127.0.0.1:9/", "method": "GET"},
        # Traversal path fails validation BEFORE screencapture would run —
        # the smoke test must never actually photograph the screen.
        "screen_capture": {"save_path": "../outside.png"},
        "git_status": {},
        "git_diff": {},
        "git_log": {},
        "git_branch": {},
        "find_definition": {"symbol": "main"},
        "find_references": {"symbol": "main"},
        "run_tests": {"test_command": "echo tests_ok"},
        "lint_code": {"file_path": "sample.py"},
        "format_code": {"file_path": "sample.py", "check_only": True},
        "type_check": {"file_path": "sample.py"},
        "git_add": {"all_files": True},
        "git_commit": {"message": "smoke"},
        "git_checkout": {},
        "git_stash": {"action": "list"},
        "list_dependencies": {},
        "add_dependency": {"package": ""},
        "remove_dependency": {"package": ""},
        "npm_install": {"package": ""},
        "pip_install": {"package": ""},
        "init_project": {"project_type": "python", "name": "smokeproj"},
        "get_project_info": {},
        "batch_replace": {"pattern": "zzz_no_match_zzz", "replacement": "x"},
        "plan_task": {"task_description": "add a helper function"},
        "save_context": {"context_data": {"focus": "smoke"}, "filename": "ctx.json"},
        "load_context": {"filename": "ctx.json"},
        "delegate_task": {"task_description": "summarize"},
        "submit_completion": {"summary": "smoke complete"},
        "add_skill": {"instruction": "Prefer explicit names", "category": "style"},
        "remove_skill": {"index": 1},
        "list_skills": {},
        "send_telegram": {"message": "smoke"},
        "analyze_code": {"file_path": "sample.py"},
        "run_docker": {"action": "ps"},
        "database_query": {"query": "SELECT 1", "database_path": "smoke.db"},
        "generate_tests": {"source_file": "sample.py"},
        "refactor_code": {
            "action": "rename",
            "file_path": "sample.py",
            "old_name": "main",
            "new_name": "run",
        },
        "deploy": {"check_only": True},
        "save_memory": {"key": "smoke", "value": "v", "memory_type": "preference"},
        "load_memory": {},
        "forget_memory": {"key": "smoke", "memory_type": "preference"},
        "add_tool": {
            "name": "smoke_tool",
            "description": "smoke test tool",
            "parameters": {},
            "body": "return {'success': True}",
        },
        "remove_tool": {"name": "smoke_tool"},
        "list_custom_tools": {},
        "schedule_task": {
            "name": "smoke",
            "schedule": "daily",
            "command": "echo hi",
        },
        "list_schedules": {},
        "todo_read": {},
        "todo_write": {
            "todos": [{"id": 1, "description": "smoke item", "status": "pending"}]
        },
        "repo_map": {},
        "apply_patch": {"patch": ""},
        "multi_edit": {
            "file_path": "multi.txt",
            "edits": [{"old_string": "multi edit", "new_string": "edited"}],
        },
    }


class TestAllToolsSmoke:
    def test_every_defined_tool_has_smoke_input(self, smoke_workspace):
        inputs = build_smoke_inputs(smoke_workspace)
        missing = [t["name"] for t in TOOL_DEFINITIONS if t["name"] not in inputs]
        assert not missing, f"Tools without smoke inputs: {missing}"

    def test_every_tool_executes_and_returns_result_dict(self, smoke_workspace):
        inputs = build_smoke_inputs(smoke_workspace)
        failures = []

        for tool in TOOL_DEFINITIONS:
            name = tool["name"]
            try:
                result = execute_tool(name, dict(inputs[name]))
            except Exception as exc:
                failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
                continue

            if not isinstance(result, dict) or "success" not in result:
                failures.append(f"{name}: malformed result: {result!r}")
                continue

            # delegate_task is intentionally handled by the agent loop.
            # The dispatcher's gap message is exactly "Unknown tool: <name>"
            # (install_system_tool has its own "Unknown tool '...'" allowlist
            # message, which is a valid tool-level rejection, not a gap).
            if name != "delegate_task" and str(result.get("error", "")).startswith(
                "Unknown tool: "
            ):
                failures.append(f"{name}: not dispatched (unknown tool)")

        assert not failures, "Tool failures:\n" + "\n".join(failures)

    def test_core_file_operations_actually_work(self, smoke_workspace):
        """Core tools must not just return dicts — they must succeed."""
        assert execute_tool(
            "write_file", {"file_path": "core.txt", "content": "one\n"}
        )["success"]
        read = execute_tool("read_file", {"file_path": "core.txt"})
        assert read["success"] and "one" in read["content"]
        assert execute_tool(
            "replace_in_file",
            {"file_path": "core.txt", "old_string": "one", "new_string": "two"},
        )["success"]
        assert execute_tool("glob_files", {"pattern": "*.txt"})["success"]
        assert execute_tool("grep_search", {"pattern": "two"})["success"]
        assert execute_tool("list_directory", {})["success"]
        assert execute_tool(
            "run_shell_command", {"command": "echo functional"}
        )["success"]

    def test_git_operations_work_in_real_repo(self, smoke_workspace):
        import shutil

        if not shutil.which("git"):
            pytest.skip("git not installed on this system")

        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "config", "user.email", "smoke@test.local"], check=True)
        subprocess.run(["git", "config", "user.name", "Smoke Test"], check=True)

        assert execute_tool("git_status", {})["success"]
        assert execute_tool("git_add", {"all_files": True})["success"]
        assert execute_tool("git_commit", {"message": "smoke commit"})["success"]
        log = execute_tool("git_log", {"count": 1})
        assert log["success"] and "smoke commit" in log.get("stdout", "")
