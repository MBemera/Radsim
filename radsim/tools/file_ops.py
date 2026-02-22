"""File operations for RadSim tools.

RadSim Principle: One Function, One Purpose
"""


from .constants import MAX_FILE_SIZE, MAX_FILES_TO_READ, MAX_TRUNCATED_SIZE
from .validation import is_protected_path, validate_path


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

    try:
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        if not path.is_file():
            return {"success": False, "error": f"Not a file: {file_path}"}

        # Check file size
        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            return {
                "success": False,
                "error": f"File too large ({file_size} bytes). Max: {MAX_FILE_SIZE} bytes",
            }

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
        file_paths: List of file paths to read

    Returns:
        dict with success, files (list of results)
    """
    results = []
    for file_path in file_paths[:MAX_FILES_TO_READ]:
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


def write_file(file_path, content, show_diff=True):
    """Write content to a file. Creates parent directories if needed.

    Args:
        file_path: Path to the file
        content: Content to write
        show_diff: If True, display diff for existing files

    Returns:
        dict with success, path, bytes_written
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}

    # Check protected patterns
    is_protected, reason = is_protected_path(file_path)
    if is_protected:
        return {"success": False, "error": f"Cannot write: {reason}"}

    try:
        # Read existing content for diff display
        old_content = None
        is_new_file = not path.exists()

        if not is_new_file and show_diff:
            try:
                old_content = path.read_text(encoding="utf-8")
            except Exception:
                old_content = None

        # Create parent directories
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        path.write_text(content, encoding="utf-8")

        # Show diff if file was modified (not created)
        if old_content is not None and old_content != content:
            from ..output import print_diff

            print_diff(old_content, content, str(path))

        return {
            "success": True,
            "path": str(path),
            "bytes_written": len(content.encode("utf-8")),
            "is_new_file": is_new_file,
        }
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {file_path}"}
    except Exception as error:
        return {"success": False, "error": str(error)}


def replace_in_file(file_path, old_string, new_string, replace_all=False, show_diff=True):
    """Replace text in a file (like Claude Code's Edit tool).

    Args:
        file_path: Path to the file
        old_string: Exact text to find
        new_string: Text to replace with
        replace_all: If True, replace all occurrences
        show_diff: If True, display diff after replacement

    Returns:
        dict with success, replacements_made
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}

    is_protected, reason = is_protected_path(file_path)
    if is_protected:
        return {"success": False, "error": f"Cannot modify: {reason}"}

    try:
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        content = path.read_text(encoding="utf-8")

        # Check if old_string exists
        if old_string not in content:
            return {"success": False, "error": "Old string not found in file"}

        # Count occurrences
        count = content.count(old_string)

        if count > 1 and not replace_all:
            return {
                "success": False,
                "error": f"Multiple matches ({count}) found. Use replace_all=true or provide more context.",
            }

        # Perform replacement
        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1

        path.write_text(new_content, encoding="utf-8")

        # Show diff of changes
        if show_diff and content != new_content:
            from ..output import print_diff

            print_diff(content, new_content, str(path))

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

    try:
        if not path_old.exists():
            return {"success": False, "error": f"Source not found: {old_path}"}

        if path_new.exists():
            return {"success": False, "error": f"Destination already exists: {new_path}"}

        # Create parent directories for new path
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

    try:
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        if path.is_dir():
            return {"success": False, "error": f"Use delete_directory for directories: {file_path}"}

        path.unlink()

        return {"success": True, "path": str(path)}
    except Exception as error:
        return {"success": False, "error": str(error)}
