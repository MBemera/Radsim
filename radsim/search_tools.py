"""Compatibility wrappers for the canonical tool-layer search modules."""

from .tools import code_intel as _code_intel
from .tools.search import glob_files as _glob_files
from .tools.search import grep_search as _grep_search
from .tools.search import search_files as _search_files

find_definition = _code_intel.find_definition
find_references = _code_intel.find_references


def glob_files(pattern, directory="."):
    """Backward-compatible wrapper for glob search."""
    result = _glob_files(pattern, directory)
    if not result.get("success"):
        return result

    return {
        "success": True,
        "files": result["matches"],
        "count": result["count"],
        "pattern": pattern,
        "truncated": result["count"] >= 100,
    }


def grep_search(pattern, directory=".", file_pattern="*", max_results=100):
    """Backward-compatible wrapper for grep search."""
    result = _grep_search(pattern, directory, file_pattern=file_pattern)
    if not result.get("success"):
        return result

    matches = result["matches"][:max_results]
    return {
        "success": True,
        "matches": matches,
        "count": len(matches),
        "files_searched": result.get("files_searched", 0),
        "files_with_matches": len({match["file"] for match in matches}),
        "truncated": result.get("count", 0) > len(matches),
    }


def search_files(query, directory=".", case_sensitive=False):
    """Backward-compatible wrapper for simple file search."""
    return _search_files(query, directory, case_sensitive=case_sensitive)
