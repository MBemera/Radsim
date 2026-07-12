"""Git operations for RadSim tools.

RadSim Principle: Standard Patterns Only
"""

from .shell import format_process_command, run_process

# =============================================================================
# GIT READ OPERATIONS
# =============================================================================


def git_status():
    """Get git repository status."""
    return run_process(["git", "-c", "core.fsmonitor=false", "status", "--porcelain", "-b"])


def git_diff(staged=False, file_path=None):
    """Get git diff.

    Args:
        staged: If True, show staged changes
        file_path: Optional specific file to diff
    """
    arguments = ["git", "diff", "--no-ext-diff", "--no-textconv"]
    if staged:
        arguments.append("--staged")
    if file_path:
        arguments.extend(["--", str(file_path)])
    return run_process(arguments)


def git_log(count=10, oneline=True):
    """Get git commit log.

    Args:
        count: Number of commits to show
        oneline: If True, show one line per commit
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        return {"success": False, "error": "Count must be an integer"}
    if not 1 <= count <= 1000:
        return {"success": False, "error": "Count must be between 1 and 1000"}

    arguments = ["git", "log", "-n", str(count)]
    if oneline:
        arguments.append("--oneline")
    return run_process(arguments)


def git_branch():
    """List git branches."""
    return run_process(["git", "branch", "-a"])


# =============================================================================
# GIT WRITE OPERATIONS
# =============================================================================


def git_add(file_paths=None, all_files=False):
    """Stage files for commit.

    Args:
        file_paths: List of specific files to stage
        all_files: Stage all changes (git add -A)

    Returns:
        dict with success, staged_files
    """
    if all_files:
        arguments = ["git", "add", "-A"]
    elif file_paths:
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        if not isinstance(file_paths, (list, tuple)) or not all(
            isinstance(path, str) and path and "\x00" not in path for path in file_paths
        ):
            return {"success": False, "error": "File paths must be non-empty strings"}
        arguments = ["git", "add", "--", *file_paths]
    else:
        return {"success": False, "error": "Specify file_paths or set all_files=True"}

    result = run_process(arguments)

    if result.get("returncode", 1) != 0:
        return {"success": False, "error": result.get("stderr", "Failed to stage files")}

    # Get list of staged files
    status = run_process(["git", "diff", "--cached", "--name-only"])
    staged = status.get("stdout", "").strip().split("\n") if status.get("stdout") else []

    return {
        "success": True,
        "staged_files": [file for file in staged if file],
        "command": format_process_command(arguments),
    }


def git_commit(message, amend=False):
    """Create a git commit.

    Args:
        message: Commit message
        amend: Amend the previous commit

    Returns:
        dict with success, commit_hash, message
    """
    if not isinstance(message, str) or not message or "\x00" in message:
        return {"success": False, "error": "Commit message is required"}

    arguments = ["git", "commit"]
    if amend:
        arguments.append("--amend")
    arguments.extend(["-m", message])

    result = run_process(arguments)

    if result.get("returncode", 1) != 0:
        stderr = result.get("stderr", "")
        if "nothing to commit" in stderr or "nothing added to commit" in result.get("stdout", ""):
            return {"success": False, "error": "Nothing to commit. Stage files first."}
        return {"success": False, "error": stderr or "Commit failed"}

    # Get the commit hash
    hash_result = run_process(["git", "rev-parse", "--short", "HEAD"])
    commit_hash = hash_result.get("stdout", "").strip()

    return {"success": True, "commit_hash": commit_hash, "message": message, "amend": amend}


def git_checkout(branch=None, create=False, file_path=None):
    """Switch branches or restore files.

    Args:
        branch: Branch name to checkout
        create: Create new branch if True
        file_path: Restore specific file from HEAD

    Returns:
        dict with success, branch or file restored
    """
    if file_path:
        result = run_process(["git", "checkout", "--", str(file_path)])
        return {
            "success": result.get("returncode", 1) == 0,
            "restored_file": file_path,
            "error": result.get("stderr", "") if result.get("returncode", 1) != 0 else None,
        }

    if not branch:
        return {"success": False, "error": "Branch name or file_path required"}

    if not isinstance(branch, str) or branch.startswith("-") or "\x00" in branch:
        return {"success": False, "error": "Invalid branch name"}

    arguments = ["git", "checkout", *(["-b"] if create else []), branch]
    result = run_process(arguments)

    return {
        "success": result.get("returncode", 1) == 0,
        "branch": branch,
        "created": create,
        "error": result.get("stderr", "") if result.get("returncode", 1) != 0 else None,
    }


def git_stash(action="push", message=None):
    """Stash or restore changes.

    Args:
        action: "push" to stash, "pop" to restore, "list" to show stashes
        message: Optional message for stash

    Returns:
        dict with success, action performed
    """
    if action == "push":
        arguments = ["git", "stash", "push"]
        if message:
            if not isinstance(message, str) or "\x00" in message:
                return {"success": False, "error": "Invalid stash message"}
            arguments.extend(["-m", message])
    elif action == "pop":
        arguments = ["git", "stash", "pop"]
    elif action == "list":
        arguments = ["git", "stash", "list"]
    elif action == "drop":
        arguments = ["git", "stash", "drop"]
    else:
        return {"success": False, "error": f"Unknown action: {action}"}

    result = run_process(arguments)

    return {
        "success": result.get("returncode", 1) == 0,
        "action": action,
        "stdout": result.get("stdout", ""),
        "error": result.get("stderr", "") if result.get("returncode", 1) != 0 else None,
    }
