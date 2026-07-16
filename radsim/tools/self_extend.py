"""Self-extension: add new tools to the live agent at runtime.

The model calls `add_tool(name, description, parameters, body)` to register
a new tool. The tool is appended to `custom_tools.py` (so it persists across
restarts) AND merged into the live `_TOOL_REGISTRY` and `TOOL_DEFINITIONS`
(so it's callable on the very next turn — no restart needed).
"""

import ast
import json
import keyword
import re
from importlib import reload
from pathlib import Path

CUSTOM_TOOLS_FILE = Path(__file__).parent / "custom_tools.py"

VALID_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

# A schema property name becomes a parameter name in generated source, so it
# must be a plain ASCII identifier and nothing else — this ceiling stops a
# crafted key from smuggling punctuation into the function signature.
MAX_PROPERTIES = 32

FORBIDDEN_NAMES = {
    "add_tool", "remove_tool", "list_custom_tools",
    "exec", "eval", "compile", "__import__",
}

FORBIDDEN_BODY_PATTERNS = [
    "import os", "import subprocess", "import shutil",
    "from os ", "from subprocess ", "from shutil ",
    "__import__", "exec(", "eval(", "compile(",
    "open('/", 'open("/',
]


def add_tool(name: str, description: str, parameters: dict, body: str) -> dict:
    """Register a new tool the model can call.

    Args:
        name: snake_case tool name (a-z, 0-9, _; must start with letter)
        description: one-line description shown to the model
        parameters: JSON Schema dict with `properties` and optional `required`
        body: Python function body (no `def` line — just the body, indented or not)

    Returns:
        dict with success status and a usage hint
    """
    name = (name or "").strip()
    description = (description or "").strip()

    if not VALID_NAME.match(name):
        return {"success": False, "error": f"Invalid tool name: {name!r} (need [a-z][a-z0-9_]{{1,63}})"}

    if name in FORBIDDEN_NAMES:
        return {"success": False, "error": f"Tool name {name!r} is reserved"}

    if not description:
        return {"success": False, "error": "description is required"}

    if not isinstance(parameters, dict):
        return {"success": False, "error": "parameters must be a JSON Schema object"}

    properties = parameters.get("properties", {})
    if not isinstance(properties, dict):
        return {"success": False, "error": "parameters.properties must be a dict"}

    key_error = _validate_property_keys(properties)
    if key_error:
        return {"success": False, "error": key_error}

    if _name_collides(name):
        return {"success": False, "error": f"Tool {name!r} already exists"}

    safety_error = _validate_body(body)
    if safety_error:
        return {"success": False, "error": safety_error}

    function_source = _build_function_source(name, properties, body)

    structure_error = _validate_generated_source(function_source, name)
    if structure_error:
        return {"success": False, "error": f"Generated source rejected: {structure_error}"}

    definition = {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": parameters.get("required", []),
        },
    }

    appended = _append_to_custom_file(name, function_source, definition)
    if not appended["success"]:
        return appended

    reloaded = _hot_reload()
    if not reloaded["success"]:
        return reloaded

    return {
        "success": True,
        "name": name,
        "message": f"Tool {name!r} registered. Callable on next turn.",
        "persisted_to": str(CUSTOM_TOOLS_FILE),
    }


def list_custom_tools() -> dict:
    """List all tools added via add_tool."""
    try:
        from . import custom_tools
        reload(custom_tools)
        tools = [
            {"name": d["name"], "description": d["description"]}
            for d in custom_tools.CUSTOM_DEFINITIONS
        ]
        return {"success": True, "tools": tools, "count": len(tools)}
    except Exception as error:
        return {"success": False, "error": str(error)}


def remove_tool(name: str) -> dict:
    """Remove a custom tool by name. Other custom tools are preserved."""
    name = (name or "").strip()
    if not name:
        return {"success": False, "error": "name is required"}

    try:
        from . import custom_tools
        reload(custom_tools)

        if name not in {d["name"] for d in custom_tools.CUSTOM_DEFINITIONS}:
            return {"success": False, "error": f"Tool {name!r} not found"}

        kept_defs = [d for d in custom_tools.CUSTOM_DEFINITIONS if d["name"] != name]
        kept_names = {d["name"] for d in kept_defs}

        _rewrite_custom_file(kept_names, kept_defs)
        _hot_reload()
        return {"success": True, "removed": name, "remaining": len(kept_defs)}
    except Exception as error:
        return {"success": False, "error": str(error)}


def _name_collides(name: str) -> bool:
    """Check whether the name is already taken in the live registry."""
    try:
        from . import _TOOL_REGISTRY
        if name in _TOOL_REGISTRY:
            return True
    except ImportError:
        pass
    return False


def _validate_body(body: str) -> str | None:
    """Reject obviously dangerous body patterns. Returns error or None."""
    if not isinstance(body, str) or not body.strip():
        return "body must be a non-empty Python source string"
    if len(body) > 10_000:
        return "body too long (max 10,000 chars)"
    for pattern in FORBIDDEN_BODY_PATTERNS:
        if pattern in body:
            return (
                f"body contains forbidden pattern: {pattern!r}. "
                "Custom tools cannot import os/subprocess/shutil or read local files. "
                "Use arguments, or ask for a built-in tool if file or env access is required."
            )
    return None


def _validate_property_keys(properties: dict) -> str | None:
    """Reject schema property names that are not safe Python identifiers.

    Each property name is joined verbatim into the generated function
    signature, so a name containing punctuation, a newline, or a colon could
    close the signature and smuggle a top-level statement that executes during
    hot reload (CWE-94/CWE-95). The policy is therefore deliberately narrow:
    a plain ASCII identifier, not a Python keyword, not a dunder, and unique.

    ASCII is required because ``str.isidentifier`` accepts Unicode names that
    NFKC-normalise to a different identifier (``ﬀ`` → ``ff``), which would let
    two distinct-looking keys collide or normalise into a keyword.

    Returns an error string, or None when every key is safe.
    """
    if len(properties) > MAX_PROPERTIES:
        return f"too many parameters ({len(properties)}); max is {MAX_PROPERTIES}"

    seen = set()
    for key in properties:
        if not isinstance(key, str):
            return f"parameter name must be a string, got {type(key).__name__}"
        if not key.isascii():
            return f"parameter name {key!r} must contain only ASCII characters"
        if not key.isidentifier():
            return f"parameter name {key!r} is not a valid identifier"
        if keyword.iskeyword(key):
            return f"parameter name {key!r} is a Python keyword"
        if key.startswith("__") and key.endswith("__"):
            return f"parameter name {key!r} may not be a dunder"
        if key in seen:
            return f"duplicate parameter name {key!r}"
        seen.add(key)
    return None


def _build_function_source(name: str, properties: dict, body: str) -> str:
    """Compose a runnable function from a name, schema, and body string.

    Callers must run ``_validate_property_keys`` first: every key here is
    joined into the signature verbatim and is only safe once proven to be a
    bare ASCII identifier.
    """
    arg_names = list(properties.keys())
    args = ", ".join(arg_names) if arg_names else ""
    body_lines = body.strip("\n").split("\n")
    indented = "\n".join("    " + line if line.strip() else line for line in body_lines)
    return f"def {name}({args}):\n{indented}\n"


def _validate_generated_source(source: str, name: str) -> str | None:
    """Parse generated source and require exactly one matching function.

    A custom tool may only ever be a single top-level ``def`` with the
    expected name. Any other top-level shape — a stray statement smuggled in
    through a schema field, a second definition, an import — is rejected before
    the source is written to disk or imported. Returns an error or None.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return f"syntax error ({error})"

    if len(tree.body) != 1:
        return "must contain exactly one top-level function definition"

    node = tree.body[0]
    if not isinstance(node, ast.FunctionDef):
        return "must be a single function definition"
    if node.name != name:
        return f"function name {node.name!r} does not match tool name {name!r}"
    return None


def _append_to_custom_file(name: str, function_source: str, definition: dict) -> dict:
    """Append a function + registry binding + definition entry to custom_tools.py."""
    try:
        existing = CUSTOM_TOOLS_FILE.read_text()

        arg_names = _extract_arg_names(function_source)
        registry_line = (
            f'CUSTOM_REGISTRY[{name!r}] = lambda tool_input: {name}('
            f'**{{k: tool_input.get(k) for k in [{", ".join(repr(a) for a in arg_names)}]}})'
        )
        definition_block = (
            f"CUSTOM_DEFINITIONS.append({json.dumps(definition, indent=4)})"
        )

        block = (
            f"\n\n# --- {name} ---\n"
            f"{function_source}\n"
            f"{registry_line}\n"
            f"{definition_block}\n"
        )

        CUSTOM_TOOLS_FILE.write_text(existing + block)
        return {"success": True}
    except OSError as error:
        return {"success": False, "error": f"Failed to write custom_tools.py: {error}"}


def _rewrite_custom_file(kept_names: set[str], kept_defs: list[dict]) -> None:
    """Rewrite custom_tools.py keeping only the named tools."""
    base = CUSTOM_TOOLS_FILE.read_text().split("\n\n# --- ")[0]

    blocks = []
    for definition in kept_defs:
        name = definition["name"]
        if name not in kept_names:
            continue
        existing = CUSTOM_TOOLS_FILE.read_text()
        marker = f"# --- {name} ---"
        if marker in existing:
            after = existing.split(marker, 1)[1]
            chunk = after.split("\n\n# --- ", 1)[0]
            blocks.append(f"\n\n# --- {name} ---{chunk}")

    CUSTOM_TOOLS_FILE.write_text(base + "".join(blocks))


def _extract_arg_names(function_source: str) -> list[str]:
    """Pull the argument names out of a function source string."""
    try:
        tree = ast.parse(function_source)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                return [arg.arg for arg in node.args.args]
    except SyntaxError:
        pass
    return []


def _hot_reload() -> dict:
    """Re-import custom_tools and merge into the live registry/definitions."""
    try:
        from . import custom_tools
        reload(custom_tools)

        from . import _TOOL_REGISTRY
        from .definitions import TOOL_DEFINITIONS

        _TOOL_REGISTRY.update(custom_tools.CUSTOM_REGISTRY)

        existing_names = {d["name"] for d in TOOL_DEFINITIONS}
        for definition in custom_tools.CUSTOM_DEFINITIONS:
            if definition["name"] not in existing_names:
                TOOL_DEFINITIONS.append(definition)

        return {"success": True}
    except Exception as error:
        return {"success": False, "error": f"Hot reload failed: {error}"}
