"""Testing and validation tools for RadSim.

RadSim Principle: One Function, One Purpose
"""

import shlex
from pathlib import Path

from .shell import run_shell_command


def detect_project_type():
    """Detect project type based on config files present.

    Returns:
        dict with project_type, test_framework, lint_tool, format_tool
    """
    cwd = Path.cwd()
    result = {
        "project_type": "unknown",
        "test_framework": None,
        "lint_tool": None,
        "format_tool": None,
        "type_checker": None,
        "package_manager": None,
    }

    # Python project detection
    if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
        result["project_type"] = "python"
        result["test_framework"] = "pytest"
        result["lint_tool"] = "ruff"
        result["format_tool"] = "ruff format"
        result["type_checker"] = "mypy"
        result["package_manager"] = "pip"

        if (cwd / "requirements.txt").exists():
            result["package_manager"] = "pip"
        if (cwd / "Pipfile").exists():
            result["package_manager"] = "pipenv"
        if (cwd / "poetry.lock").exists():
            result["package_manager"] = "poetry"

    # Node.js project detection
    elif (cwd / "package.json").exists():
        result["project_type"] = "node"
        result["package_manager"] = "npm"

        if (cwd / "yarn.lock").exists():
            result["package_manager"] = "yarn"
        if (cwd / "pnpm-lock.yaml").exists():
            result["package_manager"] = "pnpm"
        if (cwd / "bun.lockb").exists():
            result["package_manager"] = "bun"

        # Check package.json for test/lint scripts
        try:
            import json

            pkg = json.loads((cwd / "package.json").read_text())
            scripts = pkg.get("scripts", {})

            if "test" in scripts:
                if "jest" in scripts["test"]:
                    result["test_framework"] = "jest"
                elif "vitest" in scripts["test"]:
                    result["test_framework"] = "vitest"
                elif "mocha" in scripts["test"]:
                    result["test_framework"] = "mocha"
                else:
                    result["test_framework"] = "npm test"

            if "lint" in scripts:
                result["lint_tool"] = "npm run lint"
            elif (cwd / ".eslintrc.js").exists() or (cwd / ".eslintrc.json").exists():
                result["lint_tool"] = "eslint"

            if "format" in scripts:
                result["format_tool"] = "npm run format"
            elif (cwd / ".prettierrc").exists() or (cwd / "prettier.config.js").exists():
                result["format_tool"] = "prettier --write"

            # TypeScript detection
            if (cwd / "tsconfig.json").exists():
                result["type_checker"] = "tsc --noEmit"

        except Exception:
            result["test_framework"] = "npm test"
            result["lint_tool"] = "npm run lint"

    # Go project detection
    elif (cwd / "go.mod").exists():
        result["project_type"] = "go"
        result["test_framework"] = "go test ./..."
        result["lint_tool"] = "golangci-lint run"
        result["format_tool"] = "gofmt -w"
        result["type_checker"] = "go vet ./..."
        result["package_manager"] = "go"

    # Rust project detection
    elif (cwd / "Cargo.toml").exists():
        result["project_type"] = "rust"
        result["test_framework"] = "cargo test"
        result["lint_tool"] = "cargo clippy"
        result["format_tool"] = "cargo fmt"
        result["type_checker"] = "cargo check"
        result["package_manager"] = "cargo"

    return result


def run_tests(test_command=None, test_path=None, verbose=False):
    """Run project tests with auto-detection.

    Args:
        test_command: Override auto-detected test command
        test_path: Specific test file/directory to run
        verbose: Show verbose output

    Returns:
        dict with success, stdout, stderr, framework
    """
    if test_command:
        cmd = test_command
        framework = "custom"
    else:
        project = detect_project_type()
        framework = project["test_framework"]

        if not framework:
            return {
                "success": False,
                "error": "No test framework detected. Use test_command parameter.",
            }

        cmd = framework

    if test_path:
        cmd += f" {shlex.quote(test_path)}"

    if verbose:
        if "pytest" in cmd:
            cmd += " -v"
        elif "jest" in cmd or "vitest" in cmd:
            cmd += " --verbose"
        elif "go test" in cmd:
            cmd += " -v"

    result = run_shell_command(cmd, timeout=300)

    return {
        "success": result.get("returncode", 1) == 0,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "returncode": result.get("returncode", 1),
        "framework": framework,
        "command": cmd,
    }


def lint_code(file_path=None, fix=False):
    """Run linter on project or specific file.

    Args:
        file_path: Specific file to lint (optional)
        fix: Auto-fix issues if possible

    Returns:
        dict with success, stdout, stderr, linter
    """
    project = detect_project_type()
    linter = project["lint_tool"]

    if not linter:
        return {"success": False, "error": "No linter detected for this project type."}

    cmd = linter

    # Add fix flag based on linter
    if fix:
        if "ruff" in linter:
            cmd += " --fix"
        elif "eslint" in linter:
            cmd += " --fix"
        elif "golangci-lint" in linter:
            cmd += " --fix"

    if file_path:
        cmd += f" {shlex.quote(file_path)}"
    elif project["project_type"] == "python":
        cmd += " ."
    elif project["project_type"] == "node":
        cmd += " src/"

    result = run_shell_command(cmd, timeout=120)

    return {
        "success": result.get("returncode", 1) == 0,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "returncode": result.get("returncode", 1),
        "linter": linter,
        "command": cmd,
    }


def format_code(file_path=None, check_only=False):
    """Format code using project formatter.

    Args:
        file_path: Specific file to format (optional)
        check_only: Only check formatting, don't modify files

    Returns:
        dict with success, stdout, stderr, formatter
    """
    project = detect_project_type()
    formatter = project["format_tool"]

    if not formatter:
        return {"success": False, "error": "No formatter detected for this project type."}

    cmd = formatter

    # Add check flag based on formatter
    if check_only:
        if "ruff format" in formatter:
            cmd += " --check"
        elif "prettier" in formatter:
            cmd = cmd.replace("--write", "--check")
        elif "gofmt" in formatter:
            cmd = "gofmt -l"  # List files that need formatting
        elif "cargo fmt" in formatter:
            cmd += " -- --check"

    if file_path:
        cmd += f" {shlex.quote(file_path)}"
    elif project["project_type"] == "python":
        cmd += " ."

    result = run_shell_command(cmd, timeout=60)

    return {
        "success": result.get("returncode", 1) == 0,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "returncode": result.get("returncode", 1),
        "formatter": formatter,
        "command": cmd,
    }


def type_check(file_path=None):
    """Run type checker on project or file.

    Args:
        file_path: Specific file to check (optional)

    Returns:
        dict with success, stdout, stderr, checker
    """
    project = detect_project_type()
    checker = project["type_checker"]

    if not checker:
        return {"success": False, "error": "No type checker detected for this project type."}

    cmd = checker

    if file_path:
        if "mypy" in checker:
            cmd = f"mypy {shlex.quote(file_path)}"
        elif "tsc" in checker:
            cmd = f"tsc --noEmit {shlex.quote(file_path)}"

    result = run_shell_command(cmd, timeout=120)

    return {
        "success": result.get("returncode", 1) == 0,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "returncode": result.get("returncode", 1),
        "checker": checker,
        "command": cmd,
    }
