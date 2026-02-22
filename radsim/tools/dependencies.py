"""Dependency management tools for RadSim.

RadSim Principle: One Function, One Purpose
"""

import logging
import os
import shlex

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


def install_system_tool(tool_name):
    """Install a system-level CLI tool (e.g., claude-code, gemini-cli).

    Args:
        tool_name: Name of tool to install

    Returns:
        dict with success, stdout
    """
    # Mappings for known tools
    tool_map = {
        "claude-code": "npm install -g @anthropic-ai/claude-code",
        "gemini-cli": "npm install -g @google/gemini-cli",
        "gh": "brew install gh" if os.name != "nt" else "winget install GitHub.cli",
        "heroku": "brew install heroku/brew/heroku",
        "vercel": "npm install -g vercel",
    }

    # Check if mapped
    if tool_name in tool_map:
        cmd = tool_map[tool_name]
    else:
        # Generic installation strategy
        if tool_name.startswith("npm:"):
            cmd = f"npm install -g {shlex.quote(tool_name[4:])}"
        elif tool_name.startswith("pip:"):
            cmd = f"pip install {shlex.quote(tool_name[4:])}"
        elif tool_name.startswith("brew:"):
            cmd = f"brew install {shlex.quote(tool_name[5:])}"
        else:
            # Default fallback try
            return {
                "success": False,
                "error": f"Unknown tool '{tool_name}'. Use prefix like 'npm:package', 'pip:package', or 'brew:package'.",
            }

    result = run_shell_command(cmd, timeout=300)

    return {
        "success": result.get("returncode", 1) == 0,
        "tool": tool_name,
        "command": cmd,
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
        # Initialize Python project structure
        project_name = name or "my_project"
        safe_name = shlex.quote(project_name)
        # Create basic structure
        commands = [
            f"mkdir -p {safe_name}",
            f"touch {safe_name}/__init__.py",
            f"printf '[project]\\nname = %s\\nversion = \"0.1.0\"\\n' {safe_name} > pyproject.toml",
        ]
        cmd = " && ".join(commands)

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
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }
