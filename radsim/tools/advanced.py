"""Advanced tools for RadSim (Docker, Database, Refactoring, Deploy).

RadSim Principle: One Function, One Purpose
"""

import ast
import builtins
import json
import keyword
import logging
import os
import re
import shlex
from pathlib import Path

from ..terminal import is_unsafe_terminal_character
from .command_analysis import is_catastrophic_command
from .shell import format_process_command, run_process
from .validation import validate_path

logger = logging.getLogger(__name__)


def _docker_identifier_error(value, label):
    """Return an error for an invalid container or image identifier."""
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        return f"{label} must be a non-empty string"
    if value.startswith("-"):
        return f"{label} must not start with '-'"
    if any(is_unsafe_terminal_character(character) for character in value):
        return f"{label} must not contain control characters"
    return None


def _split_docker_arguments(value):
    """Return explicit Docker argv, allowing legacy strings only on POSIX."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if not isinstance(value, str):
        raise ValueError("Docker arguments must be a string or list")
    if os.name == "nt":
        raise ValueError("Docker command and options must use argument lists on Windows")
    return shlex.split(value)


def run_docker(action, container=None, image=None, command=None, options=None):
    """Run Docker commands for container management.

    Args:
        action: Docker action ('ps', 'images', 'run', 'stop', 'start', 'logs', 'exec', 'build', 'pull')
        container: Container name/ID (for stop, start, logs, exec)
        image: Image name (for run, pull, build)
        command: Command to run (for run, exec)
        options: Additional options as a string or argument list

    Returns:
        dict with success, output
    """
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

    try:
        option_arguments = _split_docker_arguments(options)
        command_arguments = _split_docker_arguments(command)
    except ValueError as argument_error:
        return {"success": False, "error": str(argument_error)}
    for value, label in ((container, "Container"), (image, "Image")):
        if validation_error := _docker_identifier_error(value, label):
            return {"success": False, "error": validation_error}

    # Build the command
    cmd_parts = ["docker", action]

    if action == "ps":
        cmd_parts.append("-a")  # Show all containers

    elif action == "images":
        pass  # No extra args needed

    elif action == "run":
        if not image:
            return {"success": False, "error": "Image required for 'run' action"}
        cmd_parts.extend(option_arguments)
        cmd_parts.append(image)
        cmd_parts.extend(command_arguments)

    elif action in ["stop", "start", "logs", "rm"]:
        if not container:
            return {"success": False, "error": f"Container required for '{action}' action"}
        if action == "logs":
            cmd_parts.extend(["--tail", "100"])
        cmd_parts.append(container)

    elif action == "exec":
        if not container:
            return {"success": False, "error": "Container required for 'exec' action"}
        if not command:
            return {"success": False, "error": "Command required for 'exec' action"}
        cmd_parts.append(container)
        cmd_parts.extend(command_arguments)

    elif action == "build":
        cmd_parts.extend(option_arguments)
        cmd_parts.append(".")  # Build from current directory

    elif action == "pull":
        if not image:
            return {"success": False, "error": "Image required for 'pull' action"}
        cmd_parts.append(image)

    elif action == "rmi":
        if not image:
            return {"success": False, "error": "Image required for 'rmi' action"}
        cmd_parts.append(image)

    if any(
        not isinstance(part, str)
        or not part
        or any(is_unsafe_terminal_character(character) for character in part)
        for part in cmd_parts
    ):
        return {"success": False, "error": "Docker arguments must be non-empty strings"}

    check = run_process(["docker", "--version"], timeout=10)
    if not check["success"]:
        return {"success": False, "error": "Docker is not installed or not running"}

    docker_cmd = format_process_command(cmd_parts)
    result = run_process(cmd_parts, timeout=300)

    return {
        "success": result["success"],
        "command": docker_cmd,
        "output": result.get("stdout", ""),
        "error": result.get("stderr") or result.get("error", ""),
    }


def _has_multiple_statements(query):
    """Return True when the query holds more than one SQL statement.

    Semicolons inside string literals are ignored, so "SELECT ';'" stays a
    single statement while "SELECT 1; DROP TABLE t" does not.
    """
    open_quote = None
    for index, character in enumerate(query):
        if open_quote:
            if character == open_quote:
                open_quote = None
            continue
        if character in ("'", '"'):
            open_quote = character
            continue
        if character == ";" and query[index + 1 :].strip():
            return True
    return False


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

    if _has_multiple_statements(query):
        return {
            "success": False,
            "error": (
                "Blocked: only one SQL statement per call is allowed. "
                "Remove everything after the first ';' and call the tool again."
            ),
        }

    # Security: Only allow SELECT in read_only mode
    query_upper = query.strip().upper()
    is_select = query_upper.startswith("SELECT")

    if read_only and not is_select:
        return {
            "success": False,
            "error": "Only SELECT queries allowed in read_only mode. Set read_only=False for write operations.",
        }

    # Destructive statements are never allowed through this tool; mass
    # deletes need an explicit WHERE clause. The error must explain the
    # working alternative, because the model reads it to plan its retry.
    for statement in ("DROP DATABASE", "DROP TABLE", "TRUNCATE"):
        if statement in query_upper:
            return {
                "success": False,
                "error": (
                    f"Blocked: {statement} is not allowed through database_query. "
                    "If the user explicitly wants this, run it via run_shell_command "
                    "with the sqlite3 CLI so they can confirm it."
                ),
            }
    if "DELETE FROM" in query_upper and "WHERE" not in query_upper:
        return {
            "success": False,
            "error": (
                "Blocked: DELETE without a WHERE clause would remove every row. "
                "Add a WHERE clause, or confirm the full wipe with the user and "
                "run it via run_shell_command with the sqlite3 CLI."
            ),
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


def _test_module_imports(module_name, functions, classes):
    """Return explicit import lines for exactly the names the tests use."""
    imported_names = [function["name"] for function in functions]
    imported_names += [cls["name"] for cls in classes]
    return [f"from {module_name} import {name}" for name in imported_names]


def _placeholder_call(callable_expression, argument_names):
    """Return a call that names the real parameters as placeholders.

    The placeholders are deliberately undefined. Every generated test is
    skipped until a developer fills them in, so a stub can never report
    coverage it does not have.
    """
    return f"{callable_expression}({', '.join(argument_names)})"


def _constructor_arguments(cls):
    """Return the __init__ parameter names for a collected class."""
    for method in cls["methods"]:
        if method["name"] == "__init__":
            return method["args"]
    return []


def _generate_pytest_tests(module_name, functions, classes):
    """Generate pytest-style test stubs."""
    lines = [f'"""Tests for {module_name} module."""', "", "import pytest"]
    lines.extend(_test_module_imports(module_name, functions, classes))
    lines.extend(["", ""])

    for function in functions:
        lines.extend(_pytest_function_test(function))

    for cls in classes:
        lines.extend(_pytest_class_test(cls))

    return "\n".join(lines)


def _pytest_function_test(function):
    """Return the pytest test class lines for one module-level function."""
    class_name = f"Test{function['name'].title().replace('_', '')}"
    call = _placeholder_call(function["name"], function["args"])
    return [
        f"class {class_name}:",
        f'    """Tests for {function["name"]} function."""',
        "",
        '    @pytest.mark.skip(reason="TODO: supply arguments and a real assertion")',
        f"    def test_{function['name']}_basic(self):",
        f'        """Test {function["name"]} with basic input."""',
        f"        result = {call}",
        "        assert result is not None",
        "",
        '    @pytest.mark.skip(reason="TODO: implement edge cases")',
        f"    def test_{function['name']}_edge_case(self):",
        f'        """Test {function["name"]} edge cases."""',
        "        pass",
        "",
        "",
    ]


def _pytest_class_test(cls):
    """Return the pytest test class lines for one collected class."""
    construction = _placeholder_call(cls["name"], _constructor_arguments(cls))
    lines = [
        f"class Test{cls['name']}:",
        f'    """Tests for {cls["name"]} class."""',
        "",
        "    @pytest.fixture",
        "    def instance(self):",
        f'        """Create a {cls["name"]} instance for testing."""',
        f"        return {construction}",
        "",
    ]

    for method in cls["methods"]:
        if method["name"] == "__init__":
            continue
        call = _placeholder_call(f"instance.{method['name']}", method["args"])
        lines.extend(
            [
                '    @pytest.mark.skip(reason="TODO: supply arguments and a real assertion")',
                f"    def test_{method['name']}(self, instance):",
                f'        """Test {cls["name"]}.{method["name"]} method."""',
                f"        result = {call}",
                "        assert result is not None",
                "",
            ]
        )

    lines.append("")
    return lines


def _generate_unittest_tests(module_name, functions, classes):
    """Generate unittest-style test stubs."""
    lines = [f'"""Tests for {module_name} module."""', "", "import unittest"]
    lines.extend(_test_module_imports(module_name, functions, classes))
    lines.extend(["", ""])

    for function in functions:
        lines.extend(_unittest_function_test(function))

    for cls in classes:
        lines.extend(_unittest_class_test(cls))

    lines.extend(["", 'if __name__ == "__main__":', "    unittest.main()", ""])
    return "\n".join(lines)


def _unittest_function_test(function):
    """Return the unittest TestCase lines for one module-level function."""
    class_name = f"Test{function['name'].title().replace('_', '')}"
    call = _placeholder_call(function["name"], function["args"])
    return [
        f"class {class_name}(unittest.TestCase):",
        f'    """Tests for {function["name"]} function."""',
        "",
        '    @unittest.skip("TODO: supply arguments and a real assertion")',
        f"    def test_{function['name']}_basic(self):",
        f'        """Test {function["name"]} with basic input."""',
        f"        result = {call}",
        "        self.assertIsNotNone(result)",
        "",
        "",
    ]


def _unittest_class_test(cls):
    """Return the unittest TestCase lines for one collected class."""
    construction = _placeholder_call(cls["name"], _constructor_arguments(cls))
    lines = [
        f"class Test{cls['name']}(unittest.TestCase):",
        f'    """Tests for {cls["name"]} class."""',
        "",
        "    def setUp(self):",
        f'        """Set up {cls["name"]} instance."""',
        f"        self.instance = {construction}",
        "",
    ]

    for method in cls["methods"]:
        if method["name"] == "__init__":
            continue
        call = _placeholder_call(f"self.instance.{method['name']}", method["args"])
        lines.extend(
            [
                '    @unittest.skip("TODO: supply arguments and a real assertion")',
                f"    def test_{method['name']}(self):",
                f'        """Test {cls["name"]}.{method["name"]} method."""',
                f"        result = {call}",
                "        self.assertIsNotNone(result)",
                "",
            ]
        )

    lines.append("")
    return lines


_BLOCK_STATEMENTS = tuple(
    node
    for node in (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.If,
        ast.With,
        ast.AsyncWith,
        ast.Try,
        getattr(ast, "Match", None),
        getattr(ast, "TryStar", None),
    )
    if node is not None
)

_UNMOVABLE_STATEMENTS = (
    ast.Return,
    ast.Raise,
    ast.Break,
    ast.Continue,
    ast.Global,
    ast.Nonlocal,
    ast.Import,
    ast.ImportFrom,
    ast.Pass,
)

_SUSPENDING_EXPRESSIONS = (ast.Await, ast.Yield, ast.YieldFrom)

_IMPURE_EXPRESSIONS = (ast.Call, ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)

_PRECEDENCE_SENSITIVE_EXPRESSIONS = (
    ast.BinOp,
    ast.BoolOp,
    ast.UnaryOp,
    ast.Compare,
    ast.IfExp,
    ast.Lambda,
    ast.Tuple,
    ast.Starred,
)


def _replace_byte_span(line, start_column, end_column, replacement):
    """Replace a column span in one source line.

    AST column offsets are UTF-8 byte offsets, so the splice runs on the
    encoded line and is decoded back afterwards.
    """
    encoded = line.encode("utf-8")
    spliced = encoded[:start_column] + replacement.encode("utf-8") + encoded[end_column:]
    return spliced.decode("utf-8")


def _find_extractable_statement(tree, target_line):
    """Return (node, error) for the simple statement starting on target_line."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt) or node.lineno != target_line:
            continue
        if isinstance(node, _BLOCK_STATEMENTS):
            return None, f"Line {target_line} opens a block; only a single simple statement can be extracted"
        if isinstance(node, _UNMOVABLE_STATEMENTS):
            return None, f"Line {target_line} cannot be moved into a separate function"
        if node.end_lineno != node.lineno:
            return None, f"The statement on line {target_line} spans several lines; only single-line statements can be extracted"
        if any(isinstance(child, _SUSPENDING_EXPRESSIONS) for child in ast.walk(node)):
            return None, f"Line {target_line} awaits or yields, so it cannot move into a plain function"
        return node, None

    return None, f"No statement starts on line {target_line}"


def _statement_name_usage(node):
    """Return (loaded, stored) sets of the plain names one statement uses."""
    loaded = set()
    stored = set()

    for child in ast.walk(node):
        if not isinstance(child, ast.Name):
            continue
        if isinstance(child.ctx, ast.Load):
            loaded.add(child.id)
        else:
            stored.add(child.id)

    # An augmented assignment reads its target before writing it.
    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        loaded.add(node.target.id)

    return loaded, stored


def _module_level_names(tree):
    """Return the names bound at module level, which a new function can still see."""
    names = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)

    return names


def _extract_statement_into_function(content, target_line, new_function_name):
    """Return (details, error) for extracting one statement into a new function.

    The extracted statement keeps working because every free name it reads
    becomes a parameter and every name it writes becomes a return value.
    """
    if not new_function_name.isidentifier() or keyword.iskeyword(new_function_name):
        return None, f"'{new_function_name}' is not a valid Python function name"

    try:
        tree = ast.parse(content)
    except SyntaxError as error:
        return None, f"File does not parse, so it cannot be refactored: {error}"

    node, error = _find_extractable_statement(tree, target_line)
    if error:
        return None, error

    lines = content.splitlines()
    statement_line = lines[target_line - 1]
    indent = statement_line[: len(statement_line) - len(statement_line.lstrip())]

    loaded, stored = _statement_name_usage(node)
    visible_without_arguments = _module_level_names(tree) | set(dir(builtins))
    parameters = sorted(loaded - visible_without_arguments)
    returns = sorted(stored)

    lines[target_line - 1] = indent + _extraction_call(new_function_name, parameters, returns)
    definition = _extraction_definition(new_function_name, parameters, returns, statement_line.strip())
    new_content = "\n".join(lines).rstrip("\n") + "\n\n\n" + definition

    try:
        ast.parse(new_content)
    except SyntaxError as error:
        return None, f"Extraction would produce invalid code, so nothing was written: {error}"

    return {
        "content": new_content,
        "parameters": parameters,
        "returns": returns,
    }, None


def _extraction_call(function_name, parameters, returns):
    """Return the call that replaces the extracted statement."""
    call = f"{function_name}({', '.join(parameters)})"
    if returns:
        return f"{', '.join(returns)} = {call}"
    return call


def _extraction_definition(function_name, parameters, returns, statement_source):
    """Return the source of the newly extracted function."""
    lines = [f"def {function_name}({', '.join(parameters)}):", f"    {statement_source}"]
    if returns:
        lines.append(f"    return {', '.join(returns)}")
    return "\n".join(lines) + "\n"


def _count_name_bindings(tree, variable_name):
    """Return how many times variable_name is bound anywhere in the tree."""
    count = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == variable_name:
            count += 0 if isinstance(node.ctx, ast.Load) else 1
        elif isinstance(node, ast.arg) and node.arg == variable_name:
            count += 1
        elif isinstance(node, (ast.Global, ast.Nonlocal)) and variable_name in node.names:
            count += 1
        elif isinstance(node, ast.ExceptHandler) and node.name == variable_name:
            count += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            count += sum(
                1
                for alias in node.names
                if (alias.asname or alias.name.split(".")[0]) == variable_name
            )

    return count


def _find_sole_assignment(tree, variable_name, lines):
    """Return (node, error) for the one simple assignment of variable_name."""
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == variable_name
    ]

    if not matches:
        return None, f"No simple assignment to '{variable_name}' was found"

    if len(matches) > 1 or _count_name_bindings(tree, variable_name) > 1:
        return None, (
            f"'{variable_name}' is bound in more than one place; "
            "inline_variable only handles a variable assigned exactly once"
        )

    node = matches[0]
    if node.lineno != node.end_lineno:
        return None, f"The assignment to '{variable_name}' spans several lines and cannot be inlined"

    line = lines[node.lineno - 1]
    if node.col_offset != len(line) - len(line.lstrip()):
        return None, f"The assignment to '{variable_name}' does not stand on its own line"

    return node, None


def _inline_value_source(content, value_node):
    """Return (source, error) for the expression being inlined."""
    if any(isinstance(child, _IMPURE_EXPRESSIONS) for child in ast.walk(value_node)):
        return None, (
            "The assigned expression runs code (a call, await, or walrus). "
            "Inlining it would run that code at every use site, so it is refused."
        )

    source = ast.get_source_segment(content, value_node)
    if source is None:
        return None, "The assigned expression could not be read back from the file"

    if isinstance(value_node, _PRECEDENCE_SENSITIVE_EXPRESSIONS):
        return f"({source})", None

    return source, None


def _inline_variable_uses(content, variable_name):
    """Return (details, error) for replacing every use of variable_name with its value.

    Only real name references are rewritten, because they come from the parse
    tree; occurrences inside strings and comments are left alone.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as error:
        return None, f"File does not parse, so it cannot be refactored: {error}"

    lines = content.splitlines()
    node, error = _find_sole_assignment(tree, variable_name, lines)
    if error:
        return None, error

    value_source, error = _inline_value_source(content, node.value)
    if error:
        return None, error

    references = [
        child
        for child in ast.walk(tree)
        if isinstance(child, ast.Name)
        and child.id == variable_name
        and isinstance(child.ctx, ast.Load)
    ]

    for reference in sorted(references, key=lambda item: (item.lineno, item.col_offset), reverse=True):
        index = reference.lineno - 1
        lines[index] = _replace_byte_span(
            lines[index], reference.col_offset, reference.end_col_offset, value_source
        )

    del lines[node.lineno - 1]
    new_content = "\n".join(lines) + "\n"

    try:
        ast.parse(new_content)
    except SyntaxError as error:
        return None, f"Inlining would produce invalid code, so nothing was written: {error}"

    return {
        "content": new_content,
        "value": value_source,
        "replacements": len(references),
    }, None


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

    handlers = {
        "rename": _rename_in_file,
        "extract_function": _extract_function_in_file,
        "inline_variable": _inline_variable_in_file,
    }
    handler = handlers.get(action)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown action: {action}. Valid: rename, extract_function, inline_variable",
        }

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        return {"success": False, "error": str(error)}

    return handler(
        path,
        content,
        old_name=old_name,
        new_name=new_name,
        target_line=target_line,
        new_function_name=new_function_name,
    )


def _rename_in_file(path, content, *, old_name, new_name, **_unused):
    """Rename every whole-word occurrence of old_name in the file."""
    if not old_name or not new_name:
        return {"success": False, "error": "Both old_name and new_name required for rename"}

    pattern = rf"\b{re.escape(old_name)}\b"
    count = len(re.findall(pattern, content))
    if count == 0:
        return {"success": False, "error": f"'{old_name}' not found in file"}

    try:
        path.write_text(re.sub(pattern, new_name, content), encoding="utf-8")
    except OSError as error:
        return {"success": False, "error": str(error)}

    return {
        "success": True,
        "action": "rename",
        "file": str(path),
        "old_name": old_name,
        "new_name": new_name,
        "replacements": count,
    }


def _extract_function_in_file(path, content, *, target_line, new_function_name, **_unused):
    """Move one statement into a new function that takes and returns what it uses."""
    if not target_line or not new_function_name:
        return {
            "success": False,
            "error": "target_line and new_function_name required for extract_function",
        }

    if not str(path).endswith(".py"):
        return {"success": False, "error": "extract_function only supports Python files"}

    if target_line < 1 or target_line > len(content.splitlines()):
        return {"success": False, "error": f"Invalid line number: {target_line}"}

    details, error = _extract_statement_into_function(content, target_line, new_function_name)
    if error:
        return {"success": False, "error": error}

    try:
        path.write_text(details["content"], encoding="utf-8")
    except OSError as error:
        return {"success": False, "error": str(error)}

    return {
        "success": True,
        "action": "extract_function",
        "file": str(path),
        "extracted_line": target_line,
        "new_function": new_function_name,
        "parameters": details["parameters"],
        "returns": details["returns"],
    }


def _inline_variable_in_file(path, content, *, old_name, **_unused):
    """Replace every reference to a single-assignment variable with its value."""
    if not old_name:
        return {"success": False, "error": "old_name (variable name) required for inline_variable"}

    if not str(path).endswith(".py"):
        return {"success": False, "error": "inline_variable only supports Python files"}

    details, error = _inline_variable_uses(content, old_name)
    if error:
        return {"success": False, "error": error}

    try:
        path.write_text(details["content"], encoding="utf-8")
    except OSError as error:
        return {"success": False, "error": str(error)}

    return {
        "success": True,
        "action": "inline_variable",
        "file": str(path),
        "variable": old_name,
        "value": details["value"],
        "replacements": details["replacements"],
    }


DEPLOY_CLI_VERSION_CHECKS = {
    "vercel": ["vercel", "--version"],
    "netlify": ["netlify", "--version"],
    "heroku": ["heroku", "--version"],
    "railway": ["railway", "--version"],
    "flyio": ["fly", "version"],
}


def _custom_deploy_arguments(command):
    """Return (argv, error) for a caller-supplied deploy command.

    The parsed argv is what actually runs, so shell metacharacters in the
    command become literal arguments instead of extra commands.
    """
    try:
        arguments = shlex.split(command)
    except ValueError:
        return None, "Invalid deploy command format"

    if not arguments:
        return None, "Deploy command is empty"

    if is_catastrophic_command(format_process_command(arguments)):
        return None, "BLOCKED: Deploy command is a catastrophic operation"

    return arguments, None


def _platform_deploy_arguments(platform, cwd):
    """Return (argv, error) for a known deployment platform."""
    if platform == "vercel":
        return (["vercel", "--prod"] if (cwd / ".vercel").exists() else ["vercel"]), None
    if platform == "netlify":
        return ["netlify", "deploy", "--prod"], None
    if platform == "heroku":
        return ["git", "push", "heroku", "main"], None
    if platform == "railway":
        return ["railway", "up"], None
    if platform == "flyio":
        return ["fly", "deploy"], None
    return None, (
        "No platform detected and none specified. "
        "Use platform='vercel' or similar, or provide a custom command"
    )


def _deploy_arguments(platform, command, cwd):
    """Return (argv, error) for the deployment that should run."""
    if command:
        return _custom_deploy_arguments(command)
    return _platform_deploy_arguments(platform, cwd)


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
    deploy_arguments, error = _deploy_arguments(platform, command, cwd)
    if error:
        return {"success": False, "error": error}

    if platform in DEPLOY_CLI_VERSION_CHECKS:
        check = run_process(DEPLOY_CLI_VERSION_CHECKS[platform], timeout=10)
        if not check["success"]:
            return {
                "success": False,
                "error": f"{platform} CLI not installed. Install with: npm i -g {platform}"
                if platform != "flyio"
                else f"{platform} CLI not installed. See https://fly.io/docs/getting-started/installing-flyctl/",
                "platform": platform,
            }

    # Run the deploy command without a shell so arguments stay literal.
    deploy_result = run_process(deploy_arguments, timeout=600)

    result["deploy_command"] = format_process_command(deploy_arguments)
    result["output"] = deploy_result.get("stdout", "")
    result["error"] = deploy_result.get("stderr", "")
    result["success"] = deploy_result["success"]

    return result
