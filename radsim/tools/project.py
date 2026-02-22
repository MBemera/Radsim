"""Project tools for RadSim (batch operations, planning, context).

RadSim Principle: One Function, One Purpose
"""

import json
import re
import time
from pathlib import Path

from .testing import detect_project_type
from .validation import is_protected_path, validate_path


def get_project_info():
    """Get information about the current project.

    Returns:
        dict with project details
    """
    project = detect_project_type()
    cwd = Path.cwd()

    info = {"success": True, "project_name": cwd.name, "project_path": str(cwd), **project}

    # Count files by type
    file_counts = {}
    for ext in [".py", ".js", ".ts", ".go", ".rs", ".java"]:
        count = len(list(cwd.glob(f"**/*{ext}")))
        if count > 0:
            file_counts[ext] = count
    info["file_counts"] = file_counts

    # Check for common config files
    config_files = []
    for cfg in [
        "README.md",
        "LICENSE",
        ".gitignore",
        "Dockerfile",
        "docker-compose.yml",
        "Makefile",
    ]:
        if (cwd / cfg).exists():
            config_files.append(cfg)
    info["config_files"] = config_files

    return info


def batch_replace(pattern, replacement, file_pattern="*", directory_path="."):
    """Replace text across multiple files.

    Args:
        pattern: Text or regex pattern to find
        replacement: Text to replace with
        file_pattern: Glob pattern to filter files
        directory_path: Directory to search in

    Returns:
        dict with success, files_modified, total_replacements
    """
    is_safe, base_path, error = validate_path(directory_path)
    if not is_safe:
        return {"success": False, "error": error}

    files_modified = []
    total_replacements = 0

    try:
        regex = re.compile(pattern)
    except re.error:
        # Treat as literal string
        regex = None

    for file_path in base_path.glob(f"**/{file_pattern}"):
        if file_path.is_dir():
            continue
        if any(part.startswith(".") for part in file_path.parts):
            continue

        # Check protected patterns
        is_protected, reason = is_protected_path(str(file_path))
        if is_protected:
            continue

        try:
            content = file_path.read_text(encoding="utf-8")

            if regex:
                new_content, count = regex.subn(replacement, content)
            else:
                count = content.count(pattern)
                new_content = content.replace(pattern, replacement)

            if count > 0:
                file_path.write_text(new_content, encoding="utf-8")
                files_modified.append(
                    {"file": str(file_path.relative_to(base_path)), "replacements": count}
                )
                total_replacements += count

        except Exception:
            continue

    return {
        "success": True,
        "files_modified": files_modified,
        "file_count": len(files_modified),
        "total_replacements": total_replacements,
    }


def plan_task(task_description, subtasks=None):
    """Create a task plan with subtasks.

    Args:
        task_description: High-level task description
        subtasks: Optional list of subtask descriptions

    Returns:
        dict with task plan structure
    """
    plan = {
        "success": True,
        "task_id": f"task_{int(time.time())}",
        "description": task_description,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "planned",
        "subtasks": [],
    }

    if subtasks:
        for i, subtask in enumerate(subtasks):
            plan["subtasks"].append({"id": i + 1, "description": subtask, "status": "pending"})

    return plan


def save_context(context_data, filename="radsim_context.json"):
    """Save conversation/task context to file.

    Args:
        context_data: Dictionary of context to save
        filename: Name of file to save to

    Returns:
        dict with success, file path
    """
    context = {"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "data": context_data}

    context_dir = Path.home() / ".radsim" / "contexts"
    context_dir.mkdir(parents=True, exist_ok=True)

    file_path = context_dir / filename

    try:
        file_path.write_text(json.dumps(context, indent=2))
        return {"success": True, "path": str(file_path)}
    except Exception as error:
        return {"success": False, "error": str(error)}


def load_context(filename="radsim_context.json"):
    """Load saved context from file.

    Args:
        filename: Name of context file to load

    Returns:
        dict with success, context data
    """
    context_path = Path.home() / ".radsim" / "contexts" / filename

    if not context_path.exists():
        return {"success": False, "error": f"Context file not found: {filename}"}

    try:
        content = json.loads(context_path.read_text())
        return {
            "success": True,
            "saved_at": content.get("saved_at"),
            "data": content.get("data", {}),
        }
    except Exception as error:
        return {"success": False, "error": str(error)}


def submit_completion(summary, artifacts=None):
    """Submit task completion.

    Args:
        summary: Summary of work
        artifacts: List of files

    Returns:
        dict with success
    """
    return {
        "success": True,
        "summary": summary,
        "artifacts": artifacts or [],
        "status": "completed",
    }



# delegate_task is handled directly by agent.py, not here
