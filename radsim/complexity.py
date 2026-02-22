"""Complexity Budget Engine.

Scores codebase complexity and enforces a simplicity budget.
Always read-only — never modifies files without explicit user confirmation.

Scoring factors per file:
  - Cyclomatic complexity (branches, loops)
  - Maximum nesting depth
  - Function length penalty (functions > 30 lines)
  - Single-letter variable penalty
"""

import json
import os
import re
from pathlib import Path

# Extensions we analyze
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java"}

# Budget storage location
BUDGET_FILE = Path.home() / ".radsim" / "complexity_budget.json"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _count_branches(content, extension):
    """Count branching statements (cyclomatic complexity proxy)."""
    if extension == ".py":
        keywords = [r"\bif\b", r"\belif\b", r"\bfor\b", r"\bwhile\b",
                    r"\bexcept\b", r"\band\b", r"\bor\b"]
    elif extension in {".js", ".ts", ".jsx", ".tsx"}:
        keywords = [r"\bif\b", r"\belse\s+if\b", r"\bfor\b", r"\bwhile\b",
                    r"\bcatch\b", r"\bcase\b", r"\b&&\b", r"\b\|\|\b"]
    elif extension == ".go":
        keywords = [r"\bif\b", r"\bfor\b", r"\bcase\b", r"\bselect\b"]
    else:
        keywords = [r"\bif\b", r"\bfor\b", r"\bwhile\b"]

    total = 0
    for pattern in keywords:
        total += len(re.findall(pattern, content))
    return total


def _max_nesting_depth(content):
    """Measure deepest indentation level (approximation via 4-space indent)."""
    max_depth = 0
    for line in content.split("\n"):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        indent = len(line) - len(stripped)
        depth = indent // 4
        if depth > max_depth:
            max_depth = depth
    return max_depth


def _count_long_functions(content, extension):
    """Count functions longer than 30 lines."""
    if extension == ".py":
        pattern = r"^[ \t]*def\s+(\w+)"
    elif extension in {".js", ".ts", ".jsx", ".tsx"}:
        pattern = r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=)"
    elif extension == ".go":
        pattern = r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)"
    else:
        return 0, []

    lines = content.split("\n")
    long_functions = []
    current_function = None
    function_start = 0
    max_length = 30

    for line_number, line in enumerate(lines):
        match = re.match(pattern, line)
        if match:
            if current_function:
                length = line_number - function_start
                if length > max_length:
                    long_functions.append({"name": current_function, "lines": length})

            groups = [g for g in match.groups() if g]
            current_function = groups[0] if groups else None
            function_start = line_number

    # Check last function
    if current_function:
        length = len(lines) - function_start
        if length > max_length:
            long_functions.append({"name": current_function, "lines": length})

    return len(long_functions), long_functions


def _count_single_letter_vars(content, extension):
    """Count single-letter variable names (excluding loop vars i, j, k, x, y, e, _)."""
    allowed = {"i", "j", "k", "x", "y", "e", "_"}
    count = 0

    if extension == ".py":
        for line in content.split("\n"):
            match = re.match(r"^\s*([a-zA-Z_]\w*)\s*=", line)
            if match:
                var_name = match.group(1)
                if len(var_name) == 1 and var_name not in allowed:
                    count += 1
    elif extension in {".js", ".ts", ".jsx", ".tsx"}:
        for line in content.split("\n"):
            match = re.search(r"(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=", line)
            if match:
                var_name = match.group(1)
                if len(var_name) == 1 and var_name not in allowed:
                    count += 1

    return count


# ---------------------------------------------------------------------------
# File scoring
# ---------------------------------------------------------------------------

def calculate_file_complexity(file_path):
    """Score a single file's complexity.

    Args:
        file_path: Path to the source file

    Returns:
        dict with score, breakdown, and details. Returns None if not a supported file.
    """
    path = Path(file_path)
    extension = path.suffix.lower()

    if extension not in CODE_EXTENSIONS:
        return None

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    lines_of_code = len([line for line in content.split("\n")
                         if line.strip() and not line.strip().startswith("#")
                         and not line.strip().startswith("//")])

    branches = _count_branches(content, extension)
    max_depth = _max_nesting_depth(content)
    long_count, long_functions = _count_long_functions(content, extension)
    bad_vars = _count_single_letter_vars(content, extension)

    # Scoring formula:
    #   base = branches (1 point each)
    #   + nesting penalty (depth > 3 adds depth * 2)
    #   + long function penalty (3 points each)
    #   + bad variable penalty (1 point each)
    nesting_penalty = max(0, max_depth - 3) * 2
    long_penalty = long_count * 3
    score = branches + nesting_penalty + long_penalty + bad_vars

    return {
        "file": str(path),
        "basename": path.name,
        "extension": extension,
        "lines_of_code": lines_of_code,
        "score": score,
        "breakdown": {
            "branches": branches,
            "nesting_penalty": nesting_penalty,
            "max_nesting_depth": max_depth,
            "long_functions": long_penalty,
            "bad_variables": bad_vars,
        },
        "long_functions": long_functions,
    }


# ---------------------------------------------------------------------------
# Project scanning
# ---------------------------------------------------------------------------

def scan_project_complexity(directory, extensions=None):
    """Walk a directory and score all supported files.

    Args:
        directory: Root directory to scan
        extensions: Optional set of extensions to include (default: CODE_EXTENSIONS)

    Returns:
        dict with total_score, file_count, files sorted by score descending, and hotspots
    """
    target_extensions = extensions or CODE_EXTENSIONS
    directory = Path(directory)
    results = []

    # Walk the tree, skipping common junk directories
    skip_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
        ".egg-info", "eggs", ".eggs",
    }

    for root, dirs, files in os.walk(directory):
        # Filter out skip directories in-place
        dirs[:] = [d for d in dirs if d not in skip_dirs
                   and not d.endswith(".egg-info")]

        for filename in files:
            filepath = Path(root) / filename
            if filepath.suffix.lower() in target_extensions:
                result = calculate_file_complexity(filepath)
                if result:
                    results.append(result)

    # Sort by score descending
    results.sort(key=lambda r: r["score"], reverse=True)

    total_score = sum(r["score"] for r in results)

    # Top 5 hotspots
    hotspots = results[:5] if results else []

    return {
        "total_score": total_score,
        "file_count": len(results),
        "files": results,
        "hotspots": hotspots,
        "directory": str(directory),
    }


# ---------------------------------------------------------------------------
# Budget management
# ---------------------------------------------------------------------------

def load_budget():
    """Load the complexity budget from disk.

    Returns:
        int or None: The budget value, or None if not set
    """
    if BUDGET_FILE.exists():
        try:
            data = json.loads(BUDGET_FILE.read_text())
            return data.get("budget")
        except (OSError, json.JSONDecodeError):
            pass
    return None


def save_budget(budget_value):
    """Save a complexity budget to disk.

    Args:
        budget_value: Integer budget to save, or None to clear
    """
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"budget": budget_value}
    BUDGET_FILE.write_text(json.dumps(data, indent=2) + "\n")


def check_budget(directory, extensions=None):
    """Check current project complexity against the budget.

    Args:
        directory: Root directory to scan
        extensions: Optional file extensions filter

    Returns:
        dict with within_budget, score, budget, and file details
    """
    budget = load_budget()
    scan = scan_project_complexity(directory, extensions)

    within_budget = True
    if budget is not None:
        within_budget = scan["total_score"] <= budget

    return {
        "within_budget": within_budget,
        "score": scan["total_score"],
        "budget": budget,
        "file_count": scan["file_count"],
        "hotspots": scan["hotspots"],
        "directory": scan["directory"],
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _health_bar(score, budget, width=20):
    """Render a text-based health bar.

    Args:
        score: Current score
        budget: Max budget (or None for no limit)
        width: Bar width in characters

    Returns:
        Formatted health bar string
    """
    if budget is None or budget == 0:
        return f"[{'?' * width}] {score}/∞"

    ratio = min(score / budget, 1.0)
    filled = int(ratio * width)
    empty = width - filled

    if ratio <= 0.6:
        bar_char = "█"
    elif ratio <= 0.85:
        bar_char = "█"
    else:
        bar_char = "█"

    bar = bar_char * filled + "░" * empty
    return f"[{bar}] {score}/{budget}"


def format_complexity_report(scan_results, budget=None):
    """Format a full complexity report for terminal display.

    Args:
        scan_results: Result from scan_project_complexity()
        budget: Optional budget value

    Returns:
        List of lines to print
    """
    lines = []
    lines.append("")
    lines.append("  ═══ COMPLEXITY REPORT ═══")
    lines.append("")

    total = scan_results["total_score"]
    file_count = scan_results["file_count"]
    bar = _health_bar(total, budget)

    lines.append(f"  Health: {bar}")
    lines.append(f"  Files scanned: {file_count}")
    lines.append(f"  Directory: {scan_results['directory']}")
    lines.append("")

    if budget is not None:
        if total <= budget:
            lines.append(f"  ✅ Within budget ({total}/{budget})")
        else:
            lines.append(f"  ⚠️  OVER BUDGET by {total - budget} points ({total}/{budget})")
    lines.append("")

    # Hotspots
    hotspots = scan_results.get("hotspots", [])
    if hotspots:
        lines.append("  Hotspots (highest complexity):")
        for i, file_result in enumerate(hotspots, 1):
            name = file_result["basename"]
            score = file_result["score"]
            loc = file_result["lines_of_code"]
            lines.append(f"    {i}. {name:<30} score: {score:>4}  ({loc} lines)")
            breakdown = file_result["breakdown"]
            parts = []
            if breakdown["branches"]:
                parts.append(f"branches={breakdown['branches']}")
            if breakdown["nesting_penalty"]:
                parts.append(f"nesting=+{breakdown['nesting_penalty']}")
            if breakdown["long_functions"]:
                parts.append(f"long_funcs=+{breakdown['long_functions']}")
            if breakdown["bad_variables"]:
                parts.append(f"bad_vars=+{breakdown['bad_variables']}")
            if parts:
                lines.append(f"       {', '.join(parts)}")
        lines.append("")

    # Long functions detail
    all_long = []
    for file_result in scan_results.get("files", []):
        for func in file_result.get("long_functions", []):
            all_long.append({
                "file": file_result["basename"],
                "name": func["name"],
                "lines": func["lines"],
            })

    if all_long:
        all_long.sort(key=lambda f: f["lines"], reverse=True)
        lines.append("  Long functions (>30 lines):")
        for func in all_long[:10]:
            lines.append(f"    {func['file']}:{func['name']}() — {func['lines']} lines")
        if len(all_long) > 10:
            lines.append(f"    ... and {len(all_long) - 10} more")
        lines.append("")

    lines.append("  Set budget: /complexity budget <number>")
    lines.append("")
    return lines


def format_file_report(file_result):
    """Format a single file's complexity report.

    Args:
        file_result: Result from calculate_file_complexity()

    Returns:
        List of lines to print
    """
    lines = []
    lines.append("")
    lines.append(f"  ═══ COMPLEXITY: {file_result['basename']} ═══")
    lines.append("")
    lines.append(f"  Score:           {file_result['score']}")
    lines.append(f"  Lines of code:   {file_result['lines_of_code']}")
    lines.append("")

    b = file_result["breakdown"]
    lines.append("  Breakdown:")
    lines.append(f"    Branches (if/for/while):  {b['branches']}")
    lines.append(f"    Max nesting depth:        {b['max_nesting_depth']}")
    lines.append(f"    Nesting penalty:          +{b['nesting_penalty']}")
    lines.append(f"    Long function penalty:    +{b['long_functions']}")
    lines.append(f"    Bad variable penalty:     +{b['bad_variables']}")
    lines.append("")

    if file_result["long_functions"]:
        lines.append("  Long functions:")
        for func in file_result["long_functions"]:
            lines.append(f"    {func['name']}() — {func['lines']} lines")
        lines.append("")

    return lines
