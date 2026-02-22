"""Shell execution for RadSim tools.

RadSim Principle: Explicit Over Implicit
"""

import os
import subprocess

from .constants import MAX_ERROR_OUTPUT_SIZE, MAX_OUTPUT_SIZE
from .validation import validate_shell_command


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

    try:
        # Determine shell based on platform
        if os.name == "nt":  # Windows
            shell_cmd = ["powershell", "-NoProfile", "-Command", command]
        else:  # Unix/Mac
            shell_cmd = ["bash", "-c", command]

        cwd = working_dir or os.getcwd()

        result = subprocess.run(shell_cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)

        # Truncate output if too large
        stdout = result.stdout
        stderr = result.stderr

        if len(stdout) > MAX_OUTPUT_SIZE:
            stdout = stdout[:MAX_OUTPUT_SIZE] + "\n... [Output truncated]"
        if len(stderr) > MAX_ERROR_OUTPUT_SIZE:
            stderr = stderr[:MAX_ERROR_OUTPUT_SIZE] + "\n... [Error output truncated]"

        return {
            "success": result.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout} seconds"}
    except Exception as error:
        return {"success": False, "error": str(error)}
