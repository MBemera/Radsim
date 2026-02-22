"""Directory operations for RadSim tools.

RadSim Principle: One Function, One Purpose
"""

import logging

from .constants import MAX_DIRECTORY_ITEMS
from .validation import validate_path

logger = logging.getLogger(__name__)


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

    try:
        if not path.exists():
            return {"success": False, "error": f"Directory not found: {directory_path}"}

        if not path.is_dir():
            return {"success": False, "error": f"Not a directory: {directory_path}"}

        items = []

        def add_items(current_path, depth=0):
            if depth > max_depth:
                return

            try:
                for item in sorted(current_path.iterdir()):
                    # Skip hidden files/dirs
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

                    if len(items) >= MAX_DIRECTORY_ITEMS:
                        return
            except PermissionError:
                logger.debug(f"Permission denied listing directory: {current_path}")

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
