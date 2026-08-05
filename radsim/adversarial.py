"""Adversarial Code Review Engine.

Static analysis "attacker" that probes code for weaknesses.
Does NOT execute code — purely reads and analyzes patterns.
All findings are presented as a report; no files are modified.
"""

import ast
import os
import re
from pathlib import Path

# Extensions we analyze
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java"}

# Every detector caps its output so one noisy file cannot flood a report.
MAX_ISSUES_PER_DETECTOR = 5

_TRY_STATEMENTS = tuple(
    node for node in (ast.Try, getattr(ast, "TryStar", None)) if node is not None
)


# ---------------------------------------------------------------------------
# Issue dataclass-like dict builder
# ---------------------------------------------------------------------------

def _issue(category, severity, function_name, line_number, message, suggestion):
    """Create a standardized issue dict.

    Args:
        category: Issue category (e.g., 'input_validation', 'error_handling')
        severity: 'high', 'medium', or 'low'
        function_name: Name of the function containing the issue
        line_number: Line number where the issue was found
        message: Description of the issue
        suggestion: Suggested fix

    Returns:
        Standardized issue dict
    """
    return {
        "category": category,
        "severity": severity,
        "function": function_name,
        "line": line_number,
        "message": message,
        "suggestion": suggestion,
    }


# ---------------------------------------------------------------------------
# Detectors (Python-focused with JS/TS support)
# ---------------------------------------------------------------------------

def _detect_missing_input_validation(content, extension):
    """Find functions that accept arguments but have no guard clauses."""
    issues = []

    if extension == ".py":
        # Find functions with parameters
        func_pattern = re.compile(r"^([ \t]*)def\s+(\w+)\s*\(([^)]*)\)\s*:", re.MULTILINE)

        for match in func_pattern.finditer(content):
            func_name = match.group(2)
            params_raw = match.group(3)
            line_number = content[:match.start()].count("\n") + 1

            # Skip dunder methods and self-only methods
            if func_name.startswith("__") and func_name.endswith("__"):
                continue

            # Parse params, skip self/cls
            params = [p.strip().split(":")[0].split("=")[0].strip()
                      for p in params_raw.split(",") if p.strip()]
            params = [p for p in params if p not in ("self", "cls", "*args", "**kwargs", "")]

            if not params:
                continue

            # Look at the function body (next 15 lines after def)
            func_start = match.end()
            body_lines = content[func_start:].split("\n")[:15]
            body_text = "\n".join(body_lines)

            # Check for any validation patterns
            has_validation = any(pattern in body_text for pattern in [
                "if not ", "if ", "raise ", "assert ", "isinstance(",
                "is None", "is not None", "len(", "ValueError", "TypeError",
            ])

            if not has_validation:
                issues.append(_issue(
                    "input_validation", "medium", func_name, line_number,
                    f"Function '{func_name}' accepts {len(params)} parameter(s) "
                    f"but has no input validation",
                    f"Add guard clauses: if not {params[0]}: raise ValueError(...)"
                ))

    elif extension in {".js", ".ts", ".jsx", ".tsx"}:
        func_pattern = re.compile(
            r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>)"
        )
        for match in func_pattern.finditer(content):
            func_name = match.group(1) or match.group(2)
            line_number = content[:match.start()].count("\n") + 1

            func_start = match.end()
            body_lines = content[func_start:].split("\n")[:15]
            body_text = "\n".join(body_lines)

            has_validation = any(pattern in body_text for pattern in [
                "if (!", "if (", "throw ", "typeof ", "instanceof ",
                "=== null", "=== undefined", ".length",
            ])

            if not has_validation:
                issues.append(_issue(
                    "input_validation", "medium", func_name, line_number,
                    f"Function '{func_name}' has no input validation",
                    "Add parameter checks at function start"
                ))

    return issues


def _detect_bare_except(content, extension):
    """Find bare except clauses that swallow all exceptions."""
    issues = []

    if extension == ".py":
        for line_number, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            if stripped == "except:" or stripped == "except Exception:":
                # Find the containing function
                func_name = _find_containing_function(content, line_number, extension)
                issues.append(_issue(
                    "error_handling", "high", func_name, line_number,
                    "Bare except clause catches all exceptions including KeyboardInterrupt",
                    "Use specific exception types: except (ValueError, TypeError) as e:"
                ))

    elif extension in {".js", ".ts", ".jsx", ".tsx"}:
        for line_number, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            if "catch" in stripped and re.search(r"catch\s*\(\s*\w*\s*\)", stripped):
                # Check if the catch body uses the error variable
                func_name = _find_containing_function(content, line_number, extension)
                # Only flag if the error variable is never used (empty catch)
                next_lines = content.split("\n")[line_number:line_number + 3]
                body = "\n".join(next_lines).strip()
                if body.startswith("}") or not body:
                    issues.append(_issue(
                        "error_handling", "high", func_name, line_number,
                        "Empty catch block silently swallows errors",
                        "Log the error or handle it explicitly"
                    ))

    return issues


def _dotted_call_name(node):
    """Return the dotted name of a call target, e.g. 'requests.get' or 'read'."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _io_call_description(node):
    """Return a label when the node performs I/O, else None."""
    if not isinstance(node, ast.Call):
        return None

    dotted = _dotted_call_name(node.func)
    if not dotted:
        return None

    root = dotted.split(".")[0]
    leaf = dotted.split(".")[-1]

    if dotted == "open":
        return "File open"
    if dotted in {"json.load", "json.dump"}:
        return "JSON file access"
    if root in {"requests", "urllib", "httpx"}:
        return "HTTP request"
    if root == "subprocess":
        return "Subprocess call"
    if leaf in {"read", "readlines"} and dotted != "read":
        return "File read"
    if leaf in {"write", "writelines"} and dotted != "write":
        return "File write"
    return None


def _function_name_by_line(tree):
    """Map each line number to the innermost function that contains it."""
    names = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            names[line] = node.name
    return names


def _collect_unguarded_io(node, protected, found):
    """Record I/O calls that no enclosing try block covers.

    Walking the parse tree means occurrences inside strings and comments are
    never seen, and try coverage is exact rather than guessed from indentation.
    """
    if isinstance(node, _TRY_STATEMENTS):
        for statement in node.body:
            _collect_unguarded_io(statement, True, found)
        for statement in list(node.handlers) + list(node.orelse) + list(node.finalbody):
            _collect_unguarded_io(statement, protected, found)
        return

    description = _io_call_description(node)
    if description and not protected:
        found.append((node.lineno, description))

    for child in ast.iter_child_nodes(node):
        _collect_unguarded_io(child, protected, found)


def _detect_unguarded_io(content, extension):
    """Find I/O operations that no enclosing try block covers."""
    if extension != ".py":
        return []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    found = []
    _collect_unguarded_io(tree, False, found)
    function_names = _function_name_by_line(tree)

    issues = [
        _issue(
            "io_safety",
            "medium",
            function_names.get(line_number, "<module>"),
            line_number,
            f"{description} is not wrapped in try/except here",
            "Wrap it in try/except, or confirm the caller handles OSError",
        )
        for line_number, description in found
    ]
    return issues[:MAX_ISSUES_PER_DETECTOR]


def _string_valued_names(tree):
    """Return names that are demonstrably strings in this file."""
    names = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.update(
                argument.arg
                for argument in node.args.args
                if isinstance(argument.annotation, ast.Name) and argument.annotation.id == "str"
            )
        elif isinstance(node, ast.Assign):
            if _is_string_expression(node.value):
                names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.annotation, ast.Name) and node.annotation.id == "str":
                names.add(node.target.id)

    return names


def _is_string_expression(node):
    """Return True when an expression obviously produces a string."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.Call):
        return _dotted_call_name(node.func).split(".")[-1] in {"str", "format", "join", "strip"}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_string_expression(node.left) or _is_string_expression(node.right)
    return False


def _concatenated_unknown_name(node, known_strings):
    """Return the name added to a string literal when its type is unknown."""
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
        return None

    for side, other in ((node.left, node.right), (node.right, node.left)):
        if not isinstance(other, ast.Constant) or not isinstance(other.value, str):
            continue
        if isinstance(side, ast.Name) and side.id not in known_strings:
            return side.id

    return None


def _detect_type_confusion(content, extension):
    """Find string concatenation with a name that is not known to be a string."""
    if extension != ".py":
        return []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    known_strings = _string_valued_names(tree)
    function_names = _function_name_by_line(tree)
    issues = []

    for node in ast.walk(tree):
        name = _concatenated_unknown_name(node, known_strings)
        if not name:
            continue
        issues.append(
            _issue(
                "type_safety",
                "low",
                function_names.get(node.lineno, "<module>"),
                node.lineno,
                f"Concatenating '{name}' with a string fails if it is not a string",
                f'Use an f-string or str(): f"{{{name}}}text"',
            )
        )

    return issues[:MAX_ISSUES_PER_DETECTOR]


def _detect_boundary_issues(content, extension):
    """Find potential off-by-one and boundary condition issues."""
    issues = []

    if extension == ".py":
        for line_number, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Range with len() minus 1 — common off-by-one source
            if re.search(r"range\(.*len\(\w+\)\s*-\s*1", stripped):
                func_name = _find_containing_function(content, line_number, extension)
                issues.append(_issue(
                    "boundary", "low", func_name, line_number,
                    "range(len(x) - 1) may cause off-by-one — verify boundary is correct",
                    "Consider using enumerate() or slice notation instead"
                ))

            # Array index with -1 without length check
            if re.search(r"\w+\[-1\]", stripped):
                # Check if there's a length check nearby
                nearby = content.split("\n")[max(0, line_number - 4):line_number]
                has_check = any("len(" in prev or "if " in prev for prev in nearby)
                if not has_check:
                    func_name = _find_containing_function(content, line_number, extension)
                    issues.append(_issue(
                        "boundary", "low", func_name, line_number,
                        "Negative index [-1] without preceding length check",
                        "Add: if collection: ... before accessing [-1]"
                    ))

    return issues[:5]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_containing_function(content, target_line, extension):
    """Find which function contains a given line number."""
    if extension == ".py":
        pattern = r"^[ \t]*def\s+(\w+)"
    elif extension in {".js", ".ts", ".jsx", ".tsx"}:
        pattern = r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=)"
    else:
        return "<module>"

    last_func = "<module>"
    for line_number, line in enumerate(content.split("\n"), 1):
        match = re.match(pattern, line)
        if match:
            groups = [g for g in match.groups() if g]
            if groups:
                last_func = groups[0]
        if line_number >= target_line:
            break

    return last_func


def _is_in_try_block(lines, target_index):
    """Check if a line is inside a try block by looking at preceding indentation."""
    if target_index < 0 or target_index >= len(lines):
        return False

    target_indent = len(lines[target_index]) - len(lines[target_index].lstrip())

    # Walk backwards looking for 'try:' at a lower or equal indent level
    for i in range(target_index - 1, max(0, target_index - 20), -1):
        line = lines[i].strip()
        line_indent = len(lines[i]) - len(lines[i].lstrip())

        if line == "try:" and line_indent <= target_indent:
            return True
        # If we hit a function def, stop searching
        if line.startswith("def ") and line_indent < target_indent:
            break

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def stress_test_file(file_path):
    """Run adversarial analysis on a single file.

    Args:
        file_path: Path to the source file

    Returns:
        dict with file info, function results, and issues list.
        Returns None if not a supported file.
    """
    path = Path(file_path)
    extension = path.suffix.lower()

    if extension not in CODE_EXTENSIONS:
        return None

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # Run all detectors
    all_issues = []
    all_issues.extend(_detect_missing_input_validation(content, extension))
    all_issues.extend(_detect_bare_except(content, extension))
    all_issues.extend(_detect_unguarded_io(content, extension))
    all_issues.extend(_detect_type_confusion(content, extension))
    all_issues.extend(_detect_boundary_issues(content, extension))

    # Group issues by function
    functions_tested = set()
    functions_with_issues = set()
    for issue in all_issues:
        functions_tested.add(issue["function"])
        functions_with_issues.add(issue["function"])

    # Also count functions without issues
    if extension == ".py":
        for match in re.finditer(r"^[ \t]*def\s+(\w+)", content, re.MULTILINE):
            functions_tested.add(match.group(1))
    elif extension in {".js", ".ts", ".jsx", ".tsx"}:
        for match in re.finditer(r"function\s+(\w+)", content):
            functions_tested.add(match.group(1))

    passed = functions_tested - functions_with_issues

    return {
        "file": str(path),
        "basename": path.name,
        "extension": extension,
        "functions_tested": len(functions_tested),
        "passed": len(passed),
        "failed": len(functions_with_issues),
        "issues": all_issues,
        "passed_functions": sorted(passed),
        "failed_functions": sorted(functions_with_issues),
    }


def stress_test_directory(directory, extensions=None):
    """Run adversarial analysis on all files in a directory.

    Args:
        directory: Root directory to scan
        extensions: Optional set of extensions to filter

    Returns:
        dict with aggregate results and per-file details
    """
    target_extensions = extensions or CODE_EXTENSIONS
    directory = Path(directory)
    results = []

    skip_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
        ".egg-info", "eggs", ".eggs",
    }

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip_dirs
                   and not d.endswith(".egg-info")]

        for filename in files:
            filepath = Path(root) / filename
            if filepath.suffix.lower() in target_extensions:
                result = stress_test_file(filepath)
                if result and result["issues"]:
                    results.append(result)

    # Sort by issue count descending
    results.sort(key=lambda r: len(r["issues"]), reverse=True)

    total_issues = sum(len(r["issues"]) for r in results)
    total_functions = sum(r["functions_tested"] for r in results)
    total_passed = sum(r["passed"] for r in results)

    # Count by severity
    severity_counts = {"high": 0, "medium": 0, "low": 0}
    for result in results:
        for issue in result["issues"]:
            severity_counts[issue["severity"]] = severity_counts.get(issue["severity"], 0) + 1

    return {
        "total_issues": total_issues,
        "total_functions": total_functions,
        "total_passed": total_passed,
        "files_with_issues": len(results),
        "severity": severity_counts,
        "files": results,
        "directory": str(directory),
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_stress_report(results):
    """Format adversarial review results for terminal display.

    Args:
        results: Result from stress_test_directory() or stress_test_file()

    Returns:
        List of lines to print
    """
    lines = []

    # Detect if this is a single file result or directory result
    if "files" not in results:
        # Single file
        return _format_single_file_report(results)

    lines.append("")
    lines.append("  ═══ ADVERSARIAL CODE REVIEW ═══")
    lines.append("")

    total = results["total_issues"]
    funcs = results["total_functions"]
    passed = results["total_passed"]
    sev = results["severity"]

    lines.append(f"  Functions tested: {funcs}")
    lines.append(f"  Passed:           {passed} ok")
    if total > 0:
        lines.append(f"  Issues found:     {total}")
        lines.append(f"    High:   {sev.get('high', 0)}")
        lines.append(f"    Medium: {sev.get('medium', 0)}")
        lines.append(f"    Low:    {sev.get('low', 0)}")
    else:
        lines.append("  Issues found:     0 — all clear")
    lines.append("")

    # Per-file details (top 10)
    for file_result in results["files"][:10]:
        fname = file_result["basename"]
        issue_count = len(file_result["issues"])
        lines.append(f"  File: {fname} — {issue_count} issue(s)")

        for issue in file_result["issues"][:5]:
            sev_icon = f"[{issue['severity'].upper()}]"
            lines.append(f"    {sev_icon} L{issue['line']:>4} {issue['function']}(): {issue['message']}")

        remaining = len(file_result["issues"]) - 5
        if remaining > 0:
            lines.append(f"    ... and {remaining} more")
        lines.append("")

    remaining_files = len(results["files"]) - 10
    if remaining_files > 0:
        lines.append(f"  ... and {remaining_files} more file(s)")
        lines.append("")

    lines.append("  Scan single file: /stress <filepath>")
    lines.append("")
    return lines


def _format_single_file_report(result):
    """Format a single file's adversarial review."""
    lines = []
    lines.append("")
    lines.append(f"  ═══ STRESS TEST: {result['basename']} ═══")
    lines.append("")

    tested = result["functions_tested"]

    lines.append(f"  Functions tested: {tested}")
    lines.append("")

    # Show passed functions
    for func in result.get("passed_functions", []):
        lines.append(f"    ok {func}()")

    # Show failed functions with details
    for func in result.get("failed_functions", []):
        func_issues = [i for i in result["issues"] if i["function"] == func]
        lines.append(f"    warning:  {func}() — {len(func_issues)} issue(s)")

        for issue in func_issues:
            sev_icon = f"[{issue['severity'].upper()}]"
            lines.append(f"       {sev_icon} L{issue['line']}: {issue['message']}")
            lines.append(f"          → {issue['suggestion']}")

    lines.append("")

    if not result["issues"]:
        lines.append("  All clear. No issues found.")
        lines.append("")

    return lines
