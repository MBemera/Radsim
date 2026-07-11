"""Structural analysis of shell commands for RadSim tools.

RadSim Principle: One Function, One Purpose.

This module parses a shell command string into its structural pieces so
that callers can reason about *what a command actually does* instead of
guessing from raw characters. It powers both the shell validator and the
agent's destructive/privilege classification, so a single, well-tested
source of truth decides safety.
"""

import re
import shlex

# Commands that prefix and run another command. We look *through* these to
# find the real program, so "env sudo apt" and "nice sudo apt" are still
# recognized as privilege escalation.
WRAPPER_COMMANDS = {
    "env",
    "command",
    "exec",
    "builtin",
    "nice",
    "ionice",
    "nohup",
    "setsid",
    "stdbuf",
    "time",
    "timeout",
    "xargs",
}

# Privilege-escalation programs. Detected in any pipeline segment and under
# any wrapper or absolute path (e.g. "/usr/bin/sudo").
PRIVILEGE_COMMANDS = {"sudo", "su", "doas", "pkexec"}

# Operators that separate one command from the next. Kept as distinct shlex
# tokens by the punctuation-aware lexer below.
SEGMENT_OPERATORS = {"|", "||", "&&", ";"}

# Redirection operators. Allowed (writing files is already possible via the
# file tools), but skipped when locating a segment's command head.
REDIRECTION_OPERATORS = {">", ">>", "<", "<<", "<<<", "&>", ">&", "2>", "2>>", "1>", "1>>"}

_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def tokenize(command):
    """Split a command into tokens, keeping shell operators as their own tokens.

    Quotes are respected, so metacharacters inside quotes stay in one token.

    Returns:
        List of token strings.

    Raises:
        ValueError if the command cannot be parsed (e.g. unbalanced quotes).
    """
    lexer = shlex.shlex(command, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def split_into_segments(tokens):
    """Split a token list into command segments at pipeline/chain operators.

    Example: ["a", "|", "b", "&&", "c"] -> [["a"], ["b"], ["c"]]

    Returns:
        List of token lists, one per command segment (empty segments dropped).
    """
    segments = []
    current = []
    for token in tokens:
        if token in SEGMENT_OPERATORS:
            if current:
                segments.append(current)
            current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def basename(token):
    """Return the program name from a token, stripping any path and quotes."""
    unquoted = token.strip("'\"")
    return re.split(r"[\\/]", unquoted)[-1]


def is_env_assignment(token):
    """True if the token is a leading VAR=value assignment (as used with env)."""
    return bool(_ENV_ASSIGNMENT.match(token))


def effective_command_tokens(tokens):
    """Return a segment's tokens starting at the real program it runs.

    Skips leading redirections, wrapper commands (env, nice, ...) and their
    inline VAR=value assignments, so "env FOO=1 sudo apt" -> ["sudo", "apt"].

    Returns:
        List of tokens beginning with the program, or [] if none found.
    """
    index = 0
    while index < len(tokens):
        token = tokens[index]

        if token in REDIRECTION_OPERATORS:
            index += 2  # skip the operator and its target
            continue

        if basename(token).lower() in WRAPPER_COMMANDS:
            index += 1
            while index < len(tokens) and is_env_assignment(tokens[index]):
                index += 1
            continue

        return tokens[index:]

    return []


def effective_command_head(tokens):
    """Return the real program name a segment runs, seeing through wrappers.

    Returns the basename so absolute paths are normalized
    ("/usr/bin/sudo" -> "sudo").

    Returns:
        Lowercase program name, or "" if none could be determined.
    """
    effective = effective_command_tokens(tokens)
    return basename(effective[0]).lower() if effective else ""


def is_privilege_escalation(command):
    """True if any segment of the command escalates privilege (sudo/su/doas/pkexec).

    Sees through wrappers and absolute paths so "env sudo" and
    "/usr/bin/sudo" are caught.
    """
    try:
        tokens = tokenize(command)
    except ValueError:
        return False

    for segment in split_into_segments(tokens):
        if effective_command_head(segment) in PRIVILEGE_COMMANDS:
            return True
    return False


def is_path_traversal(token):
    """True if a token references a parent directory (path traversal).

    Blocks "../x", "x/..", a bare "..", and flag forms like "--path=../x",
    while allowing git ranges ("HEAD..main") and Go's "./..." wildcard.
    """
    if token == "..":
        return True
    if "../" in token or "..\\" in token:
        return True
    for part in re.split(r"[\\/]", token):
        if part == "..":
            return True
    return False


def _segment_is_destructive(segment, destructive_commands):
    """True if one command segment is destructive or escalates privilege."""
    effective = effective_command_tokens(segment)
    if not effective:
        return False

    head = basename(effective[0]).lower()
    if head in PRIVILEGE_COMMANDS:
        return True
    if head in destructive_commands:
        return True

    # Two-word destructive forms: "git push", "docker rm", "crontab -r".
    # Check the immediate next token and the next non-option token so both
    # subcommands (push) and destructive flags (-r) are caught.
    rest = effective[1:]
    if rest and f"{head} {basename(rest[0]).lower()}" in destructive_commands:
        return True
    non_option = [token for token in rest if not token.startswith("-")]
    if non_option and f"{head} {basename(non_option[0]).lower()}" in destructive_commands:
        return True

    return False


def is_destructive_command(command, destructive_commands):
    """True if any segment runs a destructive or privilege-escalating program.

    Centralizes destructive classification so wrapped and absolute-path forms
    (e.g. "env sudo", "/usr/bin/sudo") cannot bypass confirmation.

    Args:
        command: The raw command string.
        destructive_commands: Set of destructive program names, including
            multi-word entries like "git push".

    Returns:
        True if the command should be treated as destructive.
    """
    try:
        tokens = tokenize(command)
    except ValueError:
        return True  # Fail closed: unparseable commands require confirmation.

    normalized = {entry.lower() for entry in destructive_commands}
    return any(
        _segment_is_destructive(segment, normalized)
        for segment in split_into_segments(tokens)
    )
