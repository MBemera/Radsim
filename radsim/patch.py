# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Multi-file patch application for RadSim.

Parses a simplified unified diff format and applies changes
across multiple files atomically.

Format:
    --- a/path/to/file.py
    +++ b/path/to/file.py
    @@
    -old line 1
    +new line 1
    --- /dev/null
    +++ b/path/to/new_file.py
    @@
    +entire content
    --- a/path/to/delete_me.py
    +++ /dev/null

RadSim Principle: One Function, One Purpose
"""

import logging

from .tools.validation import is_protected_path, validate_path

logger = logging.getLogger(__name__)


def apply_patch(patch_text):
    """Parse and apply a multi-file patch.

    Atomic: validates all hunks first, applies only if all valid.

    Args:
        patch_text: Simplified unified diff text.

    Returns:
        dict with success, files_modified, files_created, files_deleted.
    """
    if not patch_text or not patch_text.strip():
        return {"success": False, "error": "Empty patch text."}

    # Phase 1: Parse the patch into file operations
    operations = _parse_patch(patch_text)

    if not operations:
        return {"success": False, "error": "No valid operations found in patch."}

    # Phase 2: Validate all operations
    errors = _validate_operations(operations)
    if errors:
        return {
            "success": False,
            "error": "Patch validation failed:\n" + "\n".join(errors),
        }

    # Phase 3: Apply all operations
    results = _apply_operations(operations)

    return {
        "success": True,
        "files_modified": results.get("modified", []),
        "files_created": results.get("created", []),
        "files_deleted": results.get("deleted", []),
        "summary": results.get("summary", ""),
    }


def _parse_patch(patch_text):
    """Parse patch text into a list of operations."""
    operations = []
    lines = patch_text.strip().split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for file headers
        if line.startswith("--- "):
            old_path = line[4:].strip()
            if old_path.startswith("a/"):
                old_path = old_path[2:]

            i += 1
            if i >= len(lines) or not lines[i].startswith("+++ "):
                continue

            new_path = lines[i][4:].strip()
            if new_path.startswith("b/"):
                new_path = new_path[2:]

            i += 1

            # Determine operation type
            if old_path == "/dev/null":
                op_type = "create"
                file_path = new_path
            elif new_path == "/dev/null":
                op_type = "delete"
                file_path = old_path
            else:
                op_type = "modify"
                file_path = new_path

            # Parse hunks
            hunks = []
            current_old = []
            current_new = []

            while i < len(lines):
                hunk_line = lines[i]

                if hunk_line.startswith("--- "):
                    break  # Next file
                elif hunk_line.startswith("@@"):
                    # Save previous hunk if exists
                    if current_old or current_new:
                        hunks.append({"old": current_old, "new": current_new})
                    current_old = []
                    current_new = []
                    i += 1
                    continue
                elif hunk_line.startswith("-"):
                    current_old.append(hunk_line[1:])
                elif hunk_line.startswith("+"):
                    current_new.append(hunk_line[1:])
                elif hunk_line.startswith(" "):
                    # Context line (unchanged)
                    current_old.append(hunk_line[1:])
                    current_new.append(hunk_line[1:])
                i += 1

            # Save last hunk
            if current_old or current_new:
                hunks.append({"old": current_old, "new": current_new})

            operations.append({
                "type": op_type,
                "path": file_path,
                "hunks": hunks,
            })
        else:
            i += 1

    return operations


def _validate_operations(operations):
    """Validate all operations can be applied."""
    errors = []

    for op in operations:
        file_path = op["path"]

        # Check protected paths
        is_protected, reason = is_protected_path(file_path)
        if is_protected:
            errors.append(f"{op['type'].title()} {file_path}: {reason}")
            continue

        is_safe, path, error = validate_path(file_path)
        if not is_safe:
            errors.append(f"{op['type'].title()} {file_path}: {error}")
            continue

        if op["type"] == "create":
            if path.exists():
                errors.append(f"Create {file_path}: file already exists")

        elif op["type"] == "delete":
            if not path.exists():
                errors.append(f"Delete {file_path}: file not found")

        elif op["type"] == "modify":
            if not path.exists():
                errors.append(f"Modify {file_path}: file not found")
            else:
                # Check all hunks can be found
                try:
                    content = path.read_text(encoding="utf-8")
                except OSError as e:
                    errors.append(f"Modify {file_path}: cannot read: {e}")
                    continue

                for j, hunk in enumerate(op["hunks"]):
                    old_text = "\n".join(hunk["old"])
                    if old_text and old_text not in content:
                        errors.append(f"Modify {file_path} hunk {j + 1}: old text not found")

    return errors


def _apply_operations(operations):
    """Apply validated operations."""
    modified = []
    created = []
    deleted = []

    for op in operations:
        is_safe, safe_path, error = validate_path(op["path"])
        if not is_safe:
            continue

        if op["type"] == "create":
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            content = "\n".join(op["hunks"][0]["new"]) if op["hunks"] else ""
            safe_path.write_text(content, encoding="utf-8")
            created.append(op["path"])

        elif op["type"] == "delete":
            safe_path.unlink()
            deleted.append(op["path"])

        elif op["type"] == "modify":
            content = safe_path.read_text(encoding="utf-8")
            for hunk in op["hunks"]:
                old_text = "\n".join(hunk["old"])
                new_text = "\n".join(hunk["new"])
                content = content.replace(old_text, new_text, 1)
            safe_path.write_text(content, encoding="utf-8")
            modified.append(op["path"])

    parts = []
    if created:
        parts.append(f"Created: {', '.join(created)}")
    if modified:
        parts.append(f"Modified: {', '.join(modified)}")
    if deleted:
        parts.append(f"Deleted: {', '.join(deleted)}")

    return {
        "created": created,
        "modified": modified,
        "deleted": deleted,
        "summary": " | ".join(parts),
    }
