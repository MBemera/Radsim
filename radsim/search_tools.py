"""Search and code intelligence tools for RadSim Agent.

This module contains search-related tools following RadSim principles.
"""

import re

from .file_tools import validate_path

# =============================================================================
# PERFORMANCE CONSTANTS
# =============================================================================

# Binary/non-searchable extensions - frozenset for O(1) lookup
SKIP_EXTENSIONS = frozenset(
    {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",  # Binaries
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",  # Archives
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".svg",  # Images
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",  # Fonts
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",  # Documents
        ".pyc",
        ".pyo",
        ".class",  # Compiled
    }
)

# Maximum file size for searching (500KB)
MAX_SEARCH_SIZE = 500000


# =============================================================================
# GLOB AND FILE SEARCH
# =============================================================================


def glob_files(pattern, directory="."):
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., "**/*.py", "src/**/*.ts")
        directory: Base directory for search

    Returns:
        dict with success, files, count
    """
    is_safe, path, error = validate_path(directory)
    if not is_safe:
        return {"success": False, "error": error}

    if not path.is_dir():
        return {"success": False, "error": f"Not a directory: {directory}"}

    try:
        matches = list(path.glob(pattern))
        max_results = 500

        files = []
        for match in matches[:max_results]:
            if match.is_file():
                try:
                    rel_path = match.relative_to(path)
                    files.append(str(rel_path))
                except ValueError:
                    files.append(str(match))

        return {
            "success": True,
            "files": files,
            "count": len(files),
            "pattern": pattern,
            "truncated": len(matches) > max_results,
        }
    except Exception as error:
        return {"success": False, "error": str(error)}


def grep_search(pattern, directory=".", file_pattern="*", max_results=100):
    """Search file contents with regex.

    Args:
        pattern: Regex pattern to search for
        directory: Directory to search in
        file_pattern: Glob pattern to filter files (default: all files)
        max_results: Maximum matches to return

    Returns:
        dict with success, matches, count, files_searched
    """
    is_safe, path, error = validate_path(directory)
    if not is_safe:
        return {"success": False, "error": error}

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as err:
        return {"success": False, "error": f"Invalid regex: {err}"}

    matches = []
    files_searched = 0
    files_with_matches = set()

    try:
        for file_path in path.rglob(file_pattern):
            if not file_path.is_file():
                continue

            # Skip binary files (fast path - no I/O)
            if file_path.suffix.lower() in SKIP_EXTENSIONS:
                continue

            # Skip large files
            if file_path.stat().st_size > MAX_SEARCH_SIZE:
                continue

            files_searched += 1

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.split("\n")

                for line_num, line in enumerate(lines, 1):
                    if regex.search(line):
                        try:
                            rel = file_path.relative_to(path)
                        except ValueError:
                            rel = file_path.name

                        matches.append(
                            {
                                "file": str(rel),
                                "line": line_num,
                                "content": line.strip()[:200],  # Truncate long lines
                            }
                        )

                        files_with_matches.add(str(rel))

                        if len(matches) >= max_results:
                            break

            except (PermissionError, UnicodeDecodeError):
                continue

            if len(matches) >= max_results:
                break

        return {
            "success": True,
            "matches": matches,
            "count": len(matches),
            "files_searched": files_searched,
            "files_with_matches": len(files_with_matches),
            "truncated": len(matches) >= max_results,
        }

    except Exception as error:
        return {"success": False, "error": str(error)}


def search_files(query, directory=".", case_sensitive=False):
    """Simple text search - returns files containing the query.

    Args:
        query: Text to search for
        directory: Directory to search
        case_sensitive: Match case exactly

    Returns:
        dict with success, files, count
    """
    is_safe, path, error = validate_path(directory)
    if not is_safe:
        return {"success": False, "error": error}

    matching_files = []
    max_files = 100

    try:
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip binary files (fast path - no I/O)
            if file_path.suffix.lower() in SKIP_EXTENSIONS:
                continue

            # Skip large files
            if file_path.stat().st_size > MAX_SEARCH_SIZE:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")

                if case_sensitive:
                    found = query in content
                else:
                    found = query.lower() in content.lower()

                if found:
                    try:
                        rel = file_path.relative_to(path)
                    except ValueError:
                        rel = file_path.name
                    matching_files.append(str(rel))

                if len(matching_files) >= max_files:
                    break

            except (PermissionError, UnicodeDecodeError):
                continue

        return {
            "success": True,
            "files": matching_files,
            "count": len(matching_files),
            "query": query,
            "truncated": len(matching_files) >= max_files,
        }

    except Exception as error:
        return {"success": False, "error": str(error)}


# =============================================================================
# CODE INTELLIGENCE
# =============================================================================


def find_definition(symbol, file_extensions=None, directory="."):
    """Find where a symbol is defined (class, function, variable).

    Args:
        symbol: Name of the symbol to find
        file_extensions: List of extensions to search (default: common code files)
        directory: Directory to search

    Returns:
        dict with success, definitions, count
    """
    if not file_extensions:
        file_extensions = [".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java"]

    # Patterns for different languages
    definition_patterns = [
        rf"^\s*(def|async def)\s+{re.escape(symbol)}\s*\(",  # Python function
        rf"^\s*class\s+{re.escape(symbol)}\s*[\(:]",  # Python/JS class
        rf"^\s*(const|let|var)\s+{re.escape(symbol)}\s*=",  # JS variable
        rf"^\s*function\s+{re.escape(symbol)}\s*\(",  # JS function
        rf"^\s*(export\s+)?(const|let|var|function|class)\s+{re.escape(symbol)}",  # JS export
        rf"^\s*func\s+{re.escape(symbol)}\s*\(",  # Go function
        rf"^\s*fn\s+{re.escape(symbol)}\s*\(",  # Rust function
        rf"^\s*(public|private|protected)?\s*\w+\s+{re.escape(symbol)}\s*\(",  # Java/C# method
    ]

    combined_pattern = "|".join(definition_patterns)

    is_safe, path, error = validate_path(directory)
    if not is_safe:
        return {"success": False, "error": error}

    definitions = []
    try:
        regex = re.compile(combined_pattern, re.MULTILINE)

        for ext in file_extensions:
            for file_path in path.rglob(f"*{ext}"):
                if not file_path.is_file():
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    lines = content.split("\n")

                    for line_num, line in enumerate(lines, 1):
                        if regex.search(line):
                            try:
                                rel = file_path.relative_to(path)
                            except ValueError:
                                rel = file_path.name

                            definitions.append(
                                {
                                    "file": str(rel),
                                    "line": line_num,
                                    "definition": line.strip()[:150],
                                }
                            )

                except (PermissionError, UnicodeDecodeError):
                    continue

        return {
            "success": True,
            "symbol": symbol,
            "definitions": definitions,
            "count": len(definitions),
        }

    except Exception as error:
        return {"success": False, "error": str(error)}


def find_references(symbol, file_extensions=None, directory="."):
    """Find all references to a symbol.

    Args:
        symbol: Symbol to find references of
        file_extensions: Extensions to search
        directory: Directory to search

    Returns:
        dict with success, references, count
    """
    if not file_extensions:
        file_extensions = [".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java"]

    is_safe, path, error = validate_path(directory)
    if not is_safe:
        return {"success": False, "error": error}

    references = []
    max_refs = 200

    try:
        # Match word boundaries for the symbol
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")

        for ext in file_extensions:
            for file_path in path.rglob(f"*{ext}"):
                if not file_path.is_file():
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    lines = content.split("\n")

                    for line_num, line in enumerate(lines, 1):
                        if pattern.search(line):
                            try:
                                rel = file_path.relative_to(path)
                            except ValueError:
                                rel = file_path.name

                            references.append(
                                {"file": str(rel), "line": line_num, "content": line.strip()[:150]}
                            )

                            if len(references) >= max_refs:
                                break

                except (PermissionError, UnicodeDecodeError):
                    continue

                if len(references) >= max_refs:
                    break

            if len(references) >= max_refs:
                break

        return {
            "success": True,
            "symbol": symbol,
            "references": references,
            "count": len(references),
            "truncated": len(references) >= max_refs,
        }

    except Exception as error:
        return {"success": False, "error": str(error)}
