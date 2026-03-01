"""RadSim Tools Package - Modular tool implementation.

RadSim Principle: Consistent Structure Everywhere

This package provides all tools for the RadSim agent, organized into modules:
- constants: Configuration and limits
- validation: Path and command validation
- file_ops: File read/write/edit operations
- directory_ops: Directory listing and creation
- search: Glob and grep search
- shell: Shell command execution
- web: Web fetching
- git: Git operations
- testing: Test, lint, format, type check
- dependencies: Package management
- code_intel: Code analysis and symbol search
- advanced: Docker, database, refactoring, deployment
- project: Batch operations, task planning, context
- definitions: Tool definitions for API
"""

import logging

# Try to import browser tools (optional dependency)
try:
    from ..browser import browser_click, browser_open, browser_screenshot, browser_type

    HAS_BROWSER_TOOLS = True
except ImportError:
    HAS_BROWSER_TOOLS = False

# Export constants (explicit re-export for package API)
# Import all tool functions for execute_tool
from .advanced import database_query, deploy, generate_tests, refactor_code, run_docker
from .code_intel import analyze_code, find_definition, find_references
from .constants import DESTRUCTIVE_COMMANDS as DESTRUCTIVE_COMMANDS
from .constants import PROTECTED_PATTERNS as PROTECTED_PATTERNS

# Export tool definitions
from .definitions import TOOL_DEFINITIONS as TOOL_DEFINITIONS
from .dependencies import (
    add_dependency,
    init_project,
    install_system_tool,
    list_dependencies,
    npm_install,
    pip_install,
    remove_dependency,
)
from .directory_ops import create_directory, list_directory

# Import all tool functions for execute_tool
from .file_ops import (
    delete_file,
    multi_edit,
    read_file,
    read_many_files,
    rename_file,
    replace_in_file,
    write_file,
)
from .git import (
    git_add,
    git_branch,
    git_checkout,
    git_commit,
    git_diff,
    git_log,
    git_stash,
    git_status,
)
from .project import (
    batch_replace,
    get_project_info,
    load_context,
    plan_task,
    save_context,
    submit_completion,
)
from .search import glob_files, grep_search, search_files
from .shell import run_shell_command
from .testing import detect_project_type, format_code, lint_code, run_tests, type_check
from .web import web_fetch

logger = logging.getLogger(__name__)


def execute_tool(tool_name, tool_input):
    """Execute a tool and return the result.

    This is the main entry point for tool execution, used by the agent.
    """
    # Strip _intent before dispatching (chain-of-thought, not a real parameter)
    intent = tool_input.pop("_intent", None)
    if intent:
        logger.debug("Tool intent [%s]: %s", tool_name, intent)

    # Browser Tools
    if tool_name.startswith("browser_"):
        if not HAS_BROWSER_TOOLS:
            return {
                "success": False,
                "error": "Playwright not installed. Run: pip install playwright && playwright install chromium",
            }

        if tool_name == "browser_open":
            return browser_open(tool_input.get("url", ""))
        elif tool_name == "browser_click":
            return browser_click(tool_input.get("selector", ""))
        elif tool_name == "browser_type":
            return browser_type(tool_input.get("selector", ""), tool_input.get("text", ""))
        elif tool_name == "browser_screenshot":
            return browser_screenshot(tool_input.get("filename"))

    # System Tools
    if tool_name == "install_system_tool":
        return install_system_tool(tool_input.get("tool_name", ""))

    # Agentic Delegation (handled by agent.py directly, but kept for API compatibility)
    if tool_name == "delegate_task":
        return {"success": False, "error": "delegate_task is handled directly by the agent loop"}

    if tool_name == "submit_completion":
        return submit_completion(tool_input.get("summary", ""), tool_input.get("artifacts"))

    # File Operations
    if tool_name == "read_file":
        return read_file(
            tool_input.get("file_path", ""), tool_input.get("offset", 0), tool_input.get("limit")
        )

    elif tool_name == "read_many_files":
        return read_many_files(tool_input.get("file_paths", []))

    elif tool_name == "write_file":
        return write_file(tool_input.get("file_path", ""), tool_input.get("content", ""))

    elif tool_name == "replace_in_file":
        return replace_in_file(
            tool_input.get("file_path", ""),
            tool_input.get("old_string", ""),
            tool_input.get("new_string", ""),
            tool_input.get("replace_all", False),
        )

    elif tool_name == "rename_file":
        return rename_file(tool_input.get("old_path", ""), tool_input.get("new_path", ""))

    elif tool_name == "delete_file":
        return delete_file(tool_input.get("file_path", ""))

    # Directory Operations
    elif tool_name == "list_directory":
        return list_directory(
            tool_input.get("directory_path", "."),
            tool_input.get("recursive", False),
            tool_input.get("max_depth", 3),
        )

    elif tool_name == "create_directory":
        return create_directory(tool_input.get("directory_path", ""))

    # Search Tools
    elif tool_name == "glob_files":
        return glob_files(tool_input.get("pattern", ""), tool_input.get("directory_path", "."))

    elif tool_name == "grep_search":
        return grep_search(
            tool_input.get("pattern", ""),
            tool_input.get("directory_path", "."),
            tool_input.get("file_pattern"),
            tool_input.get("ignore_case", False),
            tool_input.get("context_lines", 0),
            tool_input.get("output_mode", "content"),
        )

    elif tool_name == "search_files":
        return search_files(tool_input.get("pattern", ""), tool_input.get("directory_path", "."))

    # Shell Execution
    elif tool_name == "run_shell_command":
        return run_shell_command(
            tool_input.get("command", ""),
            tool_input.get("timeout", 120),
            tool_input.get("working_dir"),
        )

    # Web Tools
    elif tool_name == "web_fetch":
        return web_fetch(tool_input.get("url", ""))

    # Git Tools
    elif tool_name == "git_status":
        return git_status()

    elif tool_name == "git_diff":
        return git_diff(tool_input.get("staged", False), tool_input.get("file_path"))

    elif tool_name == "git_log":
        return git_log(tool_input.get("count", 10), tool_input.get("oneline", True))

    elif tool_name == "git_branch":
        return git_branch()

    # Code Intelligence
    elif tool_name == "find_definition":
        return find_definition(tool_input.get("symbol", ""), tool_input.get("directory_path", "."))

    elif tool_name == "find_references":
        return find_references(tool_input.get("symbol", ""), tool_input.get("directory_path", "."))

    # Testing & Validation
    elif tool_name == "run_tests":
        return run_tests(
            tool_input.get("test_command"),
            tool_input.get("test_path"),
            tool_input.get("verbose", False),
        )

    elif tool_name == "lint_code":
        return lint_code(tool_input.get("file_path"), tool_input.get("fix", False))

    elif tool_name == "format_code":
        return format_code(tool_input.get("file_path"), tool_input.get("check_only", False))

    elif tool_name == "type_check":
        return type_check(tool_input.get("file_path"))

    # Git Write Operations
    elif tool_name == "git_add":
        return git_add(tool_input.get("file_paths"), tool_input.get("all_files", False))

    elif tool_name == "git_commit":
        return git_commit(tool_input.get("message", ""), tool_input.get("amend", False))

    elif tool_name == "git_checkout":
        return git_checkout(
            tool_input.get("branch"), tool_input.get("create", False), tool_input.get("file_path")
        )

    elif tool_name == "git_stash":
        return git_stash(tool_input.get("action", "push"), tool_input.get("message"))

    # Dependency Management
    elif tool_name == "list_dependencies":
        return list_dependencies()

    elif tool_name == "add_dependency":
        return add_dependency(tool_input.get("package", ""), tool_input.get("dev", False))

    elif tool_name == "remove_dependency":
        return remove_dependency(tool_input.get("package", ""))

    elif tool_name == "npm_install":
        return npm_install(
            tool_input.get("package", ""),
            tool_input.get("dev", False),
            tool_input.get("global_install", False),
        )

    elif tool_name == "pip_install":
        return pip_install(
            tool_input.get("package", ""),
            tool_input.get("upgrade", False),
        )

    elif tool_name == "init_project":
        return init_project(
            tool_input.get("project_type", ""),
            tool_input.get("name"),
            tool_input.get("template"),
        )

    # Project Tools
    elif tool_name == "detect_project_type":
        return detect_project_type()

    elif tool_name == "get_project_info":
        return get_project_info()

    elif tool_name == "batch_replace":
        return batch_replace(
            tool_input.get("pattern", ""),
            tool_input.get("replacement", ""),
            tool_input.get("file_pattern", "*"),
            tool_input.get("directory_path", "."),
        )

    # Task Planning
    elif tool_name == "plan_task":
        return plan_task(tool_input.get("task_description", ""), tool_input.get("subtasks"))

    elif tool_name == "save_context":
        return save_context(
            tool_input.get("context_data", {}), tool_input.get("filename", "radsim_context.json")
        )

    elif tool_name == "load_context":
        return load_context(tool_input.get("filename", "radsim_context.json"))

    # Advanced Skills
    elif tool_name == "analyze_code":
        return analyze_code(
            tool_input.get("file_path", ""), tool_input.get("analysis_type", "full")
        )

    elif tool_name == "run_docker":
        return run_docker(
            tool_input.get("action", ""),
            tool_input.get("container"),
            tool_input.get("image"),
            tool_input.get("command"),
            tool_input.get("options"),
        )

    elif tool_name == "database_query":
        return database_query(
            tool_input.get("query", ""),
            tool_input.get("database_path", "database.db"),
            tool_input.get("read_only", True),
        )

    elif tool_name == "generate_tests":
        return generate_tests(
            tool_input.get("source_file", ""),
            tool_input.get("output_file"),
            tool_input.get("framework", "pytest"),
        )

    elif tool_name == "refactor_code":
        return refactor_code(
            tool_input.get("action", ""),
            tool_input.get("file_path", ""),
            tool_input.get("old_name"),
            tool_input.get("new_name"),
            tool_input.get("target_line"),
            tool_input.get("new_function_name"),
        )

    elif tool_name == "deploy":
        return deploy(
            tool_input.get("platform"),
            tool_input.get("check_only", False),
            tool_input.get("command"),
        )

    # Memory & Scheduling
    elif tool_name == "save_memory":
        from ..memory import save_memory

        return save_memory(
            tool_input.get("key", ""),
            tool_input.get("value", ""),
            tool_input.get("memory_type", "preference"),
        )

    elif tool_name == "load_memory":
        from ..memory import load_memory

        return load_memory(tool_input.get("key"), tool_input.get("memory_type", "preference"))

    elif tool_name == "schedule_task":
        from ..scheduler import schedule_task

        return schedule_task(
            tool_input.get("name", ""),
            tool_input.get("schedule", ""),
            tool_input.get("command", ""),
            tool_input.get("description"),
        )

    elif tool_name == "list_schedules":
        from ..scheduler import list_schedules

        return list_schedules()

    elif tool_name == "add_skill":
        from ..skills import add_skill

        return add_skill(
            tool_input.get("instruction", ""),
            tool_input.get("category"),
        )

    elif tool_name == "remove_skill":
        from ..skills import remove_skill

        index = tool_input.get("index", 0) - 1  # Convert 1-based to 0-based
        return remove_skill(index)

    elif tool_name == "list_skills":
        from ..skills import list_skills

        skills = list_skills()
        return {"success": True, "skills": skills, "count": len(skills)}

    elif tool_name == "send_telegram":
        from ..telegram import send_telegram_message

        return send_telegram_message(tool_input.get("message", ""))

    # Task Tracking
    elif tool_name == "todo_read":
        from ..todo import get_tracker

        return get_tracker().read()

    elif tool_name == "todo_write":
        from ..todo import get_tracker

        return get_tracker().write(tool_input.get("todos", []))

    # Atomic Batch Edit
    elif tool_name == "multi_edit":
        return multi_edit(tool_input.get("file_path", ""), tool_input.get("edits", []))

    # Codebase Structure
    elif tool_name == "repo_map":
        from ..repo_map import generate_repo_map

        return generate_repo_map(
            directory=tool_input.get("directory_path", "."),
            focus_files=tool_input.get("focus_files"),
            max_tokens=tool_input.get("max_tokens", 4000),
            language_filter=tool_input.get("language_filter"),
        )

    # Multi-File Patch
    elif tool_name == "apply_patch":
        from ..patch import apply_patch

        return apply_patch(tool_input.get("patch", ""))

    else:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
