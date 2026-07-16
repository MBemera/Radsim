"""Path and command validation for RadSim tools.

RadSim Principle: Explicit Safety Checks
"""

import fnmatch
import os
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


def is_protected_path(file_path, resolved_path=None):
    """Check if a file path matches protected write patterns.

    Checks the caller-supplied string and, when given, the canonical
    resolved path. Passing the resolved path is what closes the symlink
    bypass (R-03): a benign-looking name that resolves to a protected
    target (``safe.txt`` → ``.env``) is still caught.

    Args:
        file_path: Path to check (as supplied by the caller)
        resolved_path: Optional canonical/resolved path to also check

    Returns:
        Tuple of (is_protected, reason)
    """
    candidates = [str(file_path)]
    if resolved_path is not None:
        candidates.append(str(resolved_path))

    for candidate in candidates:
        path_lower = candidate.lower()
        for pattern in PROTECTED_PATTERNS:
            if fnmatch.fnmatch(path_lower, f"*{pattern}*"):
                return True, f"Protected file pattern: {pattern}"
    return False, None


# Files whose contents are secrets. Reading any of these hands credentials to
# the model provider, so a read must be confirmed against the *canonical* path
# (R-02). Matching is on the basename so it is precise and low-noise — a source
# file such as tokenizer.py is not a secret, but .env / id_rsa / *.pem are.
SECRET_READ_FILE_GLOBS = (
    ".env",
    ".env.*",
    "*.env",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.keystore",
    "*.jks",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "credentials",
    "credentials.json",
    "secrets.json",
    "service-account*.json",
)

# Directory names that only ever hold credentials or private key material.
SECRET_READ_DIR_NAMES = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
    ".gcloud",
)


def _extra_secret_read_globs():
    """Return any user-configured secret-read globs, or an empty tuple.

    Users can widen the protected-read set through the agent config key
    ``security.protected_read_patterns`` without editing source.
    """
    try:
        from ..agent_config import get_agent_config_manager

        extra = get_agent_config_manager().get("security.protected_read_patterns", [])
        if isinstance(extra, list):
            return tuple(str(item) for item in extra if item)
    except Exception:
        pass
    return ()


def is_secret_read_path(file_path, resolved_path=None):
    """Return (is_secret, reason) when a path targets secret material.

    Checks both the supplied path and the canonical resolved path so a
    symlink or case-variant pointing at a secret is still caught. Content
    read from these paths is provider-visible, so the agent must confirm
    the exact canonical path before reading.
    """
    candidates = []
    if resolved_path is not None:
        candidates.append(Path(str(resolved_path)))
    candidates.append(Path(str(file_path)))

    file_globs = SECRET_READ_FILE_GLOBS + _extra_secret_read_globs()

    for path in candidates:
        name = path.name.lower()
        for glob in file_globs:
            if fnmatch.fnmatch(name, glob.lower()):
                return True, f"secret file ({path.name})"
        parts_lower = {part.lower() for part in path.parts}
        for secret_dir in SECRET_READ_DIR_NAMES:
            if secret_dir in parts_lower:
                return True, f"secret directory ({secret_dir}/)"
    return False, None


def contains_symlink(file_path):
    """Return (has_symlink, offending_path) when a write target is a symlink.

    ``validate_path`` resolves the path and confirms containment, but a
    write must not follow a symlink: a benign-looking name (``safe.txt``)
    can be a repository-controlled link onto a protected or out-of-tree
    file (``.env``). This checks the target itself and every ancestor that
    lies strictly inside the project directory; the project root and
    anything above it are not checked, so a project cloned under a
    symlinked path still works.

    Returns:
        Tuple of (has_symlink, offending_path). has_symlink is False on
        any error so callers keep their existing validate_path guarantees.
    """
    try:
        cwd = str(_get_resolved_cwd())
        if os.path.isabs(file_path):
            target = os.path.normpath(str(file_path))
        else:
            target = os.path.normpath(os.path.join(cwd, str(file_path)))

        prefix = cwd + os.sep
        current = target
        while current != cwd and current.startswith(prefix):
            if os.path.islink(current):
                return True, current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return False, None
    except Exception:
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
