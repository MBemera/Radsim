"""Dependency management tools for RadSim.

RadSim Principle: One Function, One Purpose
"""

import logging
import re
import shlex
import shutil
from pathlib import Path

from .platform_detect import detect_os, detect_package_manager
from .shell import run_shell_command
from .testing import detect_project_type

logger = logging.getLogger(__name__)


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
        cmd = "pip list --format=json"
        result = run_shell_command(cmd)
        if result.get("returncode", 1) == 0:
            try:
                import json

                deps = json.loads(result.get("stdout", "[]"))
                return {"success": True, "dependencies": deps, "package_manager": pkg_manager}
            except Exception:
                logger.debug("Failed to parse pip list JSON output, falling back to plain list")
        # Fallback to plain list
        cmd = "pip list"

    elif pkg_manager in ["npm", "yarn", "pnpm", "bun"]:
        cmd = f"{pkg_manager} list --depth=0"

    elif pkg_manager == "go":
        cmd = "go list -m all"

    elif pkg_manager == "cargo":
        cmd = "cargo tree --depth 1"

    elif pkg_manager in ["poetry", "pipenv"]:
        cmd = f"{pkg_manager} show"

    else:
        return {"success": False, "error": f"Unsupported package manager: {pkg_manager}"}

    result = run_shell_command(cmd)

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
    project = detect_project_type()
    pkg_manager = project["package_manager"]

    if not pkg_manager:
        return {"success": False, "error": "No package manager detected"}

    if pkg_manager == "pip":
        cmd = f"pip install {shlex.quote(package)}"
    elif pkg_manager == "npm":
        flag = "--save-dev" if dev else "--save"
        cmd = f"npm install {flag} {shlex.quote(package)}"
    elif pkg_manager == "yarn":
        flag = "--dev" if dev else ""
        cmd = f"yarn add {flag} {shlex.quote(package)}"
    elif pkg_manager == "pnpm":
        flag = "-D" if dev else ""
        cmd = f"pnpm add {flag} {shlex.quote(package)}"
    elif pkg_manager == "go":
        cmd = f"go get {shlex.quote(package)}"
    elif pkg_manager == "cargo":
        cmd = f"cargo add {shlex.quote(package)}"
    elif pkg_manager == "poetry":
        flag = "--dev" if dev else ""
        cmd = f"poetry add {flag} {shlex.quote(package)}"
    else:
        return {"success": False, "error": f"Unsupported package manager: {pkg_manager}"}

    result = run_shell_command(cmd, timeout=120)

    return {
        "success": result.get("returncode", 1) == 0,
        "package": package,
        "dev": dev,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "package_manager": pkg_manager,
    }


def remove_dependency(package):
    """Remove a package dependency.

    Args:
        package: Package name to remove

    Returns:
        dict with success, package removed
    """
    project = detect_project_type()
    pkg_manager = project["package_manager"]

    if not pkg_manager:
        return {"success": False, "error": "No package manager detected"}

    if pkg_manager == "pip":
        cmd = f"pip uninstall -y {shlex.quote(package)}"
    elif pkg_manager == "npm":
        cmd = f"npm uninstall {shlex.quote(package)}"
    elif pkg_manager == "yarn":
        cmd = f"yarn remove {shlex.quote(package)}"
    elif pkg_manager == "pnpm":
        cmd = f"pnpm remove {shlex.quote(package)}"
    elif pkg_manager == "cargo":
        cmd = f"cargo remove {shlex.quote(package)}"
    elif pkg_manager == "poetry":
        cmd = f"poetry remove {shlex.quote(package)}"
    else:
        return {"success": False, "error": f"Unsupported package manager: {pkg_manager}"}

    result = run_shell_command(cmd, timeout=60)

    return {
        "success": result.get("returncode", 1) == 0,
        "package": package,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "package_manager": pkg_manager,
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
        "macos": "brew install gh",
        "windows": "winget install --id GitHub.cli",
        "dnf": "dnf install -y gh",
        "yum": "yum install -y gh",
        "pacman": "pacman -S --noconfirm github-cli",
        "zypper": "zypper install -y gh",
    },
}


def _resolve_native_install_command(tool_name):
    """Return (command, error) for an OS-native system tool.

    Picks a command that fits the detected OS and package manager instead of
    assuming Homebrew. Returns an error with guidance when no safe automated
    command exists for the current platform.
    """
    per_os = _NATIVE_SYSTEM_TOOLS[tool_name]
    os_family = detect_os()

    if os_family in per_os:
        return per_os[os_family], None

    manager = detect_package_manager(os_family)
    if manager and manager in per_os:
        return per_os[manager], None

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
    if tool_name in _NPM_SYSTEM_TOOLS:
        cmd = f"npm install -g {shlex.quote(_NPM_SYSTEM_TOOLS[tool_name])}"
    elif tool_name in _NATIVE_SYSTEM_TOOLS:
        cmd, error = _resolve_native_install_command(tool_name)
        if error:
            return {"success": False, "tool": tool_name, "error": error}
    elif tool_name.startswith("npm:"):
        cmd = f"npm install -g {shlex.quote(tool_name[4:])}"
    elif tool_name.startswith("pip:"):
        cmd = f"pip install {shlex.quote(tool_name[4:])}"
    elif tool_name.startswith("brew:"):
        if not shutil.which("brew"):
            return {
                "success": False,
                "tool": tool_name,
                "error": "Homebrew is not installed. Use 'npm:' or 'pip:' prefixes, "
                "or install the tool with your system package manager.",
            }
        cmd = f"brew install {shlex.quote(tool_name[5:])}"
    else:
        return {
            "success": False,
            "error": f"Unknown tool '{tool_name}'. Use prefix like 'npm:package', 'pip:package', or 'brew:package'.",
        }

    result = run_shell_command(cmd, timeout=300)

    return {
        "success": result.get("returncode", 1) == 0,
        "tool": tool_name,
        "command": cmd,
        "error": result.get("error"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


def npm_install(package, dev=False, global_install=False):
    """Install an npm package directly (without requiring package.json detection).

    Args:
        package: Package name (e.g., "vite", "react", "@types/node")
        dev: Install as dev dependency (--save-dev)
        global_install: Install globally (-g)

    Returns:
        dict with success, package, stdout, stderr
    """
    if global_install:
        cmd = f"npm install -g {shlex.quote(package)}"
    elif dev:
        cmd = f"npm install --save-dev {shlex.quote(package)}"
    else:
        cmd = f"npm install {shlex.quote(package)}"

    result = run_shell_command(cmd, timeout=120)

    return {
        "success": result.get("returncode", 1) == 0,
        "package": package,
        "dev": dev,
        "global": global_install,
        "command": cmd,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


def pip_install(package, upgrade=False):
    """Install a pip package directly.

    Args:
        package: Package name (e.g., "flask", "requests>=2.0")
        upgrade: Upgrade if already installed (--upgrade)

    Returns:
        dict with success, package, stdout, stderr
    """
    flag = "--upgrade" if upgrade else ""
    cmd = f"pip install {flag} {shlex.quote(package)}".strip()

    result = run_shell_command(cmd, timeout=120)

    return {
        "success": result.get("returncode", 1) == 0,
        "package": package,
        "upgrade": upgrade,
        "command": cmd,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


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
    # Build command based on project type
    if project_type == "npm":
        # Just initialize package.json
        cmd = "npm init -y"

    elif project_type == "vite":
        # Create Vite project
        project_name = name or "vite-project"
        if template:
            cmd = f"npm create vite@latest {shlex.quote(project_name)} -- --template {shlex.quote(template)}"
        else:
            cmd = f"npm create vite@latest {shlex.quote(project_name)} -- --template react"

    elif project_type == "react":
        # Create React App
        project_name = name or "my-app"
        cmd = f"npx create-react-app {shlex.quote(project_name)}"

    elif project_type == "next":
        # Create Next.js project
        project_name = name or "my-next-app"
        cmd = f"npx create-next-app@latest {shlex.quote(project_name)} --yes"

    elif project_type == "astro":
        # Create Astro project
        project_name = name or "my-astro-project"
        cmd = f"npm create astro@latest {shlex.quote(project_name)} -- --yes"

    elif project_type == "python":
        # Build the Python project structure directly with pathlib. No shell
        # chaining, so it works identically on Linux, macOS, and Windows.
        return _create_python_project(name or "my_project", working_dir)

    else:
        return {
            "success": False,
            "error": f"Unknown project type: {project_type}. Supported: npm, vite, react, next, astro, python",
        }

    result = run_shell_command(cmd, timeout=300, working_dir=working_dir)

    return {
        "success": result.get("returncode", 1) == 0,
        "project_type": project_type,
        "name": name,
        "template": template,
        "command": cmd,
        "error": result.get("error"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


def _create_python_project(project_name, working_dir):
    """Create a minimal Python project (package dir, __init__.py, pyproject.toml).

    Builds files directly instead of chaining shell commands so it is
    cross-platform and never trips shell validation.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", project_name) or project_name in (".", ".."):
        return {
            "success": False,
            "project_type": "python",
            "name": project_name,
            "error": "Invalid project name. Use letters, digits, '.', '_' or '-' only.",
        }

    base = Path(working_dir) if working_dir else Path.cwd()
    package_dir = base / project_name

    try:
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "__init__.py").touch()
        pyproject = base / "pyproject.toml"
        pyproject.write_text(
            f'[project]\nname = "{project_name}"\nversion = "0.1.0"\n'
        )
    except OSError as error:
        return {"success": False, "project_type": "python", "name": project_name, "error": str(error)}

    return {
        "success": True,
        "project_type": "python",
        "name": project_name,
        "created": [str(package_dir), str(package_dir / "__init__.py"), str(pyproject)],
    }
