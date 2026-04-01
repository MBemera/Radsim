"""RadSim Tools Package - Modular tool implementation."""

import logging
from importlib import import_module

from .constants import DESTRUCTIVE_COMMANDS as DESTRUCTIVE_COMMANDS
from .constants import PROTECTED_PATTERNS as PROTECTED_PATTERNS
from .definitions import TOOL_DEFINITIONS as TOOL_DEFINITIONS

logger = logging.getLogger(__name__)


def _run_tool_function(module_path, function_name, *args):
    """Import a tool module only when the tool is executed."""
    module = import_module(module_path, package=__package__)
    function = getattr(module, function_name)
    return function(*args)


def _build_tool_executor(module_path, function_name, *argument_specs):
    """Create a lazy executor for a standard module function."""

    def execute(tool_input):
        arguments = []
        for argument_name, default_value in argument_specs:
            arguments.append(tool_input.get(argument_name, default_value))
        return _run_tool_function(module_path, function_name, *arguments)

    return execute


def _execute_delegate_task(tool_input):
    """Keep API compatibility for delegation handled in the agent loop."""
    return {"success": False, "error": "delegate_task is handled directly by the agent loop"}


def _execute_browser_tool(tool_name, tool_input):
    """Load browser tooling only when a browser tool is executed."""
    browser_handlers = {
        "browser_open": ("browser_open", ("url", "")),
        "browser_click": ("browser_click", ("selector", "")),
        "browser_type": ("browser_type", ("selector", ""), ("text", "")),
        "browser_screenshot": ("browser_screenshot", ("filename", None)),
    }

    if tool_name not in browser_handlers:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    try:
        browser_module = import_module("..browser", package=__package__)
    except ImportError:
        return {
            "success": False,
            "error": "Playwright not installed. Run: pip install playwright && playwright install chromium",
        }

    function_name, *argument_specs = browser_handlers[tool_name]
    arguments = [
        tool_input.get(argument_name, default_value)
        for argument_name, default_value in argument_specs
    ]
    function = getattr(browser_module, function_name)
    return function(*arguments)


def _execute_list_skills(tool_input):
    """Return the existing list_skills response shape."""
    skills_module = import_module("..skills", package=__package__)
    skills = skills_module.list_skills()
    return {"success": True, "skills": skills, "count": len(skills)}


def _execute_remove_skill(tool_input):
    """Convert the 1-based API index into the internal 0-based value."""
    index = tool_input.get("index", 0) - 1
    return _run_tool_function("..skills", "remove_skill", index)


def _execute_todo_read(tool_input):
    """Call the todo tracker read method lazily."""
    todo_module = import_module("..todo", package=__package__)
    return todo_module.get_tracker().read()


def _execute_todo_write(tool_input):
    """Call the todo tracker write method lazily."""
    todo_module = import_module("..todo", package=__package__)
    return todo_module.get_tracker().write(tool_input.get("todos", []))


_TOOL_REGISTRY = {
    "install_system_tool": _build_tool_executor(
        ".dependencies",
        "install_system_tool",
        ("tool_name", ""),
    ),
    "delegate_task": _execute_delegate_task,
    "submit_completion": _build_tool_executor(
        ".project",
        "submit_completion",
        ("summary", ""),
        ("artifacts", None),
    ),
    "read_file": _build_tool_executor(
        ".file_ops",
        "read_file",
        ("file_path", ""),
        ("offset", 0),
        ("limit", None),
    ),
    "read_many_files": _build_tool_executor(".file_ops", "read_many_files", ("file_paths", [])),
    "write_file": _build_tool_executor(
        ".file_ops",
        "write_file",
        ("file_path", ""),
        ("content", ""),
    ),
    "replace_in_file": _build_tool_executor(
        ".file_ops",
        "replace_in_file",
        ("file_path", ""),
        ("old_string", ""),
        ("new_string", ""),
        ("replace_all", False),
    ),
    "rename_file": _build_tool_executor(
        ".file_ops",
        "rename_file",
        ("old_path", ""),
        ("new_path", ""),
    ),
    "delete_file": _build_tool_executor(".file_ops", "delete_file", ("file_path", "")),
    "list_directory": _build_tool_executor(
        ".directory_ops",
        "list_directory",
        ("directory_path", "."),
        ("recursive", False),
        ("max_depth", 3),
    ),
    "create_directory": _build_tool_executor(
        ".directory_ops",
        "create_directory",
        ("directory_path", ""),
    ),
    "glob_files": _build_tool_executor(
        ".search",
        "glob_files",
        ("pattern", ""),
        ("directory_path", "."),
    ),
    "grep_search": _build_tool_executor(
        ".search",
        "grep_search",
        ("pattern", ""),
        ("directory_path", "."),
        ("file_pattern", None),
        ("ignore_case", False),
        ("context_lines", 0),
        ("output_mode", "content"),
    ),
    "search_files": _build_tool_executor(
        ".search",
        "search_files",
        ("pattern", ""),
        ("directory_path", "."),
    ),
    "run_shell_command": _build_tool_executor(
        ".shell",
        "run_shell_command",
        ("command", ""),
        ("timeout", 120),
        ("working_dir", None),
    ),
    "web_fetch": _build_tool_executor(".web", "web_fetch", ("url", "")),
    "git_status": _build_tool_executor(".git", "git_status"),
    "git_diff": _build_tool_executor(
        ".git",
        "git_diff",
        ("staged", False),
        ("file_path", None),
    ),
    "git_log": _build_tool_executor(
        ".git",
        "git_log",
        ("count", 10),
        ("oneline", True),
    ),
    "git_branch": _build_tool_executor(".git", "git_branch"),
    "find_definition": _build_tool_executor(
        ".code_intel",
        "find_definition",
        ("symbol", ""),
        ("directory_path", "."),
    ),
    "find_references": _build_tool_executor(
        ".code_intel",
        "find_references",
        ("symbol", ""),
        ("directory_path", "."),
    ),
    "run_tests": _build_tool_executor(
        ".testing",
        "run_tests",
        ("test_command", None),
        ("test_path", None),
        ("verbose", False),
    ),
    "lint_code": _build_tool_executor(
        ".testing",
        "lint_code",
        ("file_path", None),
        ("fix", False),
    ),
    "format_code": _build_tool_executor(
        ".testing",
        "format_code",
        ("file_path", None),
        ("check_only", False),
    ),
    "type_check": _build_tool_executor(".testing", "type_check", ("file_path", None)),
    "git_add": _build_tool_executor(
        ".git",
        "git_add",
        ("file_paths", None),
        ("all_files", False),
    ),
    "git_commit": _build_tool_executor(
        ".git",
        "git_commit",
        ("message", ""),
        ("amend", False),
    ),
    "git_checkout": _build_tool_executor(
        ".git",
        "git_checkout",
        ("branch", None),
        ("create", False),
        ("file_path", None),
    ),
    "git_stash": _build_tool_executor(
        ".git",
        "git_stash",
        ("action", "push"),
        ("message", None),
    ),
    "list_dependencies": _build_tool_executor(".dependencies", "list_dependencies"),
    "add_dependency": _build_tool_executor(
        ".dependencies",
        "add_dependency",
        ("package", ""),
        ("dev", False),
    ),
    "remove_dependency": _build_tool_executor(
        ".dependencies",
        "remove_dependency",
        ("package", ""),
    ),
    "npm_install": _build_tool_executor(
        ".dependencies",
        "npm_install",
        ("package", ""),
        ("dev", False),
        ("global_install", False),
    ),
    "pip_install": _build_tool_executor(
        ".dependencies",
        "pip_install",
        ("package", ""),
        ("upgrade", False),
    ),
    "init_project": _build_tool_executor(
        ".dependencies",
        "init_project",
        ("project_type", ""),
        ("name", None),
        ("template", None),
    ),
    "detect_project_type": _build_tool_executor(".testing", "detect_project_type"),
    "get_project_info": _build_tool_executor(".project", "get_project_info"),
    "batch_replace": _build_tool_executor(
        ".project",
        "batch_replace",
        ("pattern", ""),
        ("replacement", ""),
        ("file_pattern", "*"),
        ("directory_path", "."),
    ),
    "plan_task": _build_tool_executor(
        ".project",
        "plan_task",
        ("task_description", ""),
        ("subtasks", None),
    ),
    "save_context": _build_tool_executor(
        ".project",
        "save_context",
        ("context_data", {}),
        ("filename", "radsim_context.json"),
    ),
    "load_context": _build_tool_executor(
        ".project",
        "load_context",
        ("filename", "radsim_context.json"),
    ),
    "analyze_code": _build_tool_executor(
        ".code_intel",
        "analyze_code",
        ("file_path", ""),
        ("analysis_type", "full"),
    ),
    "run_docker": _build_tool_executor(
        ".advanced",
        "run_docker",
        ("action", ""),
        ("container", None),
        ("image", None),
        ("command", None),
        ("options", None),
    ),
    "database_query": _build_tool_executor(
        ".advanced",
        "database_query",
        ("query", ""),
        ("database_path", "database.db"),
        ("read_only", True),
    ),
    "generate_tests": _build_tool_executor(
        ".advanced",
        "generate_tests",
        ("source_file", ""),
        ("output_file", None),
        ("framework", "pytest"),
    ),
    "refactor_code": _build_tool_executor(
        ".advanced",
        "refactor_code",
        ("action", ""),
        ("file_path", ""),
        ("old_name", None),
        ("new_name", None),
        ("target_line", None),
        ("new_function_name", None),
    ),
    "deploy": _build_tool_executor(
        ".advanced",
        "deploy",
        ("platform", None),
        ("check_only", False),
        ("command", None),
    ),
    "save_memory": _build_tool_executor(
        "..memory",
        "save_memory",
        ("key", ""),
        ("value", ""),
        ("memory_type", "preference"),
    ),
    "load_memory": _build_tool_executor(
        "..memory",
        "load_memory",
        ("key", None),
        ("memory_type", "preference"),
    ),
    "schedule_task": _build_tool_executor(
        "..scheduler",
        "schedule_task",
        ("name", ""),
        ("schedule", ""),
        ("command", ""),
        ("description", None),
    ),
    "list_schedules": _build_tool_executor("..scheduler", "list_schedules"),
    "add_skill": _build_tool_executor(
        "..skills",
        "add_skill",
        ("instruction", ""),
        ("category", None),
    ),
    "remove_skill": _execute_remove_skill,
    "list_skills": _execute_list_skills,
    "send_telegram": _build_tool_executor(
        "..telegram",
        "send_telegram_message",
        ("message", ""),
    ),
    "todo_read": _execute_todo_read,
    "todo_write": _execute_todo_write,
    "multi_edit": _build_tool_executor(
        ".file_ops",
        "multi_edit",
        ("file_path", ""),
        ("edits", []),
    ),
    "repo_map": _build_tool_executor(
        "..repo_map",
        "generate_repo_map",
        ("directory_path", "."),
        ("focus_files", None),
        ("max_tokens", 4000),
        ("language_filter", None),
    ),
    "apply_patch": _build_tool_executor("..patch", "apply_patch", ("patch", "")),
}


def execute_tool(tool_name, tool_input):
    """Execute a tool and return the result."""
    tool_input = dict(tool_input)

    intent = tool_input.pop("_intent", None)
    if intent:
        logger.debug("Tool intent [%s]: %s", tool_name, intent)

    if tool_name.startswith("browser_"):
        return _execute_browser_tool(tool_name, tool_input)

    executor = _TOOL_REGISTRY.get(tool_name)
    if executor is None:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    return executor(tool_input)
