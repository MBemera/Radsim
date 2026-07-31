"""RadSim Tools Package - Modular tool implementation."""

import json
import logging
import re
from importlib import import_module

from .constants import DESTRUCTIVE_COMMANDS as DESTRUCTIVE_COMMANDS
from .constants import PROTECTED_PATTERNS as PROTECTED_PATTERNS
from .definitions import TOOL_DEFINITIONS as TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

EXTENSION_PERMISSION_TIERS = frozenset({"read_only", "mutation", "generated_code"})
EXTENSION_INPUT_ROLES = frozenset({"path", "command"})
MAX_EXTENSION_SCHEMA_BYTES = 32 * 1024
MAX_EXTENSION_RESULT_BYTES = 512 * 1024
_EXTENSION_TOOL_META = {}
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


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
    "http_request": _build_tool_executor(
        ".web",
        "http_request",
        ("url", ""),
        ("method", "GET"),
        ("headers", None),
        ("body", ""),
        ("timeout", 30),
    ),
    "screen_capture": _build_tool_executor(".screen", "screen_capture", ("save_path", "")),
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
    "get_project_info": _build_tool_executor(".project", "get_project_info"),
    "read_document": _build_tool_executor(".documents", "read_document", ("file_path", "")),
    "read_image": _build_tool_executor(".documents", "read_image", ("file_path", "")),
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
    "forget_memory": _build_tool_executor(
        "..memory",
        "forget_memory",
        ("key", ""),
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
    "add_tool": _build_tool_executor(
        ".self_extend",
        "add_tool",
        ("name", ""),
        ("description", ""),
        ("parameters", {}),
        ("body", ""),
    ),
    "list_custom_tools": _build_tool_executor(".self_extend", "list_custom_tools"),
    "remove_tool": _build_tool_executor(".self_extend", "remove_tool", ("name", "")),
}


def _merge_custom_tools():
    """Load user-added tools into the live registry and definitions."""
    try:
        from . import custom_tools
        _TOOL_REGISTRY.update(custom_tools.CUSTOM_REGISTRY)
        existing_names = {d["name"] for d in TOOL_DEFINITIONS}
        for definition in custom_tools.CUSTOM_DEFINITIONS:
            if definition["name"] not in existing_names:
                TOOL_DEFINITIONS.append(definition)
    except ImportError:
        pass


_merge_custom_tools()


def validate_extension_tool_definition(definition):
    """Validate the provider-facing subset supported by extension tools."""
    if not isinstance(definition, dict):
        raise ValueError("Tool definition must be an object")
    try:
        encoded = json.dumps(definition, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError("Tool definition must be JSON serializable") from error
    if len(encoded.encode("utf-8")) > MAX_EXTENSION_SCHEMA_BYTES:
        raise ValueError("Tool definition exceeds the schema size limit")
    definition = json.loads(encoded)
    name = definition.get("name")
    if not isinstance(name, str) or not _TOOL_NAME_PATTERN.fullmatch(name):
        raise ValueError("Tool name must use 2-64 lowercase letters, digits, or underscores")
    description = definition.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 500:
        raise ValueError("Tool description must contain 1-500 characters")
    schema = definition.get("input_schema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("Tool input_schema must be an object schema")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or len(properties) > 30:
        raise ValueError("Tool schema properties must be an object with at most 30 entries")
    if (
        not isinstance(required, list)
        or any(not isinstance(key, str) for key in required)
        or len(required) != len(set(required))
        or any(key not in properties for key in required)
    ):
        raise ValueError("Tool schema required fields must name declared properties")
    for key, property_schema in properties.items():
        if (
            not isinstance(key, str)
            or not isinstance(property_schema, dict)
            or property_schema.get("type") not in _JSON_TYPES
        ):
            raise ValueError(f"Unsupported schema for property: {key}")
    return {
        "name": name,
        "description": description.strip(),
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
        },
    }


def validate_extension_input_roles(definition, properties):
    """Validate the optional explicit path and command input declarations."""
    roles = definition.get("input_roles", {}) if isinstance(definition, dict) else {}
    if not isinstance(roles, dict):
        raise ValueError("Tool input_roles must be an object")
    unknown = sorted(set(roles) - EXTENSION_INPUT_ROLES)
    if unknown:
        raise ValueError(
            f"Unknown input role(s): {', '.join(unknown)}. "
            f"Valid: {', '.join(sorted(EXTENSION_INPUT_ROLES))}"
        )
    declared = {}
    for role, keys in roles.items():
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
            raise ValueError(f"Tool input_roles.{role} must be a list of property names")
        missing = sorted(set(keys) - set(properties))
        if missing:
            raise ValueError(
                f"Tool input_roles.{role} names undeclared propert(ies): {', '.join(missing)}"
            )
        declared[role] = tuple(keys)
    return declared


def can_register_extension_tool(name, *, replacing_owner=None):
    """Check the live registry without creating a parallel registry."""
    if name not in _TOOL_REGISTRY:
        return True, None
    metadata = _EXTENSION_TOOL_META.get(name)
    if metadata and metadata.get("owner") == replacing_owner:
        return True, None
    return False, f"Tool already registered: {name}"


def _schema_value_matches(value, expected):
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _JSON_TYPES[expected])


def _validate_extension_tool_input(definition, tool_input):
    schema = definition["input_schema"]
    properties = schema["properties"]
    missing = [key for key in schema["required"] if key not in tool_input]
    if missing:
        return False, f"Missing required input: {', '.join(sorted(missing))}"
    unknown = set(tool_input) - set(properties)
    if unknown:
        return False, f"Unknown input field: {', '.join(sorted(unknown))}"
    for key, value in tool_input.items():
        expected = properties[key]["type"]
        if not _schema_value_matches(value, expected):
            return False, f"Input '{key}' must be {expected}"
    return True, None


def _extension_input_keys(definition, declared_roles):
    """Combine explicit input roles with the conventional name patterns.

    Name matching alone misses inputs called `filename`, `dest`, or `cmd`, so a
    tool that handles paths or commands under any other name must declare them
    in `input_roles` to receive path, protected-file, symlink, and shell
    validation.
    """
    properties = definition["input_schema"]["properties"]
    path_keys = set(declared_roles.get("path", ()))
    command_keys = set(declared_roles.get("command", ()))
    for key in properties:
        lowered = key.lower()
        if lowered in {"path", "file", "directory"} or lowered.endswith(
            ("_path", "_paths", "_file", "_files", "_directory", "_directories", "_dir")
        ):
            path_keys.add(key)
        if lowered == "command" or lowered.endswith("_command"):
            command_keys.add(key)
    return tuple(sorted(path_keys)), tuple(sorted(command_keys))


def _validate_extension_tool_safety(metadata, tool_input):
    from .validation import (
        contains_symlink,
        is_protected_path,
        validate_path,
        validate_shell_command,
    )

    for key in metadata["path_keys"]:
        values = tool_input.get(key, [])
        values = values if isinstance(values, list) else [values]
        for value in values:
            safe, resolved, error = validate_path(value)
            if not safe:
                return False, error
            if metadata["permission_tier"] != "read_only":
                protected, reason = is_protected_path(value, resolved)
                if protected:
                    return False, f"Protected extension write blocked: {reason}"
                symlinked, path = contains_symlink(value)
                if symlinked:
                    return False, f"Extension write through symlink blocked: {path}"
    for key in metadata["command_keys"]:
        safe, error = validate_shell_command(tool_input.get(key))
        if not safe:
            return False, f"Extension command rejected: {error}"
    return True, None


def register_extension_tool(owner, definition, execute, permission_tier, *, input_roles=None):
    """Add an extension tool to the existing live registry."""
    validated = validate_extension_tool_definition(definition)
    if permission_tier not in EXTENSION_PERMISSION_TIERS:
        raise ValueError(
            "permission_tier must be read_only, mutation, or generated_code"
        )
    if not callable(execute):
        raise ValueError("Tool executor must be callable")
    allowed, error = can_register_extension_tool(validated["name"])
    if not allowed:
        raise ValueError(error)

    declared_roles = (
        validate_extension_input_roles(definition, validated["input_schema"]["properties"])
        if input_roles is None
        else input_roles
    )
    path_keys, command_keys = _extension_input_keys(validated, declared_roles)
    if command_keys and permission_tier == "read_only":
        raise ValueError("A tool with command input cannot use the read_only tier")
    metadata = {
        "owner": owner,
        "permission_tier": permission_tier,
        "active": True,
        "path_keys": path_keys,
        "command_keys": command_keys,
    }

    def guarded_execute(tool_input):
        if not metadata["active"]:
            return {"success": False, "error": f"Extension tool '{validated['name']}' is inactive"}
        valid, input_error = _validate_extension_tool_input(validated, tool_input)
        if not valid:
            return {"success": False, "error": input_error}
        safe, safety_error = _validate_extension_tool_safety(metadata, tool_input)
        if not safe:
            return {"success": False, "error": safety_error}
        try:
            result = execute(dict(tool_input))
        except Exception as error:
            logger.exception("Extension tool %s crashed", validated["name"])
            return {
                "success": False,
                "error": (
                    f"Extension tool crashed: {type(error).__name__}: "
                    f"{str(error)[:300]}"
                ),
            }
        if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
            return {
                "success": False,
                "error": "Extension tools must return a dict with a boolean 'success'",
            }
        try:
            encoded_result = json.dumps(result)
        except (TypeError, ValueError):
            return {
                "success": False,
                "error": "Extension tool results must be JSON serializable",
            }
        if len(encoded_result.encode("utf-8")) > MAX_EXTENSION_RESULT_BYTES:
            return {
                "success": False,
                "error": "Extension tool result exceeds the size limit",
            }
        return result

    _TOOL_REGISTRY[validated["name"]] = guarded_execute
    TOOL_DEFINITIONS.append(validated)
    _EXTENSION_TOOL_META[validated["name"]] = metadata
    return validated["name"]


def set_extension_tool_active(owner, name, enabled):
    """Toggle one extension-owned tool without changing its registration."""
    metadata = _EXTENSION_TOOL_META.get(name)
    if metadata is None or metadata.get("owner") != owner:
        raise ValueError(f"Extension does not own tool: {name}")
    metadata["active"] = bool(enabled)


def unregister_extension_tools(owner):
    """Remove only tool registrations owned by one extension."""
    names = sorted(
        name
        for name, metadata in _EXTENSION_TOOL_META.items()
        if metadata.get("owner") == owner
    )
    for name in names:
        _TOOL_REGISTRY.pop(name, None)
        _EXTENSION_TOOL_META.pop(name, None)
    if names:
        TOOL_DEFINITIONS[:] = [
            definition for definition in TOOL_DEFINITIONS if definition["name"] not in names
        ]
    return names


def get_extension_tool_metadata(name):
    """Return a copy of extension ownership and policy metadata."""
    metadata = _EXTENSION_TOOL_META.get(name)
    return dict(metadata) if metadata else None


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
