"""Advanced tools for RadSim (Docker, Database, Refactoring, Deploy).

RadSim Principle: One Function, One Purpose
"""

import ast
import json
import logging
import re
import shlex
from pathlib import Path

from .shell import run_shell_command
from .validation import validate_path

logger = logging.getLogger(__name__)


def run_docker(action, container=None, image=None, command=None, options=None):
    """Run Docker commands for container management.

    Args:
        action: Docker action ('ps', 'images', 'run', 'stop', 'start', 'logs', 'exec', 'build', 'pull')
        container: Container name/ID (for stop, start, logs, exec)
        image: Image name (for run, pull, build)
        command: Command to run (for run, exec)
        options: Additional options as string

    Returns:
        dict with success, output
    """
    # Check if Docker is available
    check = run_shell_command("docker --version", timeout=10)
    if not check["success"]:
        return {"success": False, "error": "Docker is not installed or not running"}

    valid_actions = [
        "ps",
        "images",
        "run",
        "stop",
        "start",
        "logs",
        "exec",
        "build",
        "pull",
        "rm",
        "rmi",
    ]
    if action not in valid_actions:
        return {"success": False, "error": f"Invalid action. Valid: {', '.join(valid_actions)}"}

    # Build the command
    cmd_parts = ["docker", action]

    if action == "ps":
        cmd_parts.append("-a")  # Show all containers

    elif action == "images":
        pass  # No extra args needed

    elif action == "run":
        if not image:
            return {"success": False, "error": "Image required for 'run' action"}
        if options:
            cmd_parts.extend(shlex.split(options))
        cmd_parts.append(shlex.quote(image))
        if command:
            cmd_parts.extend(shlex.split(command))

    elif action in ["stop", "start", "logs", "rm"]:
        if not container:
            return {"success": False, "error": f"Container required for '{action}' action"}
        if action == "logs":
            cmd_parts.extend(["--tail", "100"])
        cmd_parts.append(shlex.quote(container))

    elif action == "exec":
        if not container:
            return {"success": False, "error": "Container required for 'exec' action"}
        if not command:
            return {"success": False, "error": "Command required for 'exec' action"}
        cmd_parts.extend(["-it", shlex.quote(container)])
        cmd_parts.extend(shlex.split(command))

    elif action == "build":
        if options:
            cmd_parts.extend(shlex.split(options))
        cmd_parts.append(".")  # Build from current directory

    elif action == "pull":
        if not image:
            return {"success": False, "error": "Image required for 'pull' action"}
        cmd_parts.append(shlex.quote(image))

    elif action == "rmi":
        if not image:
            return {"success": False, "error": "Image required for 'rmi' action"}
        cmd_parts.append(shlex.quote(image))

    docker_cmd = " ".join(cmd_parts)
    result = run_shell_command(docker_cmd, timeout=300)

    return {
        "success": result["success"],
        "command": docker_cmd,
        "output": result.get("stdout", ""),
        "error": result.get("stderr") or result.get("error", ""),
    }


def database_query(query, database_path="database.db", read_only=True):
    """Execute a query on a SQLite database.

    Args:
        query: SQL query to execute
        database_path: Path to the SQLite database file
        read_only: If True, only allow SELECT queries (default: True)

    Returns:
        dict with success, results, columns
    """
    import sqlite3

    is_safe, path, error = validate_path(database_path, allow_outside=True)
    if not is_safe:
        return {"success": False, "error": error}

    # Security: Only allow SELECT in read_only mode
    query_upper = query.strip().upper()
    is_select = query_upper.startswith("SELECT")

    if read_only and not is_select:
        return {
            "success": False,
            "error": "Only SELECT queries allowed in read_only mode. Set read_only=False for write operations.",
        }

    # Block dangerous operations even in write mode
    dangerous = ["DROP DATABASE", "DROP TABLE", "TRUNCATE", "DELETE FROM"]
    for d in dangerous:
        if d in query_upper and "WHERE" not in query_upper:
            return {
                "success": False,
                "error": f"Dangerous operation blocked: {d} without WHERE clause",
            }

    try:
        # Check if database exists in read_only mode
        if read_only and not path.exists():
            return {"success": False, "error": f"Database file not found: {database_path}"}

        # Connect with read-only URI if read_only mode
        if read_only and path.exists():
            uri = f"file:{path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
        else:
            conn = sqlite3.connect(str(path))

        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(query)

        if is_select:
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            results = [dict(row) for row in rows]

            conn.close()
            return {
                "success": True,
                "query": query,
                "columns": columns,
                "results": results[:100],  # Limit to 100 rows
                "row_count": len(results),
                "truncated": len(results) > 100,
            }
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return {"success": True, "query": query, "rows_affected": affected}

    except sqlite3.Error as e:
        return {"success": False, "error": f"SQLite error: {e}"}
    except Exception as error:
        return {"success": False, "error": str(error)}


def generate_tests(source_file, output_file=None, framework="pytest"):
    """Generate test stubs for a Python source file.

    Args:
        source_file: Path to the source file to generate tests for
        output_file: Path for the test file (default: test_<source_file>)
        framework: Test framework ('pytest' or 'unittest')

    Returns:
        dict with success, generated_tests, output_file
    """
    is_safe, path, error = validate_path(source_file)
    if not is_safe:
        return {"success": False, "error": error}

    if not path.exists():
        return {"success": False, "error": f"Source file not found: {source_file}"}

    if not str(path).endswith(".py"):
        return {"success": False, "error": "generate_tests only supports Python files"}

    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)

        # Determine output file
        if not output_file:
            output_file = f"test_{path.name}"

        module_name = path.stem

        # Collect functions and classes
        functions = []
        classes = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    functions.append(
                        {
                            "name": node.name,
                            "args": [arg.arg for arg in node.args.args if arg.arg != "self"],
                            "is_async": isinstance(node, ast.AsyncFunctionDef),
                            "docstring": ast.get_docstring(node) or "",
                        }
                    )
            elif isinstance(node, ast.ClassDef):
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith("_") or item.name in [
                            "__init__",
                            "__str__",
                            "__repr__",
                        ]:
                            methods.append(
                                {
                                    "name": item.name,
                                    "args": [
                                        arg.arg for arg in item.args.args if arg.arg != "self"
                                    ],
                                    "is_async": isinstance(item, ast.AsyncFunctionDef),
                                }
                            )
                classes.append(
                    {
                        "name": node.name,
                        "methods": methods,
                        "docstring": ast.get_docstring(node) or "",
                    }
                )

        # Generate test code
        if framework == "pytest":
            test_code = _generate_pytest_tests(module_name, functions, classes)
        else:
            test_code = _generate_unittest_tests(module_name, functions, classes)

        return {
            "success": True,
            "source_file": str(path),
            "output_file": output_file,
            "generated_tests": test_code,
            "function_count": len(functions),
            "class_count": len(classes),
            "framework": framework,
        }

    except SyntaxError as e:
        return {"success": False, "error": f"Syntax error in source: {e}"}
    except Exception as error:
        return {"success": False, "error": str(error)}


def _generate_pytest_tests(module_name, functions, classes):
    """Generate pytest-style tests."""
    lines = [
        f'"""Tests for {module_name} module."""',
        "",
        "import pytest",
        f"from {module_name} import *",
        "",
        "",
    ]

    # Generate function tests
    for func in functions:
        lines.append(f"class Test{func['name'].title().replace('_', '')}:")
        lines.append(f'    """Tests for {func["name"]} function."""')
        lines.append("")
        lines.append(f"    def test_{func['name']}_basic(self):")
        lines.append(f'        """Test {func["name"]} with basic input."""')
        if func["args"]:
            args_str = ", ".join(["None"] * len(func["args"]))
            lines.append(f"        result = {func['name']}({args_str})")
        else:
            lines.append(f"        result = {func['name']}()")
        lines.append("        assert result is not None  # TODO: Add proper assertion")
        lines.append("")
        lines.append(f"    def test_{func['name']}_edge_case(self):")
        lines.append(f'        """Test {func["name"]} edge cases."""')
        lines.append("        # TODO: Implement edge case tests")
        lines.append("        pass")
        lines.append("")
        lines.append("")

    # Generate class tests
    for cls in classes:
        lines.append(f"class Test{cls['name']}:")
        lines.append(f'    """Tests for {cls["name"]} class."""')
        lines.append("")
        lines.append("    @pytest.fixture")
        lines.append("    def instance(self):")
        lines.append(f'        """Create a {cls["name"]} instance for testing."""')
        lines.append(f"        return {cls['name']}()  # TODO: Add constructor args")
        lines.append("")

        for method in cls["methods"]:
            if method["name"] == "__init__":
                continue
            lines.append(f"    def test_{method['name']}(self, instance):")
            lines.append(f'        """Test {cls["name"]}.{method["name"]} method."""')
            if method["args"]:
                args_str = ", ".join(["None"] * len(method["args"]))
                lines.append(f"        result = instance.{method['name']}({args_str})")
            else:
                lines.append(f"        result = instance.{method['name']}()")
            lines.append("        assert result is not None  # TODO: Add proper assertion")
            lines.append("")

        lines.append("")

    return "\n".join(lines)


def _generate_unittest_tests(module_name, functions, classes):
    """Generate unittest-style tests."""
    lines = [
        f'"""Tests for {module_name} module."""',
        "",
        "import unittest",
        f"from {module_name} import *",
        "",
        "",
    ]

    # Generate function tests
    for func in functions:
        lines.append(f"class Test{func['name'].title().replace('_', '')}(unittest.TestCase):")
        lines.append(f'    """Tests for {func["name"]} function."""')
        lines.append("")
        lines.append(f"    def test_{func['name']}_basic(self):")
        lines.append(f'        """Test {func["name"]} with basic input."""')
        if func["args"]:
            args_str = ", ".join(["None"] * len(func["args"]))
            lines.append(f"        result = {func['name']}({args_str})")
        else:
            lines.append(f"        result = {func['name']}()")
        lines.append("        self.assertIsNotNone(result)  # TODO: Add proper assertion")
        lines.append("")
        lines.append("")

    # Generate class tests
    for cls in classes:
        lines.append(f"class Test{cls['name']}(unittest.TestCase):")
        lines.append(f'    """Tests for {cls["name"]} class."""')
        lines.append("")
        lines.append("    def setUp(self):")
        lines.append(f'        """Set up {cls["name"]} instance."""')
        lines.append(f"        self.instance = {cls['name']}()  # TODO: Add constructor args")
        lines.append("")

        for method in cls["methods"]:
            if method["name"] == "__init__":
                continue
            lines.append(f"    def test_{method['name']}(self):")
            lines.append(f'        """Test {cls["name"]}.{method["name"]} method."""')
            if method["args"]:
                args_str = ", ".join(["None"] * len(method["args"]))
                lines.append(f"        result = self.instance.{method['name']}({args_str})")
            else:
                lines.append(f"        result = self.instance.{method['name']}()")
            lines.append("        self.assertIsNotNone(result)  # TODO: Add proper assertion")
            lines.append("")

        lines.append("")

    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    unittest.main()")
    lines.append("")

    return "\n".join(lines)


def refactor_code(
    action, file_path, old_name=None, new_name=None, target_line=None, new_function_name=None
):
    """Perform code refactoring operations.

    Args:
        action: Refactoring action ('rename', 'extract_function', 'inline_variable')
        file_path: Path to the file to refactor
        old_name: Current name (for rename)
        new_name: New name (for rename)
        target_line: Line number for extraction
        new_function_name: Name for extracted function

    Returns:
        dict with success, changes made
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}

    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        # Read file content
        content = path.read_text(encoding="utf-8")

        if action == "rename":
            if not old_name or not new_name:
                return {"success": False, "error": "Both old_name and new_name required for rename"}

            # Simple word-boundary rename
            pattern = rf"\b{re.escape(old_name)}\b"
            count = len(re.findall(pattern, content))

            if count == 0:
                return {"success": False, "error": f"'{old_name}' not found in file"}

            content = re.sub(pattern, new_name, content)
            path.write_text(content, encoding="utf-8")

            return {
                "success": True,
                "action": "rename",
                "file": str(path),
                "old_name": old_name,
                "new_name": new_name,
                "replacements": count,
            }

        elif action == "extract_function":
            if not target_line or not new_function_name:
                return {
                    "success": False,
                    "error": "target_line and new_function_name required for extract_function",
                }

            lines = content.splitlines()
            if target_line < 1 or target_line > len(lines):
                return {"success": False, "error": f"Invalid line number: {target_line}"}

            # Extract the line and replace with function call
            extracted_line = lines[target_line - 1]
            indent = len(extracted_line) - len(extracted_line.lstrip())
            indent_str = " " * indent

            # Create new function
            new_function = f"\ndef {new_function_name}():\n    {extracted_line.strip()}\n"

            # Replace line with function call
            lines[target_line - 1] = f"{indent_str}{new_function_name}()"

            # Add function at the end
            new_content = "\n".join(lines) + new_function
            path.write_text(new_content, encoding="utf-8")

            return {
                "success": True,
                "action": "extract_function",
                "file": str(path),
                "extracted_line": target_line,
                "new_function": new_function_name,
            }

        elif action == "inline_variable":
            if not old_name:
                return {
                    "success": False,
                    "error": "old_name (variable name) required for inline_variable",
                }

            # Find variable assignment
            pattern = rf"^(\s*){re.escape(old_name)}\s*=\s*(.+)$"
            match = re.search(pattern, content, re.MULTILINE)

            if not match:
                return {"success": False, "error": f"Assignment for '{old_name}' not found"}

            value = match.group(2).strip()

            # Remove the assignment line
            content = re.sub(pattern + r"\n?", "", content, count=1, flags=re.MULTILINE)

            # Replace all uses with the value
            use_pattern = rf"\b{re.escape(old_name)}\b"
            count = len(re.findall(use_pattern, content))
            content = re.sub(use_pattern, value, content)

            path.write_text(content, encoding="utf-8")

            return {
                "success": True,
                "action": "inline_variable",
                "file": str(path),
                "variable": old_name,
                "value": value,
                "replacements": count,
            }

        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}. Valid: rename, extract_function, inline_variable",
            }

    except Exception as error:
        return {"success": False, "error": str(error)}


def deploy(platform=None, check_only=False, command=None):
    """Deploy application or check deployment readiness.

    Args:
        platform: Target platform ('vercel', 'netlify', 'heroku', 'railway', 'flyio', 'auto')
        check_only: If True, only check readiness, don't deploy
        command: Custom deploy command to run

    Returns:
        dict with success, deployment info
    """
    cwd = Path.cwd()

    # Platform detection based on config files
    platform_configs = {
        "vercel": ["vercel.json", ".vercel"],
        "netlify": ["netlify.toml", ".netlify"],
        "heroku": ["Procfile", "app.json"],
        "railway": ["railway.json", "railway.toml"],
        "flyio": ["fly.toml"],
    }

    detected_platforms = []
    for plat, files in platform_configs.items():
        for f in files:
            if (cwd / f).exists():
                detected_platforms.append(plat)
                break

    # Also check package.json scripts
    package_json = cwd / "package.json"
    has_build_script = False
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text())
            scripts = pkg.get("scripts", {})
            has_build_script = "build" in scripts
        except (json.JSONDecodeError, OSError):
            logger.debug("Failed to parse package.json for deploy platform detection")

    # Auto-detect platform
    if platform == "auto" or platform is None:
        if detected_platforms:
            platform = detected_platforms[0]
        elif has_build_script:
            platform = "vercel"  # Default for JS projects
        else:
            platform = None

    result = {
        "success": True,
        "detected_platforms": detected_platforms,
        "selected_platform": platform,
        "has_build_script": has_build_script,
        "check_only": check_only,
    }

    if check_only:
        # Just return readiness info
        result["ready"] = len(detected_platforms) > 0 or has_build_script
        result["recommendations"] = []

        if not detected_platforms and not has_build_script:
            result["recommendations"].append(
                "No deployment config found. Consider adding vercel.json, netlify.toml, or Procfile"
            )
        if not (cwd / ".gitignore").exists():
            result["recommendations"].append("Add a .gitignore file")
        if not (cwd / "README.md").exists():
            result["recommendations"].append("Add a README.md file")

        return result

    # Execute deployment
    if command:
        # Validate the custom command can be parsed safely
        try:
            shlex.split(command)
        except ValueError:
            return {"success": False, "error": "Invalid deploy command format"}
        deploy_cmd = command
    elif platform == "vercel":
        deploy_cmd = "vercel --prod" if (cwd / ".vercel").exists() else "vercel"
    elif platform == "netlify":
        deploy_cmd = "netlify deploy --prod"
    elif platform == "heroku":
        deploy_cmd = "git push heroku main"
    elif platform == "railway":
        deploy_cmd = "railway up"
    elif platform == "flyio":
        deploy_cmd = "fly deploy"
    else:
        return {
            "success": False,
            "error": "No platform detected and none specified. Use platform='vercel' or similar, or provide a custom command",
        }

    # Check if CLI is installed
    cli_check = {
        "vercel": "vercel --version",
        "netlify": "netlify --version",
        "heroku": "heroku --version",
        "railway": "railway --version",
        "flyio": "fly version",
    }

    if platform in cli_check:
        check = run_shell_command(cli_check[platform], timeout=10)
        if not check["success"]:
            return {
                "success": False,
                "error": f"{platform} CLI not installed. Install with: npm i -g {platform}"
                if platform != "flyio"
                else f"{platform} CLI not installed. See https://fly.io/docs/getting-started/installing-flyctl/",
                "platform": platform,
            }

    # Run the deploy command
    deploy_result = run_shell_command(deploy_cmd, timeout=600)

    result["deploy_command"] = deploy_cmd
    result["output"] = deploy_result.get("stdout", "")
    result["error"] = deploy_result.get("stderr", "")
    result["success"] = deploy_result["success"]

    return result
