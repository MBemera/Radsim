"""Search tools for RadSim (glob and grep).

RadSim Principle: Standard Patterns Only
"""

import fnmatch
import os
import re
from pathlib import Path

from .constants import MAX_SEARCH_RESULTS
from .validation import validate_path


def glob_files(pattern, directory_path="."):
    """Find files matching a glob pattern (like Claude Code's Glob tool).

    Args:
        pattern: Glob pattern (e.g., "**/*.py", "src/**/*.ts")
        directory_path: Base directory for search

    Returns:
        dict with success, matches
    """
    is_safe, path, error = validate_path(directory_path)
    if not is_safe:
        return {"success": False, "error": error}

    try:
        matches = []

        for match in path.glob(pattern):
            # Skip hidden files
            if any(part.startswith(".") for part in match.parts):
                continue

            try:
                rel_path = match.relative_to(path)
                matches.append(str(rel_path))
            except ValueError:
                matches.append(str(match))

            if len(matches) >= MAX_SEARCH_RESULTS:
                break

        return {
            "success": True,
            "pattern": pattern,
            "matches": sorted(matches),
            "count": len(matches),
        }
    except Exception as error:
        return {"success": False, "error": str(error)}


def grep_search(pattern, directory_path=".", file_pattern=None, ignore_case=False, context_lines=0):
    """Search file contents with regex (like Claude Code's Grep tool).

    Args:
        pattern: Regex pattern to search for
        directory_path: Directory to search in
        file_pattern: Optional glob pattern to filter files (e.g., "*.py")
        ignore_case: If True, case-insensitive search
        context_lines: Number of context lines before/after match

    Returns:
        dict with success, matches (with file, line, content)
    """
    is_safe, path, error = validate_path(directory_path)
    if not is_safe:
        return {"success": False, "error": error}

    try:
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"success": False, "error": f"Invalid regex: {e}"}

    matches = []
    files_searched = 0

    try:
        for root, dirs, files in os.walk(str(path)):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for file_name in files:
                # Skip hidden files
                if file_name.startswith("."):
                    continue

                # Apply file pattern filter
                if file_pattern and not fnmatch.fnmatch(file_name, file_pattern):
                    continue

                file_path = Path(root) / file_name

                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    lines = content.split("\n")
                    files_searched += 1

                    for line_num, line in enumerate(lines, 1):
                        if regex.search(line):
                            try:
                                rel_path = file_path.relative_to(Path.cwd())
                            except ValueError:
                                rel_path = file_path

                            match_info = {
                                "file": str(rel_path),
                                "line": line_num,
                                "content": line.strip()[:200],  # Truncate long lines
                            }

                            # Add context if requested
                            if context_lines > 0:
                                start = max(0, line_num - context_lines - 1)
                                end = min(len(lines), line_num + context_lines)
                                match_info["context"] = lines[start:end]

                            matches.append(match_info)

                            if len(matches) >= MAX_SEARCH_RESULTS:
                                break

                    if len(matches) >= MAX_SEARCH_RESULTS:
                        break

                except Exception:
                    continue  # Skip unreadable files

            if len(matches) >= MAX_SEARCH_RESULTS:
                break

        return {
            "success": True,
            "pattern": pattern,
            "matches": matches,
            "count": len(matches),
            "files_searched": files_searched,
        }
    except Exception as error:
        return {"success": False, "error": str(error)}


def search_files(pattern, directory_path="."):
    """Simple text search (backwards compatibility).

    Args:
        pattern: Text to search for
        directory_path: Directory to search in

    Returns:
        dict with success, matches (file paths only)
    """
    result = grep_search(pattern, directory_path)
    if not result["success"]:
        return result

    # Extract unique file paths
    files = list({m["file"] for m in result["matches"]})
    return {"success": True, "matches": files, "count": len(files)}
