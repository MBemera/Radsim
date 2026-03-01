# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Repository structure mapping for RadSim.

Generates a ranked, token-budgeted overview of codebase architecture
using ast (Python) or regex fallback (JS/TS).

RadSim Principle: One Function, One Purpose
"""

import ast
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories to always skip during discovery
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".egg-info",
    ".radsim",
}

# Language extension mapping
LANGUAGE_EXTENSIONS = {
    "python": [".py"],
    "javascript": [".js", ".jsx", ".mjs"],
    "typescript": [".ts", ".tsx"],
}


def generate_repo_map(
    directory=".",
    focus_files=None,
    max_tokens=4000,
    language_filter=None,
):
    """Generate a structural map of the repository.

    Args:
        directory: Root directory to map.
        focus_files: Files to rank higher (currently relevant).
        max_tokens: Token budget (~4 chars per token).
        language_filter: Limit to specific language (e.g., "python").

    Returns:
        dict with 'success', 'map', 'file_count', 'symbol_count'.
    """
    root = Path(directory).resolve()

    if not root.is_dir():
        return {"success": False, "error": f"Not a directory: {directory}"}

    source_files = _discover_files(root, language_filter)

    if not source_files:
        return {
            "success": True,
            "map": "No source files found.",
            "file_count": 0,
            "symbol_count": 0,
        }

    # Extract symbols from each file
    all_symbols = {}
    for filepath in source_files:
        relative = str(filepath.relative_to(root))
        symbols = _extract_symbols(filepath)
        if symbols:
            all_symbols[relative] = symbols

    # Rank files (boost focus files)
    ranked_files = _rank_files(all_symbols, focus_files or [])

    # Render within token budget
    map_text = _render_map(ranked_files, all_symbols, max_tokens)

    total_symbols = sum(len(s) for s in all_symbols.values())

    return {
        "success": True,
        "map": map_text,
        "file_count": len(all_symbols),
        "symbol_count": total_symbols,
    }


def _discover_files(root, language_filter=None):
    """Find all source files, skipping common non-source directories."""
    if language_filter and language_filter in LANGUAGE_EXTENSIONS:
        allowed = set(LANGUAGE_EXTENSIONS[language_filter])
    else:
        allowed = set()
        for exts in LANGUAGE_EXTENSIONS.values():
            allowed.update(exts)

    # Also include common config/markup
    allowed.update([".json", ".yaml", ".yml", ".toml"])

    files = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in allowed:
            files.append(path)

    return sorted(files)


def _extract_symbols(filepath):
    """Extract function/class/method signatures from a file.

    Uses ast for Python, regex for JS/TS.
    """
    suffix = filepath.suffix

    if suffix == ".py":
        return _extract_python_symbols(filepath)
    elif suffix in (".js", ".jsx", ".ts", ".tsx"):
        return _extract_js_symbols_regex(filepath)
    else:
        return []


def _extract_python_symbols(filepath):
    """Extract symbols from Python using the ast module."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, ValueError):
        return []

    symbols = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(_get_base_name(b) for b in node.bases)
            base_str = f"({bases})" if bases else ""
            symbols.append({
                "type": "class",
                "name": node.name,
                "signature": f"class {node.name}{base_str}",
                "line": node.lineno,
            })

            # Get methods within the class
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = _get_function_signature(item)
                    prefix = "async def" if isinstance(item, ast.AsyncFunctionDef) else "def"
                    symbols.append({
                        "type": "method",
                        "name": f"{node.name}.{item.name}",
                        "signature": f"  {prefix} {item.name}{sig}",
                        "line": item.lineno,
                    })

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Only top-level functions (not methods inside classes)
            if not any(
                isinstance(parent, ast.ClassDef)
                for parent in ast.walk(tree)
                if hasattr(parent, "body") and node in getattr(parent, "body", [])
            ):
                sig = _get_function_signature(node)
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                symbols.append({
                    "type": "function",
                    "name": node.name,
                    "signature": f"{prefix} {node.name}{sig}",
                    "line": node.lineno,
                })

    return symbols


def _get_function_signature(node):
    """Build a function signature string from an AST node."""
    simple_args = [a.arg for a in node.args.args]

    return_hint = ""
    if node.returns:
        return_hint = " -> ..."

    return f"({', '.join(simple_args)}){return_hint}"


def _get_base_name(node):
    """Get the name from an AST base class node."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return f"{_get_base_name(node.value)}.{node.attr}"
    return "?"


def _extract_js_symbols_regex(filepath):
    """Extract symbols from JS/TS files using regex (fallback)."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    symbols = []
    patterns = [
        (r"(?:export\s+)?class\s+(\w+)", "class"),
        (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", "function"),
        (r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>", "function"),
    ]

    for pattern, sym_type in patterns:
        for match in re.finditer(pattern, source):
            name = match.group(1)
            symbols.append({
                "type": sym_type,
                "name": name,
                "signature": match.group(0)[:80],
                "line": source[: match.start()].count("\n") + 1,
            })

    return symbols


def _rank_files(all_symbols, focus_files):
    """Rank files by relevance. Focus files get highest priority."""
    scores = {}

    for filepath, symbols in all_symbols.items():
        score = len(symbols)  # More symbols = more important

        # Boost focus files significantly
        if filepath in focus_files:
            score += 100

        # Boost files with classes (likely core architecture)
        class_count = sum(1 for s in symbols if s["type"] == "class")
        score += class_count * 3

        # Slight penalty for test files (useful but secondary)
        if "test" in filepath.lower():
            score *= 0.5

        scores[filepath] = score

    return sorted(scores.keys(), key=lambda f: scores[f], reverse=True)


def _render_map(ranked_files, all_symbols, max_tokens):
    """Render the map within a token budget."""
    char_budget = max_tokens * 4  # ~4 chars per token
    lines = []
    chars_used = 0
    files_rendered = 0

    for filepath in ranked_files:
        symbols = all_symbols.get(filepath, [])

        # File header
        header = f"\n{filepath}"

        # Symbol lines
        symbol_lines = []
        for sym in symbols:
            symbol_lines.append(f"  {sym['signature']}")

        block = header + "\n" + "\n".join(symbol_lines) + "\n"

        if chars_used + len(block) > char_budget:
            # Try to fit just the header with symbol count
            summary = f"\n{filepath} ({len(symbols)} symbols)\n"
            if chars_used + len(summary) < char_budget:
                lines.append(summary)
                chars_used += len(summary)
                files_rendered += 1
            else:
                remaining = len(ranked_files) - files_rendered
                lines.append(f"\n... and {remaining} more files\n")
                break
        else:
            lines.append(block)
            chars_used += len(block)
            files_rendered += 1

    return "".join(lines).strip()
