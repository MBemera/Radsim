"""Code Quality Checker - Enforce RadSim Rules.

Analyzes generated code for violations of the 6 RadSim rules:
1. Extreme Clarity Over Cleverness
2. Self-Documenting Names
3. One Function, One Purpose
4. Flat Over Nested
5. Explicit Over Implicit
6. Standard Patterns Only
"""

import re


def check_code_quality(content, file_extension):
    """Check code content for RadSim rule violations.

    Args:
        content: The source code string to check
        file_extension: File extension (e.g., ".py", ".js")

    Returns:
        dict with 'violations' list and 'passed' bool
    """
    violations = []

    if file_extension not in {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java"}:
        return {"passed": True, "violations": []}

    violations.extend(check_function_length(content, file_extension))
    violations.extend(check_nesting_depth(content))
    violations.extend(check_variable_names(content, file_extension))
    violations.extend(check_function_names(content, file_extension))

    return {
        "passed": len(violations) == 0,
        "violations": violations,
    }


def check_function_length(content, file_extension):
    """Rule 3: Functions should be max 20-30 lines."""
    violations = []
    max_lines = 30

    if file_extension == ".py":
        pattern = r"^(    |\t)*def\s+(\w+)"
    elif file_extension in {".js", ".ts", ".jsx", ".tsx"}:
        pattern = r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=)"
    elif file_extension == ".go":
        pattern = r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)"
    else:
        return []

    lines = content.split("\n")
    current_function = None
    function_start = 0

    for line_number, line in enumerate(lines):
        match = re.match(pattern, line)
        if match:
            # Check previous function
            if current_function:
                length = line_number - function_start
                if length > max_lines:
                    violations.append(
                        f"Rule 3: Function '{current_function}' is {length} lines "
                        f"(max {max_lines}). Break it into smaller functions."
                    )

            # Track groups for different patterns
            groups = [g for g in match.groups() if g]
            current_function = groups[0] if groups else None
            function_start = line_number

    # Check last function
    if current_function:
        length = len(lines) - function_start
        if length > max_lines:
            violations.append(
                f"Rule 3: Function '{current_function}' is {length} lines "
                f"(max {max_lines}). Break it into smaller functions."
            )

    return violations


def check_nesting_depth(content):
    """Rule 4: Max 2-3 levels of nesting."""
    violations = []
    max_depth = 3
    deepest_depth = 0
    deepest_line = 0

    lines = content.split("\n")
    for line_number, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue

        indent = len(line) - len(stripped)
        # Approximate depth: 4 spaces or 1 tab per level
        depth = indent // 4 if "    " in line[:indent] else indent

        if depth > deepest_depth:
            deepest_depth = depth
            deepest_line = line_number

    if deepest_depth > max_depth:
        violations.append(
            f"Rule 4: Nesting depth of {deepest_depth} on line {deepest_line} "
            f"(max {max_depth}). Use early returns or extract functions."
        )

    return violations


def check_variable_names(content, file_extension):
    """Rule 2: No single-letter variable names (except i, j, k in loops)."""
    violations = []
    loop_vars = {"i", "j", "k", "x", "y", "e", "_"}

    if file_extension == ".py":
        # Find assignments like: a = something
        pattern = r"^\s*([a-zA-Z_]\w*)\s*="
        for line in content.split("\n"):
            match = re.match(pattern, line)
            if match:
                var_name = match.group(1)
                if len(var_name) == 1 and var_name not in loop_vars:
                    violations.append(
                        f"Rule 2: Single-letter variable '{var_name}' found. "
                        f"Use a descriptive name."
                    )

    elif file_extension in {".js", ".ts", ".jsx", ".tsx"}:
        pattern = r"(?:const|let|var)\s+([a-zA-Z_]\w*)\s*="
        for line in content.split("\n"):
            match = re.search(pattern, line)
            if match:
                var_name = match.group(1)
                if len(var_name) == 1 and var_name not in loop_vars:
                    violations.append(
                        f"Rule 2: Single-letter variable '{var_name}' found. "
                        f"Use a descriptive name."
                    )

    # Only report first 3 to avoid noise
    return violations[:3]


def check_function_names(content, file_extension):
    """Rule 3: Function names with 'and' suggest doing too much."""
    violations = []

    if file_extension == ".py":
        pattern = r"def\s+(\w+)"
    elif file_extension in {".js", ".ts", ".jsx", ".tsx"}:
        pattern = r"function\s+(\w+)"
    elif file_extension == ".go":
        pattern = r"func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)"
    else:
        return []

    for match in re.finditer(pattern, content):
        func_name = match.group(1)
        # Check for "and" in snake_case or camelCase
        if "_and_" in func_name or "And" in func_name:
            violations.append(
                f"Rule 3: Function '{func_name}' contains 'and', "
                f"suggesting it does multiple things. Split into separate functions."
            )

    return violations[:3]


def format_quality_warnings(violations):
    """Format violations into a readable warning string.

    Args:
        violations: List of violation strings

    Returns:
        Formatted warning string or empty string if no violations
    """
    if not violations:
        return ""

    header = f"RadSim Quality Check: {len(violations)} issue(s) found"
    items = "\n".join(f"  - {v}" for v in violations)
    return f"{header}\n{items}"
