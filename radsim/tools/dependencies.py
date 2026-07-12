"""Dependency management tools for RadSim.

RadSim Principle: One Function, One Purpose
"""

import logging
import re
import shutil
from pathlib import Path

from ..terminal import is_unsafe_terminal_character
from .platform_detect import detect_os, detect_package_manager
from .shell import format_process_command, run_process
from .testing import detect_project_type

logger = logging.getLogger(__name__)

SAFE_AXIOS_VERSIONS = {"0.30.3", "1.14.0"}
NPM_REGISTRY_SPEC_PATTERN = re.compile(
    r"^(?P<name>(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*)"
    r"(?:@(?P<selector>[a-z0-9][a-z0-9._~+*-]*))?$",
    re.IGNORECASE,
)


def _reject_unsafe_package(package):
    """Return an error dict when a package argument could inject CLI options.

    A name starting with '-' still lands in the installer's option parser
    even when passed as one argv item. Returns None when the name is safe.
    """
    if not isinstance(package, str) or not package.strip():
        return {"success": False, "error": "Package name cannot be empty"}

    raw_package = package
    package = raw_package.strip()
    if package != raw_package:
        return {"success": False, "error": "Package name must not contain surrounding whitespace"}
    if any(is_unsafe_terminal_character(character) for character in package):
        return {"success": False, "error": "Package name contains forbidden control characters"}

    if package.startswith("-"):
        return {
            "success": False,
            "error": f"Invalid package name: {package!r} (must not start with '-')",
        }

    return None


def _reject_unsafe_npm_package(package):
    """Reject untrusted npm sources, malware, and unpinned axios versions."""
    unsafe = _reject_unsafe_package(package)
    if unsafe:
        return unsafe

    normalized = str(package).strip().lower()
    registry_spec = NPM_REGISTRY_SPEC_PATTERN.fullmatch(normalized)
    if not registry_spec:
        return {
            "success": False,
            "error": "Only npm registry package names are allowed; URLs, paths, aliases, and git sources are blocked",
        }

    package_name = registry_spec.group("name")
    package_selector = registry_spec.group("selector")
    if package_name == "plain-crypto-js":
        return {"success": False, "error": "Blocked malicious npm package: plain-crypto-js"}

    if package_name == "axios" and package_selector not in SAFE_AXIOS_VERSIONS:
        safe_versions = ", ".join(sorted(SAFE_AXIOS_VERSIONS))
        return {
            "success": False,
            "error": f"Axios must be pinned to a known-safe version: {safe_versions}",
        }
    return None


def _reject_untrusted_npm_package_name(package):
    """Reject npm removal arguments that are not registry package specs."""
    unsafe = _reject_unsafe_package(package)
    if unsafe:
        return unsafe
    if NPM_REGISTRY_SPEC_PATTERN.fullmatch(package.lower()):
        return None
    return {
        "success": False,
        "error": "Only npm registry package names are allowed; URLs, paths, aliases, and git sources are blocked",
    }


def _validate_scaffold_value(value, label):
    """Return an error dict for an unsafe project or template name."""
    if not value or not isinstance(value, str):
        return {"success": False, "error": f"{label} must be a non-empty string"}
    if value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        return {
            "success": False,
            "error": f"Invalid {label.lower()}. Use letters, digits, '.', '_' or '-' only.",
        }
    return None


def _command_result(arguments, result, **metadata):
    """Return a consistent dependency-tool result."""
    return {
        "success": result.get("returncode", 1) == 0,
        "command": format_process_command(arguments),
        "error": result.get("error"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        **metadata,
    }


def list_dependencies():
    """List project dependencies.

    Returns:
        dict with success, dependencies list, package_manager
    """
    project = detect_project_type()
    pkg_manager = project["package_manager"]

    if not pkg_manager:
        return {"success": False, "error": "No package manager detected"}

    if pkg_manager == "pip":
        arguments = ["pip", "list", "--format=json"]
        result = run_process(arguments)
        if result.get("returncode", 1) == 0:
            try:
                import json

                deps = json.loads(result.get("stdout", "[]"))
                return {"success": True, "dependencies": deps, "package_manager": pkg_manager}
            except Exception:
                logger.debug("Failed to parse pip list JSON output, falling back to plain list")
        # Fallback to plain list
        arguments = ["pip", "list"]

    elif pkg_manager in ["npm", "yarn", "pnpm", "bun"]:
        arguments = [pkg_manager, "list", "--depth=0"]

    elif pkg_manager == "go":
        arguments = ["go", "list", "-m", "all"]

    elif pkg_manager == "cargo":
        arguments = ["cargo", "tree", "--depth", "1"]

    elif pkg_manager in ["poetry", "pipenv"]:
        arguments = [pkg_manager, "show"]

    else:
        return {"success": False, "error": f"Unsupported package manager: {pkg_manager}"}

    result = run_process(arguments)

    return {
        "success": result.get("returncode", 1) == 0,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "package_manager": pkg_manager,
    }


def add_dependency(package, dev=False):
    """Add a package dependency.

    Args:
        package: Package name (with optional version like "requests>=2.0")
        dev: Install as dev dependency

    Returns:
        dict with success, package installed
    """
    unsafe = _reject_unsafe_package(package)
    if unsafe:
        return unsafe

    project = detect_project_type()
    pkg_manager = project["package_manager"]

    if not pkg_manager:
        return {"success": False, "error": "No package manager detected"}

    if pkg_manager == "pip":
        arguments = ["pip", "install", "--", package]
    elif pkg_manager == "npm":
        unsafe = _reject_unsafe_npm_package(package)
        if unsafe:
            return unsafe
        flag = "--save-dev" if dev else "--save"
        arguments = ["npm", "install", flag, "--", package]
    elif pkg_manager == "yarn":
        unsafe = _reject_unsafe_npm_package(package)
        if unsafe:
            return unsafe
        flag = "--dev" if dev else ""
        arguments = ["yarn", "add", *([flag] if flag else []), package]
    elif pkg_manager == "pnpm":
        unsafe = _reject_unsafe_npm_package(package)
        if unsafe:
            return unsafe
        flag = "-D" if dev else ""
        arguments = ["pnpm", "add", *([flag] if flag else []), package]
    elif pkg_manager == "go":
        arguments = ["go", "get", package]
    elif pkg_manager == "cargo":
        arguments = ["cargo", "add", package]
    elif pkg_manager == "poetry":
        flag = "--dev" if dev else ""
        arguments = ["poetry", "add", *([flag] if flag else []), package]
    else:
        return {"success": False, "error": f"Unsupported package manager: {pkg_manager}"}

    result = run_process(arguments, timeout=120)

    return {
        "success": result.get("returncode", 1) == 0,
        "package": package,
        "dev": dev,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "package_manager": pkg_manager,
        "command": format_process_command(arguments),
    }


def remove_dependency(package):
    """Remove a package dependency.

    Args:
        package: Package name to remove

    Returns:
        dict with success, package removed
    """
    unsafe = _reject_unsafe_package(package)
    if unsafe:
        return unsafe

    project = detect_project_type()
    pkg_manager = project["package_manager"]

    if not pkg_manager:
        return {"success": False, "error": "No package manager detected"}

    if pkg_manager in {"npm", "yarn", "pnpm"}:
        unsafe = _reject_untrusted_npm_package_name(package)
        if unsafe:
            return unsafe

    if pkg_manager == "pip":
        arguments = ["pip", "uninstall", "-y", "--", package]
    elif pkg_manager == "npm":
        arguments = ["npm", "uninstall", "--", package]
    elif pkg_manager == "yarn":
        arguments = ["yarn", "remove", package]
    elif pkg_manager == "pnpm":
        arguments = ["pnpm", "remove", package]
    elif pkg_manager == "cargo":
        arguments = ["cargo", "remove", package]
    elif pkg_manager == "poetry":
        arguments = ["poetry", "remove", package]
    else:
        return {"success": False, "error": f"Unsupported package manager: {pkg_manager}"}

    result = run_process(arguments, timeout=60)

    return {
        "success": result.get("returncode", 1) == 0,
        "package": package,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "package_manager": pkg_manager,
        "command": format_process_command(arguments),
    }


# Tools installable with npm on every OS.
_NPM_SYSTEM_TOOLS = {
    "claude-code": "@anthropic-ai/claude-code",
    "gemini-cli": "@google/gemini-cli",
    "vercel": "vercel",
    "heroku": "heroku",
}

# OS-specific install commands for tools not available via npm.
_NATIVE_SYSTEM_TOOLS = {
    "gh": {
        "brew": ["brew", "install", "gh"],
        "winget": ["winget", "install", "--id", "GitHub.cli"],
        "dnf": ["dnf", "install", "-y", "gh"],
        "yum": ["yum", "install", "-y", "gh"],
        "pacman": ["pacman", "-S", "--noconfirm", "github-cli"],
        "zypper": ["zypper", "install", "-y", "gh"],
    },
}


def _resolve_native_install_command(tool_name):
    """Return (command, error) for an OS-native system tool.

    Picks a command that fits the detected OS and package manager instead of
    assuming Homebrew. Returns an error with guidance when no safe automated
    command exists for the current platform.
    """
    per_manager = _NATIVE_SYSTEM_TOOLS[tool_name]
    os_family = detect_os()
    manager = detect_package_manager(os_family)
    if manager and manager in per_manager:
        return per_manager[manager], None

    hint = manager or "your system package manager"
    return None, (
        f"No automated install for '{tool_name}' on {os_family}. "
        f"Install it manually with {hint}."
    )


def install_system_tool(tool_name):
    """Install a system-level CLI tool (e.g., claude-code, gemini-cli).

    Args:
        tool_name: Name of tool to install

    Returns:
        dict with success, stdout
    """
    unsafe = _reject_unsafe_package(tool_name)
    if unsafe:
        return unsafe

    for prefix in ("npm:", "pip:", "brew:"):
        if tool_name.startswith(prefix):
            unsafe = _reject_unsafe_package(tool_name[len(prefix):])
            if unsafe:
                return unsafe

    if tool_name in _NPM_SYSTEM_TOOLS:
        package = _NPM_SYSTEM_TOOLS[tool_name]
        unsafe = _reject_unsafe_npm_package(package)
        if unsafe:
            return unsafe
        arguments = ["npm", "install", "-g", "--", package]
    elif tool_name in _NATIVE_SYSTEM_TOOLS:
        arguments, error = _resolve_native_install_command(tool_name)
        if error:
            return {"success": False, "tool": tool_name, "error": error}
    elif tool_name.startswith("npm:"):
        package = tool_name[4:]
        unsafe = _reject_unsafe_npm_package(package)
        if unsafe:
            return unsafe
        arguments = ["npm", "install", "-g", "--", package]
    elif tool_name.startswith("pip:"):
        arguments = ["pip", "install", "--", tool_name[4:]]
    elif tool_name.startswith("brew:"):
        if not shutil.which("brew"):
            return {
                "success": False,
                "tool": tool_name,
                "error": "Homebrew is not installed. Use 'npm:' or 'pip:' prefixes, "
                "or install the tool with your system package manager.",
            }
        arguments = ["brew", "install", "--", tool_name[5:]]
    else:
        return {
            "success": False,
            "error": f"Unknown tool '{tool_name}'. Use prefix like 'npm:package', 'pip:package', or 'brew:package'.",
        }

    result = run_process(arguments, timeout=300)
    return _command_result(arguments, result, tool=tool_name)


def npm_install(package, dev=False, global_install=False):
    """Install an npm package directly (without requiring package.json detection).

    Args:
        package: Package name (e.g., "vite", "react", "@types/node")
        dev: Install as dev dependency (--save-dev)
        global_install: Install globally (-g)

    Returns:
        dict with success, package, stdout, stderr
    """
    unsafe = _reject_unsafe_npm_package(package)
    if unsafe:
        return unsafe

    if global_install:
        arguments = ["npm", "install", "-g", "--", package]
    elif dev:
        arguments = ["npm", "install", "--save-dev", "--", package]
    else:
        arguments = ["npm", "install", "--", package]

    result = run_process(arguments, timeout=120)
    metadata = {"package": package, "dev": dev, "global": global_install}
    return _command_result(arguments, result, **metadata)


def pip_install(package, upgrade=False):
    """Install a pip package directly.

    Args:
        package: Package name (e.g., "flask", "requests>=2.0")
        upgrade: Upgrade if already installed (--upgrade)

    Returns:
        dict with success, package, stdout, stderr
    """
    unsafe = _reject_unsafe_package(package)
    if unsafe:
        return unsafe

    arguments = ["pip", "install"]
    if upgrade:
        arguments.append("--upgrade")
    arguments.extend(["--", package])

    result = run_process(arguments, timeout=120)
    return _command_result(arguments, result, package=package, upgrade=upgrade)


def init_project(project_type, name=None, template=None, working_dir=None):
    """Initialize a new project using common scaffolding tools.

    Args:
        project_type: One of "npm", "vite", "react", "next", "astro", "python"
        name: Project name (used for directory and package name)
        template: Template variant (e.g., "react-ts" for Vite)
        working_dir: Directory to create project in (default: current)

    Returns:
        dict with success, project_type, command, stdout, stderr
    """
    if project_type == "npm":
        arguments = ["npm", "init", "-y"]
    elif project_type == "python":
        return _create_python_project(name or "my_project", working_dir)
    else:
        arguments, error = _build_scaffold_arguments(project_type, name, template)
        if error:
            return {"success": False, "error": error}

    result = run_process(arguments, timeout=300, working_dir=working_dir)
    return _command_result(
        arguments,
        result,
        project_type=project_type,
        name=name,
        template=template,
    )


def _build_scaffold_arguments(project_type, name, template):
    """Return safe argv for a supported JavaScript project scaffold."""
    defaults = {
        "vite": "vite-project",
        "react": "my-app",
        "next": "my-next-app",
        "astro": "my-astro-project",
    }
    if project_type not in defaults:
        supported = "npm, vite, react, next, astro, python"
        return None, f"Unknown project type: {project_type}. Supported: {supported}"

    project_name = name or defaults[project_type]
    unsafe = _validate_scaffold_value(project_name, "Project name")
    if unsafe:
        return None, unsafe["error"]
    if template and (unsafe := _validate_scaffold_value(template, "Template")):
        return None, unsafe["error"]

    return _scaffold_arguments(project_type, project_name, template), None


def _scaffold_arguments(project_type, project_name, template):
    """Build argv after scaffold values have been validated."""
    if project_type == "vite":
        return ["npm", "create", "vite@latest", project_name, "--", "--template", template or "react"]
    if project_type == "react":
        return ["npx", "create-react-app", project_name]
    if project_type == "next":
        return ["npx", "create-next-app@latest", project_name, "--yes"]
    return ["npm", "create", "astro@latest", project_name, "--", "--yes"]


def _create_python_project(project_name, working_dir):
    """Create a minimal Python project (package dir, __init__.py, pyproject.toml).

    Builds files directly instead of chaining shell commands so it is
    cross-platform and never trips shell validation.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", project_name):
        return {
            "success": False,
            "project_type": "python",
            "name": project_name,
            "error": "Invalid Python package name. Use letters, digits, and '_' only.",
        }

    base = (Path(working_dir) if working_dir else Path.cwd()).resolve()
    package_dir = base / project_name
    pyproject = base / "pyproject.toml"

    if not base.is_dir():
        return {"success": False, "error": f"Working directory does not exist: {base}"}
    if package_dir.exists() or pyproject.exists():
        return {"success": False, "error": "Project target already exists; refusing to overwrite"}

    try:
        package_dir.mkdir()
        (package_dir / "__init__.py").touch()
        pyproject.write_text(f'[project]\nname = "{project_name}"\nversion = "0.1.0"\n')
    except OSError as error:
        return {"success": False, "project_type": "python", "name": project_name, "error": str(error)}

    return {
        "success": True,
        "project_type": "python",
        "name": project_name,
        "created": [str(package_dir), str(package_dir / "__init__.py"), str(pyproject)],
    }
