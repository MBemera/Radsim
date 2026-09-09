"""Git operations for RadSim tools.

RadSim Principle: Standard Patterns Only
"""

from pathlib import Path

from .sandbox import wrap_shell_arguments
from .shell import format_process_command, run_process
from .validation import is_secret_read_path


def _run_git(arguments, working_dir=None):
    """Keep explicit Git directories inside the session workspace."""
    if working_dir is not None:
        try:
            directory = Path(working_dir).resolve()
            if not directory.is_dir() or not directory.is_relative_to(Path.cwd().resolve()):
                return {"success": False, "error": "Git directory must be inside the workspace"}
        except (TypeError, ValueError, OSError, RuntimeError):
            return {"success": False, "error": "Invalid Git working directory"}
    try:
        arguments = wrap_shell_arguments(arguments, str(Path(working_dir or Path.cwd()).resolve()))
    except RuntimeError as error:
        return {"success": False, "blocked": True, "error": str(error)}
    result = run_process(arguments, working_dir=working_dir)
    result["working_dir"] = str(Path(working_dir or Path.cwd()).resolve())
    return result


def validate_stage_paths(file_paths, working_dir=None):
    """Require literal files in one repository for automatic staging."""
    directory = Path(working_dir or Path.cwd()).resolve()
    if not directory.is_relative_to(Path.cwd().resolve()):
        return False
    repository = next(
        (path for path in (directory, *directory.parents) if (path / ".git").exists()), None
    )
    if repository is None:
        return False
    for name in file_paths:
        if not isinstance(name, str) or not name or any(char in name for char in ":*?[]\x00"):
            return False
        target = (directory / name).resolve()
        if not target.is_relative_to(directory) or target.is_dir():
            return False
        if ".git" in target.parts or is_secret_read_path(name, str(target))[0]:
            return False
        owner = next((path for path in target.parents if (path / ".git").exists()), None)
        if owner != repository:
            return False
    return True


def validate_commit_index(working_dir, allowed_files):
    """Check staged metadata before automatic commit, without reading contents."""
    result = _run_git(["git", "diff", "--cached", "--name-only", "-z"], working_dir)
    if not result.get("success"):
        return False
    paths = [name for name in result.get("stdout", "").split("\0") if name]
    root = _run_git(["git", "rev-parse", "--show-toplevel"], working_dir)
    if not root.get("success") or not paths:
        return False
    repository = Path(root.get("stdout", "").strip())
    staged_files = {str((repository / name).resolve()) for name in paths}
    return staged_files.issubset(allowed_files) and validate_stage_paths(paths, repository)


# =============================================================================
# GIT READ OPERATIONS
# =============================================================================


def git_status(working_dir=None):
    """Get git repository status."""
    return _run_git(
        ["git", "-c", "core.fsmonitor=false", "status", "--porcelain", "-b"],
        working_dir=working_dir,
    )


def git_diff(staged=False, file_path=None, working_dir=None):
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
    return _run_git(arguments, working_dir=working_dir)


def git_log(count=10, oneline=True, working_dir=None):
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
    return _run_git(arguments, working_dir=working_dir)


def git_branch(working_dir=None):
    """List git branches."""
    return _run_git(["git", "branch", "-a"], working_dir=working_dir)


# =============================================================================
# GIT WRITE OPERATIONS
# =============================================================================


def git_add(file_paths=None, all_files=False, working_dir=None):
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

    result = _run_git(arguments, working_dir=working_dir)

    if result.get("returncode", 1) != 0:
        return {
            "success": False,
            "error": result.get("stderr") or result.get("error") or "Failed to stage files",
        }

    # Get list of staged files
    status = _run_git(["git", "diff", "--cached", "--name-only"], working_dir=working_dir)
    staged = status.get("stdout", "").strip().split("\n") if status.get("stdout") else []

    return {
        "success": True,
        "staged_files": [file for file in staged if file],
        "command": format_process_command(arguments),
    }


def git_commit(message, amend=False, working_dir=None):
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

    result = _run_git(arguments, working_dir=working_dir)

    if result.get("returncode", 1) != 0:
        stderr = result.get("stderr", "")
        if "nothing to commit" in stderr or "nothing added to commit" in result.get("stdout", ""):
            return {"success": False, "error": "Nothing to commit. Stage files first."}
        return {"success": False, "error": stderr or result.get("error") or "Commit failed"}

    # Get the commit hash
    hash_result = _run_git(["git", "rev-parse", "--short", "HEAD"], working_dir=working_dir)
    commit_hash = hash_result.get("stdout", "").strip()

    return {"success": True, "commit_hash": commit_hash, "message": message, "amend": amend}


def git_checkout(branch=None, create=False, file_path=None, working_dir=None):
    """Switch branches or restore files.

    Args:
        branch: Branch name to checkout
        create: Create new branch if True
        file_path: Restore specific file from HEAD

    Returns:
        dict with success, branch or file restored
    """
    if file_path:
        result = _run_git(["git", "checkout", "--", str(file_path)], working_dir=working_dir)
        return {
            "success": result.get("returncode", 1) == 0,
            "restored_file": file_path,
            "error": (result.get("stderr") or result.get("error") or "Git operation failed")
            if result.get("returncode", 1) != 0
            else None,
        }

    if not branch:
        return {"success": False, "error": "Branch name or file_path required"}

    if not isinstance(branch, str) or branch.startswith("-") or "\x00" in branch:
        return {"success": False, "error": "Invalid branch name"}

    arguments = ["git", "checkout", *(["-b"] if create else []), branch]
    result = _run_git(arguments, working_dir=working_dir)

    return {
        "success": result.get("returncode", 1) == 0,
        "branch": branch,
        "created": create,
        "error": (result.get("stderr") or result.get("error") or "Git operation failed")
        if result.get("returncode", 1) != 0
        else None,
    }


def git_stash(action="push", message=None, working_dir=None):
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

    result = _run_git(arguments, working_dir=working_dir)

    return {
        "success": result.get("returncode", 1) == 0,
        "action": action,
        "stdout": result.get("stdout", ""),
        "error": (result.get("stderr") or result.get("error") or "Git operation failed")
        if result.get("returncode", 1) != 0
        else None,
    }
