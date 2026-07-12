"""Path and command validation for RadSim tools.

RadSim Principle: Explicit Safety Checks
"""

import fnmatch
from pathlib import Path
from threading import RLock

from ..terminal import is_unsafe_terminal_character
from . import command_analysis
from .constants import MAX_COMMAND_SIZE, PROTECTED_PATTERNS

_PATH_CACHE = {
    "cwd": None,
    "resolved_cwd": None,
}
_PATH_CACHE_LOCK = RLock()


def _get_resolved_cwd():
    """Return the resolved current working directory with cache invalidation."""
    with _PATH_CACHE_LOCK:
        current_cwd = Path.cwd()
        if _PATH_CACHE["cwd"] != current_cwd:
            _PATH_CACHE["cwd"] = current_cwd
            _PATH_CACHE["resolved_cwd"] = current_cwd.resolve()
        return _PATH_CACHE["resolved_cwd"]


def clear_path_validation_cache():
    """Clear cached current working directory state."""
    with _PATH_CACHE_LOCK:
        _PATH_CACHE["cwd"] = None
        _PATH_CACHE["resolved_cwd"] = None


def validate_path(file_path, allow_outside=False):
    """Ensure path is safe and within project directory.

    Args:
        file_path: The path to validate
        allow_outside: If True, allows paths outside CWD (requires confirmation)

    Returns:
        Tuple of (is_safe, resolved_path, error_message)
    """
    if file_path is None:
        return False, None, "Path cannot be empty"

    try:
        if not isinstance(file_path, str):
            file_path = str(file_path)

        if not file_path.strip():
            return False, None, "Path cannot be empty"

        path = Path(file_path).resolve()
        cwd = _get_resolved_cwd()

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
    """Validate a shell command using structure-aware rules.

    Legitimate shell structure is allowed so the agent can run real
    commands across platforms: pipelines (``|``), conditional chaining
    (``&&``, ``||``), sequencing (``;``), file redirection (``>``), globs,
    git ranges (``HEAD..main``) and Go wildcards (``./...``).

    Genuinely dangerous constructs are still rejected:
    - command/process substitution ( ``$(...)`` , backticks, ``<(...)`` )
    - background execution ( ``&`` ) and bare subshell grouping
    - path traversal ( ``../`` ) in any token
    - catastrophic commands, enforced per pipeline segment by the policy

    Args:
        command: Command string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not command:
        return False, "Command cannot be empty"

    if not isinstance(command, str):
        return False, "Command must be a string"

    if not command.strip():
        return False, "Command cannot be empty"

    if len(command) > MAX_COMMAND_SIZE:
        return False, f"Command exceeds the {MAX_COMMAND_SIZE}-character limit"

    # Phase 1: reject dangerous syntax on the raw string (catches
    # substitution even inside quotes, before we parse).
    is_safe, rejection_reason = _check_for_dangerous_characters(command)
    if not is_safe:
        return False, rejection_reason

    # Phase 2: parse into structural tokens.
    try:
        tokens = command_analysis.tokenize(command)
    except ValueError:
        return False, "Invalid command format"

    if not tokens:
        return False, "Empty command"

    is_safe, rejection_reason = _check_tokens(tokens)
    if not is_safe:
        return False, rejection_reason

    # Phase 3: enforce the command policy per segment. Fail closed if the
    # policy cannot render a decision.
    is_allowed, reason = _check_command_policy(command)
    if not is_allowed:
        return False, reason

    return True, None


def has_terminal_control_character(value):
    """Return True when text contains terminal or bidi control characters."""
    if not isinstance(value, str):
        return False
    return any(is_unsafe_terminal_character(character) for character in value)


def _check_for_dangerous_characters(command):
    """Reject raw-string constructs that hide or inject commands.

    Returns:
        Tuple of (is_safe, rejection_reason). is_safe is True when clean.
    """
    if "\x00" in command:
        return False, "Null bytes are forbidden in commands"

    if "\n" in command or "\r" in command:
        return False, "Newlines are forbidden in commands"

    if has_terminal_control_character(command):
        return False, "Terminal control characters are forbidden in commands"

    if "`" in command:
        return False, "Backticks are forbidden in commands (command substitution)"

    if "$" in command:
        return False, "Dollar signs are forbidden in commands (variable/command substitution)"

    if "<(" in command or ">(" in command:
        return False, "Process substitution ('<(...)' / '>(...)') is forbidden in commands"

    return True, None


def _check_tokens(tokens):
    """Reject unsupported structure and path traversal in parsed tokens.

    Returns:
        Tuple of (is_safe, rejection_reason). is_safe is True when clean.
    """
    for token in tokens:
        if token == "&":
            return False, "Background execution ('&') is forbidden in commands"
        if token in ("(", ")"):
            return False, "Subshell grouping ('(...)') is forbidden in commands"
        if command_analysis.is_path_traversal(token):
            return False, "Path traversal ('..') is forbidden in command"

    for segment in command_analysis.split_into_segments(tokens):
        if command_analysis.has_shell_control_syntax(segment):
            return False, "Shell control structures are forbidden in commands"
        if command_analysis.has_ambiguous_command_head(segment):
            return False, "Shell expansion in an executable name is forbidden"
        if command_analysis.has_unanalyzable_execution(segment):
            return False, "Nested shells and inline interpreter code are forbidden"

    if any(command_analysis.has_brace_expansion(token) for token in tokens):
        return False, "Shell brace expansion is forbidden in commands"

    return True, None


def _check_command_policy(command):
    """Apply the whitelist/blocklist policy, failing closed on any error.

    If the policy engine cannot render a decision the command is blocked:
    a broken configuration must never widen what the agent may run.

    Returns:
        Tuple of (is_allowed, reason). reason is None when allowed.
    """
    try:
        from .command_policy import get_command_policy

        return get_command_policy().is_command_allowed(command)
    except Exception:
        return False, "Command policy could not be evaluated; blocked for safety"
