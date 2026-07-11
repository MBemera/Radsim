"""Shell execution for RadSim tools.

RadSim Principle: Explicit Over Implicit
"""

import os
import subprocess

from .constants import MAX_ERROR_OUTPUT_SIZE, MAX_OUTPUT_SIZE
from .environment import build_child_environment
from .validation import validate_shell_command


def _resolve_working_dir(working_dir):
    """Validate the requested working directory.

    Returns:
        Tuple of (cwd, error). cwd is the directory to run in; error is a
        message when the directory is invalid.
    """
    if working_dir is None:
        return os.getcwd(), None

    if not isinstance(working_dir, str) or not working_dir.strip():
        return None, "Working directory must be a non-empty path"

    if not os.path.isdir(working_dir):
        return None, f"Working directory does not exist: {working_dir}"

    return working_dir, None


def _truncate(text, limit, label):
    """Return text capped at limit, appending a truncation notice if cut."""
    if len(text) > limit:
        return text[:limit] + f"\n... [{label} truncated]"
    return text


def run_shell_command(command, timeout=120, working_dir=None):
    """Execute a shell command.

    Args:
        command: Command to execute
        timeout: Timeout in seconds (default: 120)
        working_dir: Working directory (default: current)

    Returns:
        dict with success, stdout, stderr, returncode
    """
    is_valid, error = validate_shell_command(command)
    if not is_valid:
        return {"success": False, "error": error}

    cwd, error = _resolve_working_dir(working_dir)
    if error:
        return {"success": False, "error": error}

    try:
        if os.name == "nt":  # Windows
            shell_cmd = ["powershell", "-NoProfile", "-Command", command]
        else:  # Unix/Mac
            shell_cmd = ["bash", "-c", command]

        # Isolate the child into its own process group/session so RadSim's
        # terminal signals don't leak into it. POSIX-only.
        run_kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "cwd": cwd,
            "env": build_child_environment(),
        }
        if os.name != "nt":
            run_kwargs["start_new_session"] = True

        result = subprocess.run(shell_cmd, **run_kwargs)

        return {
            "success": result.returncode == 0,
            "stdout": _truncate(result.stdout, MAX_OUTPUT_SIZE, "Output"),
            "stderr": _truncate(result.stderr, MAX_ERROR_OUTPUT_SIZE, "Error output"),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout} seconds"}
    except Exception as error:
        return {"success": False, "error": str(error)}
