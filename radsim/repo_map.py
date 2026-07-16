# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Repository structure mapping for RadSim.

Generates a ranked, token-budgeted overview of codebase architecture
using ast (Python) or regex fallback (JS/TS).

RadSim Principle: One Function, One Purpose
"""

import ast
import hashlib
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

PARSER_VERSION = 2
MAX_SYMBOL_CACHE_ENTRIES = 512
_SYMBOL_CACHE = {}


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
            "error_count": 0,
            "errors": [],
        }

    # Extract symbols from each file
    all_symbols = {}
    errors = []
    for filepath in source_files:
        relative = str(filepath.relative_to(root))
        symbols = _extract_symbols(filepath)
        if symbols:
            all_symbols[relative] = symbols
        for symbol in symbols:
            if symbol["type"] == "error":
                errors.append({"file": relative, "error": symbol["name"]})

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
        "error_count": len(errors),
        "errors": errors,
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
        file_bytes = filepath.read_bytes()
    except OSError as error:
        return [_error_symbol(f"read failed: {error}")]

    cache_key = _build_cache_key(file_bytes, "python")
    cached_symbols = _SYMBOL_CACHE.get(cache_key)
    if cached_symbols is not None:
        return _copy_symbols(cached_symbols)

    source = file_bytes.decode("utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as error:
        symbols = [_syntax_error_symbol(error)]
        _cache_symbols(cache_key, symbols)
        return symbols
    except ValueError as error:
        symbols = [_error_symbol(f"parse failed: {error}")]
        _cache_symbols(cache_key, symbols)
        return symbols

    symbols = []
    method_owners = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_owners[id(child)] = node.name

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

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            class_name = method_owners.get(id(node))
            symbols.append(_function_symbol(node, class_name))

    _cache_symbols(cache_key, symbols)
    return symbols


def _function_symbol(node, class_name=None):
    """Build one function or direct-class-method symbol."""
    signature = _get_function_signature(node)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    if class_name:
        return {
            "type": "method",
            "name": f"{class_name}.{node.name}",
            "signature": f"  {prefix} {node.name}{signature}",
            "line": node.lineno,
        }
    return {
        "type": "function",
        "name": node.name,
        "signature": f"{prefix} {node.name}{signature}",
        "line": node.lineno,
    }


def _build_cache_key(file_bytes, parser_options):
    """Build a content-based cache key for one parser configuration."""
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    return content_hash, PARSER_VERSION, parser_options


def _cache_symbols(cache_key, symbols):
    """Cache symbols and evict the oldest entry when the bound is reached."""
    if cache_key not in _SYMBOL_CACHE and len(_SYMBOL_CACHE) >= MAX_SYMBOL_CACHE_ENTRIES:
        oldest_key = next(iter(_SYMBOL_CACHE))
        del _SYMBOL_CACHE[oldest_key]
    _SYMBOL_CACHE[cache_key] = _copy_symbols(symbols)


def _copy_symbols(symbols):
    """Return symbols that callers can mutate without changing the cache."""
    return [symbol.copy() for symbol in symbols]


def _error_symbol(message, line=0):
    """Build a visible per-file parser diagnostic."""
    return {
        "type": "error",
        "name": message,
        "signature": f"[repo-map error: {message}]",
        "line": line,
    }


def _syntax_error_symbol(error):
    """Build a stable diagnostic without embedding an absolute file path."""
    line = error.lineno or 0
    return _error_symbol(f"syntax error at line {line}: {error.msg}", line)


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
        file_bytes = filepath.read_bytes()
    except OSError as error:
        return [_error_symbol(f"read failed: {error}")]

    cache_key = _build_cache_key(file_bytes, f"regex:{filepath.suffix}")
    cached_symbols = _SYMBOL_CACHE.get(cache_key)
    if cached_symbols is not None:
        return _copy_symbols(cached_symbols)

    source = file_bytes.decode("utf-8", errors="replace")
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

    _cache_symbols(cache_key, symbols)
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
