"""File and directory operations for RadSim Agent.

This module contains all file-related tools following RadSim principles:
- Read, write, edit files
- Directory listing and creation
- Path validation and security checks
"""

import fnmatch
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum file size to read (prevent context exhaustion)
MAX_FILE_SIZE = 100000  # 100KB
MAX_TRUNCATED_SIZE = 20000  # 20KB for display

# Protected path patterns - compiled once at module load
PROTECTED_PATTERNS = (
    ".env",
    ".env.*",
    "credentials",
    "secrets",
    ".git/config",
    "id_rsa",
    "id_ed25519",
    "*.pem",
    "*.key",
    "password",
    "token",
)


# =============================================================================
# PATH VALIDATION
# =============================================================================

# Cache for resolved CWD (avoids repeated filesystem access)
_cwd_cache = {"value": None}


def _get_cwd():
    """Get and cache the resolved current working directory.

    This avoids repeated Path.cwd().resolve() calls which involve
    filesystem access on each invocation.
    """
    if _cwd_cache["value"] is None:
        _cwd_cache["value"] = Path.cwd().resolve()
    return _cwd_cache["value"]


def clear_cwd_cache():
    """Clear the CWD cache. Call this if the working directory changes."""
    _cwd_cache["value"] = None


def validate_path(file_path, allow_outside=False):
    """Validate that a file path is safe and within project directory.

    Args:
        file_path: The path to validate
        allow_outside: If True, allows paths outside CWD (requires confirmation)

    Returns:
        Tuple of (is_safe, resolved_path, error_message)
    """
    if not file_path:
        return False, None, "Path cannot be empty"

    try:
        path = Path(file_path).resolve()
        cwd = _get_cwd()  # Cached

        is_inside_project = path == cwd or cwd in path.parents

        if not is_inside_project and not allow_outside:
            return False, None, f"Access denied: '{file_path}' is outside project directory"

        return True, path, None
    except Exception as error:
        return False, None, str(error)


def is_protected_path(file_path):
    """Check if a file path matches protected patterns.

    Args:
        file_path: Path to check

    Returns:
        Tuple of (is_protected, reason)
    """
    path_lower = file_path.lower()
    for pattern in PROTECTED_PATTERNS:
        if fnmatch.fnmatch(path_lower, f"*{pattern}*"):
            return True, f"Protected file pattern: {pattern}"

    return False, None


# =============================================================================
# FILE OPERATIONS
# =============================================================================


def read_file(file_path, offset=0, limit=None):
    """Read contents of a file.

    Args:
        file_path: Path to the file
        offset: Line number to start reading from (0-indexed)
        limit: Maximum number of lines to read

    Returns:
        dict with success, content, path, line_count
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}

    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    if not path.is_file():
        return {"success": False, "error": f"Not a file: {file_path}"}

    file_size = path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        return {
            "success": False,
            "error": f"File too large ({file_size} bytes). Max: {MAX_FILE_SIZE} bytes",
        }

    try:
        content = path.read_text(encoding="utf-8")
        lines = content.split("\n")
        total_lines = len(lines)

        # Apply offset and limit
        if offset > 0 or limit is not None:
            end = offset + limit if limit else None
            lines = lines[offset:end]
            content = "\n".join(lines)

        # Truncate if still too large
        if len(content) > MAX_TRUNCATED_SIZE:
            content = content[:MAX_TRUNCATED_SIZE]
            content += f"\n... [Truncated at {MAX_TRUNCATED_SIZE} chars, {total_lines} total lines]"

        return {
            "success": True,
            "content": content,
            "path": str(path),
            "line_count": total_lines,
            "offset": offset,
            "limit": limit,
        }

    except PermissionError:
        return {"success": False, "error": f"Permission denied: {file_path}"}
    except UnicodeDecodeError:
        return {"success": False, "error": f"Cannot read binary file: {file_path}"}
    except Exception as error:
        return {"success": False, "error": str(error)}


def read_many_files(file_paths):
    """Read multiple files at once.

    Args:
        file_paths: List of file paths to read (max 20)

    Returns:
        dict with success, files (list of results)
    """
    max_files = 20
    results = []

    for file_path in file_paths[:max_files]:
        result = read_file(file_path)
        results.append(
            {
                "path": file_path,
                "success": result["success"],
                "content": result.get("content", ""),
                "error": result.get("error", ""),
            }
        )

    return {"success": True, "files": results, "count": len(results)}


def write_file(file_path, content):
    """Write content to a file. Creates parent directories if needed.

    Args:
        file_path: Path to the file
        content: Content to write

    Returns:
        dict with success, path, bytes_written
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}

    is_protected, reason = is_protected_path(file_path)
    if is_protected:
        return {"success": False, "error": f"Cannot write: {reason}"}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        return {"success": True, "path": str(path), "bytes_written": len(content.encode("utf-8"))}
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {file_path}"}
    except Exception as error:
        return {"success": False, "error": str(error)}


def replace_in_file(file_path, old_string, new_string, replace_all=False):
    """Replace text in a file.

    Args:
        file_path: Path to the file
        old_string: Exact text to find
        new_string: Text to replace with
        replace_all: If True, replace all occurrences

    Returns:
        dict with success, replacements_made
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}

    is_protected, reason = is_protected_path(file_path)
    if is_protected:
        return {"success": False, "error": f"Cannot modify: {reason}"}

    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        content = path.read_text(encoding="utf-8")

        if old_string not in content:
            return {"success": False, "error": "Old string not found in file"}

        occurrence_count = content.count(old_string)

        if occurrence_count > 1 and not replace_all:
            return {
                "success": False,
                "error": f"Multiple matches ({occurrence_count}) found. Use replace_all=true or provide more context.",
            }

        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = occurrence_count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1

        path.write_text(new_content, encoding="utf-8")

        return {"success": True, "path": str(path), "replacements_made": replacements}
    except Exception as error:
        return {"success": False, "error": str(error)}


def rename_file(old_path, new_path):
    """Rename or move a file.

    Args:
        old_path: Current file path
        new_path: New file path

    Returns:
        dict with success, old_path, new_path
    """
    is_safe_old, path_old, error = validate_path(old_path)
    if not is_safe_old:
        return {"success": False, "error": error}

    is_safe_new, path_new, error = validate_path(new_path)
    if not is_safe_new:
        return {"success": False, "error": error}

    if not path_old.exists():
        return {"success": False, "error": f"Source not found: {old_path}"}

    if path_new.exists():
        return {"success": False, "error": f"Destination already exists: {new_path}"}

    try:
        path_new.parent.mkdir(parents=True, exist_ok=True)
        path_old.rename(path_new)

        return {"success": True, "old_path": str(path_old), "new_path": str(path_new)}
    except Exception as error:
        return {"success": False, "error": str(error)}


def delete_file(file_path):
    """Delete a file (requires confirmation in agent).

    Args:
        file_path: Path to the file to delete

    Returns:
        dict with success, path
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}

    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    if path.is_dir():
        return {"success": False, "error": f"Use delete_directory for directories: {file_path}"}

    try:
        path.unlink()
        return {"success": True, "path": str(path)}
    except Exception as error:
        return {"success": False, "error": str(error)}


# =============================================================================
# DIRECTORY OPERATIONS
# =============================================================================


def list_directory(directory_path=".", recursive=False, max_depth=3):
    """List contents of a directory.

    Args:
        directory_path: Path to list (default: current directory)
        recursive: If True, list recursively
        max_depth: Maximum recursion depth

    Returns:
        dict with success, items, count
    """
    is_safe, path, error = validate_path(directory_path)
    if not is_safe:
        return {"success": False, "error": error}

    if not path.exists():
        return {"success": False, "error": f"Directory not found: {directory_path}"}

    if not path.is_dir():
        return {"success": False, "error": f"Not a directory: {directory_path}"}

    items = []
    max_items = 500

    def add_items(current_path, depth=0):
        if depth > max_depth:
            return

        try:
            for item in sorted(current_path.iterdir()):
                if item.name.startswith("."):
                    continue

                try:
                    rel_path = item.relative_to(path)
                except ValueError:
                    rel_path = item.name

                item_info = {
                    "name": str(rel_path),
                    "type": "directory" if item.is_dir() else "file",
                }

                if item.is_file():
                    item_info["size"] = item.stat().st_size

                items.append(item_info)

                if recursive and item.is_dir() and depth < max_depth:
                    add_items(item, depth + 1)

                if len(items) >= max_items:
                    return
        except PermissionError:
            logger.debug(f"Permission denied when listing directory: {current_path}")

    try:
        add_items(path)

        return {"success": True, "path": str(path), "items": items, "count": len(items)}
    except Exception as error:
        return {"success": False, "error": str(error)}


def create_directory(directory_path):
    """Create a directory and any parent directories.

    Args:
        directory_path: Path of directory to create

    Returns:
        dict with success, path
    """
    is_safe, path, error = validate_path(directory_path)
    if not is_safe:
        return {"success": False, "error": error}

    try:
        path.mkdir(parents=True, exist_ok=True)
        return {"success": True, "path": str(path)}
    except Exception as error:
        return {"success": False, "error": str(error)}
