"""Git operations for RadSim Agent.

This module contains all git-related tools following RadSim principles.
"""

import shlex

from .shell_tools import run_shell_command

# =============================================================================
# GIT READ OPERATIONS
# =============================================================================


def git_status():
    """Get git repository status.

    Returns:
        dict with success, stdout, stderr
    """
    return run_shell_command("git status --porcelain -b")


def git_diff(staged=False, file_path=None):
    """Get git diff.

    Args:
        staged: If True, show staged changes
        file_path: Optional specific file to diff

    Returns:
        dict with success, stdout, stderr
    """
    cmd = "git diff"
    if staged:
        cmd += " --staged"
    if file_path:
        cmd += f" -- {shlex.quote(file_path)}"
    return run_shell_command(cmd)


def git_log(count=10, oneline=True):
    """Get git commit log.

    Args:
        count: Number of commits to show
        oneline: If True, show one line per commit

    Returns:
        dict with success, stdout, stderr
    """
    count = int(count)
    cmd = f"git log -n {count}"
    if oneline:
        cmd += " --oneline"
    return run_shell_command(cmd)


def git_branch():
    """List git branches.

    Returns:
        dict with success, stdout, stderr
    """
    return run_shell_command("git branch -a")


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
        cmd = "git add -A"
    elif file_paths:
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        quoted_paths = " ".join(shlex.quote(p) for p in file_paths)
        cmd = f"git add {quoted_paths}"
    else:
        return {"success": False, "error": "Specify file_paths or set all_files=True"}

    result = run_shell_command(cmd)

    if result.get("returncode", 1) != 0:
        return {"success": False, "error": result.get("stderr", "Failed to stage files")}

    # Get list of staged files
    status = run_shell_command("git diff --cached --name-only")
    staged = status.get("stdout", "").strip().split("\n") if status.get("stdout") else []

    return {"success": True, "staged_files": [f for f in staged if f], "command": cmd}


def git_commit(message, amend=False):
    """Create a git commit.

    Args:
        message: Commit message
        amend: Amend the previous commit

    Returns:
        dict with success, commit_hash, message
    """
    if not message:
        return {"success": False, "error": "Commit message is required"}

    safe_message = shlex.quote(message)

    if amend:
        cmd = f"git commit --amend -m {safe_message}"
    else:
        cmd = f"git commit -m {safe_message}"

    result = run_shell_command(cmd)

    if result.get("returncode", 1) != 0:
        stderr = result.get("stderr", "")
        if "nothing to commit" in stderr or "nothing added to commit" in result.get("stdout", ""):
            return {"success": False, "error": "Nothing to commit. Stage files first."}
        return {"success": False, "error": stderr or "Commit failed"}

    hash_result = run_shell_command("git rev-parse --short HEAD")
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
        cmd = f"git checkout -- {shlex.quote(file_path)}"
        result = run_shell_command(cmd)
        return {
            "success": result.get("returncode", 1) == 0,
            "restored_file": file_path,
            "error": result.get("stderr", "") if result.get("returncode", 1) != 0 else None,
        }

    if not branch:
        return {"success": False, "error": "Branch name or file_path required"}

    if create:
        cmd = f"git checkout -b {shlex.quote(branch)}"
    else:
        cmd = f"git checkout {shlex.quote(branch)}"

    result = run_shell_command(cmd)

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
        cmd = "git stash push"
        if message:
            cmd += f" -m {shlex.quote(message)}"
    elif action == "pop":
        cmd = "git stash pop"
    elif action == "list":
        cmd = "git stash list"
    elif action == "drop":
        cmd = "git stash drop"
    else:
        return {"success": False, "error": f"Unknown action: {action}"}

    result = run_shell_command(cmd)

    return {
        "success": result.get("returncode", 1) == 0,
        "action": action,
        "stdout": result.get("stdout", ""),
        "error": result.get("stderr", "") if result.get("returncode", 1) != 0 else None,
    }
