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
from pathlib import PurePosixPath

# Commands that prefix and run another command. We look *through* these to
# find the real program, so "env sudo apt" and "nice sudo apt" are still
# recognized as privilege escalation.
WRAPPER_COMMANDS = {
    "busybox",
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
    "toybox",
}

WRAPPER_VALUE_OPTIONS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "--class", "-n", "--classdata", "-p", "--pid", "-P", "--pgid", "-u", "--uid"},
    "stdbuf": {"-i", "--input", "-o", "--output", "-e", "--error"},
    "time": {"-f", "--format", "-o", "--output"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "xargs": {
        "-a", "--arg-file", "-E", "--eof", "-I", "--replace",
        "-L", "--max-lines", "-n", "--max-args", "-P", "--max-procs",
        "-s", "--max-chars",
    },
}

# Shell keywords that can precede a command inside a segment. Skipped like
# wrappers so "while true; do rm x; done" and "{ rm x ; }" still expose the
# real program to classification. Matched literally: bash only treats these
# as keywords when unquoted.
SHELL_KEYWORDS = {
    "case",
    "coproc",
    "esac",
    "if",
    "then",
    "elif",
    "else",
    "fi",
    "while",
    "until",
    "do",
    "done",
    "for",
    "function",
    "in",
    "select",
    "!",
    "{",
    "}",
}

# Privilege-escalation programs. Detected in any pipeline segment and under
# any wrapper or absolute path (e.g. "/usr/bin/sudo").
PRIVILEGE_COMMANDS = {"sudo", "su", "doas", "pkexec"}

# Operators that separate one command from the next. Kept as distinct shlex
# tokens by the punctuation-aware lexer below. "|&" pipes stderr too and
# still starts a new command.
SEGMENT_OPERATORS = {"|", "||", "&&", ";", "|&"}

# Redirection operators. Allowed (writing files is already possible via the
# file tools), but skipped when locating a segment's command head.
OUTPUT_REDIRECTION_OPERATORS = {">", ">>", ">|", "&>", "&>>"}
REDIRECTION_OPERATORS = OUTPUT_REDIRECTION_OPERATORS | {
    "<",
    "<<",
    "<<-",
    "<<<",
    "<>",
    "<&",
    ">&",
}

_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Numeric wrapper arguments such as timeout durations ("timeout 5", "timeout 10s").
_WRAPPER_DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")
_PYTHON_PROGRAM = re.compile(r"^(python|pythonw)(\d+(\.\d+)*)?$")
_PRIVILEGE_VALUE_OPTIONS = {
    "-a", "-C", "--close-from", "-D", "-g", "--group", "-h", "--host",
    "-p", "--prompt", "-R", "-r", "--role", "-T", "-t", "--type",
    "-u", "--user", "--chdir", "--chroot", "--command-timeout",
}

NESTED_SHELL_PROGRAMS = {
    "bash",
    "cmd",
    "dash",
    "fish",
    "ksh",
    "powershell",
    "powershell.exe",
    "pwsh",
    "sh",
    "zsh",
}

POWERSHELL_DESTRUCTIVE_COMMANDS = {
    "clear-content",
    "clear-disk",
    "format-volume",
    "initialize-disk",
    "invoke-expression",
    "move-item",
    "remove-item",
    "restart-computer",
    "set-acl",
    "start-process",
    "stop-computer",
}


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


def _redirection_width(tokens, index):
    """Return the number of tokens occupied by a redirection at index."""
    if tokens[index] in REDIRECTION_OPERATORS:
        return 2
    if tokens[index].isdigit() and index + 1 < len(tokens):
        if tokens[index + 1] in REDIRECTION_OPERATORS:
            return 3
    return 0


def has_output_redirection(tokens):
    """Return True when parsed tokens redirect stdout or stderr to a target."""
    for index, token in enumerate(tokens):
        operator = token
        if token.isdigit() and index + 1 < len(tokens):
            operator = tokens[index + 1]
        if operator in OUTPUT_REDIRECTION_OPERATORS or operator == ">&":
            return True
    return False


def shell_resolved_forms(token):
    """Return the strings the shell could resolve this token to.

    Bash removes quotes and backslash escapes before using a word, so
    ``su"do"`` and ``su\\do`` both run sudo, and ``cd ".."`` changes to the
    parent directory. Classification checks every form so quoting tricks
    cannot hide the real value.
    """
    unquoted = token.replace('"', "").replace("'", "")
    return {unquoted, unquoted.replace("\\", "")}


def program_names(token):
    """Return every program name the shell could resolve this token to.

    Strips paths (both separators, so "/usr/bin/sudo" and "C:\\bin\\sudo"
    normalize) and quoting tricks. Lowercased for set comparison.
    """
    names = set()
    for form in shell_resolved_forms(token):
        names.add(re.split(r"[\\/]", form)[-1].lower())
    return names


def basename(token):
    """Return the most likely program name from a token, for display use.

    Security checks should use program_names(), which returns every
    resolvable reading instead of a single guess.
    """
    unquoted = token.replace('"', "").replace("'", "")
    return re.split(r"[\\/]", unquoted)[-1]


def is_env_assignment(token):
    """True if the token is a leading VAR=value assignment (as used with env)."""
    return bool(_ENV_ASSIGNMENT.match(token))


def _option_consumes_value(wrapper, token):
    """Return True when this exact wrapper option consumes the next token."""
    return token in WRAPPER_VALUE_OPTIONS.get(wrapper, set())


def _skip_wrapper_arguments(tokens, index, wrapper):
    """Return the index of the command invoked by one wrapper."""
    while index < len(tokens):
        redirection_width = _redirection_width(tokens, index)
        if redirection_width:
            index += redirection_width
            continue

        token = tokens[index]
        if token == "--":
            return index + 1
        if wrapper == "env" and is_env_assignment(token):
            index += 1
            continue
        if wrapper == "timeout" and _WRAPPER_DURATION.match(token):
            index += 1
            continue
        if token.startswith("-"):
            index += 2 if _option_consumes_value(wrapper, token) else 1
            continue
        return index
    return index


def _skip_command_prefix(tokens, index):
    """Skip assignments, redirections, and shell keywords before a command."""
    while index < len(tokens):
        redirection_width = _redirection_width(tokens, index)
        if redirection_width:
            index += redirection_width
            continue
        if is_env_assignment(tokens[index]) or tokens[index] in SHELL_KEYWORDS:
            index += 1
            continue
        break
    return index


def effective_command_tokens(tokens):
    """Return a segment's tokens starting at the real program it runs.

    Skips leading redirections, shell keywords (do, if, {, ...), wrapper
    commands (env, nice, timeout, ...) and the arguments those wrappers
    consume, so "env FOO=1 sudo apt", "nice -n 10 sudo apt" and
    "do rm file" all resolve to the real program.

    Returns:
        List of tokens beginning with the program, or [] if none found.
    """
    index = 0
    while index < len(tokens):
        index = _skip_command_prefix(tokens, index)
        if index >= len(tokens):
            return []

        token = tokens[index]
        if program_names(token) & WRAPPER_COMMANDS:
            wrapper = sorted(program_names(token) & WRAPPER_COMMANDS)[0]
            index += 1
            index = _skip_wrapper_arguments(tokens, index, wrapper)
            continue

        return tokens[index:]

    return []


def initial_command_names(tokens):
    """Return names for the first executable token without unwrapping wrappers."""
    index = _skip_command_prefix(tokens, 0)
    if index >= len(tokens):
        return set()
    return program_names(tokens[index])


def has_shell_control_syntax(segment):
    """Return True when a segment begins with unsupported shell grammar."""
    index = 0
    while index < len(segment):
        redirection_width = _redirection_width(segment, index)
        if redirection_width:
            index += redirection_width
            continue
        if is_env_assignment(segment[index]):
            index += 1
            continue
        return segment[index] in SHELL_KEYWORDS
    return False


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

    Sees through wrappers, absolute paths, and quoting tricks so "env sudo",
    "/usr/bin/sudo" and 'su"do"' are all caught.
    """
    try:
        tokens = tokenize(command)
    except ValueError:
        return False

    for segment in split_into_segments(tokens):
        effective = effective_command_tokens(segment)
        if effective and program_names(effective[0]) & PRIVILEGE_COMMANDS:
            return True
    return False


def is_path_traversal(token):
    """True if a token references a parent directory (path traversal).

    Blocks "../x", "x/..", a bare "..", quoted forms like '".."', and flag
    forms like "--path=../x" or "--path=..", while allowing git ranges
    ("HEAD..main") and Go's "./..." wildcard.
    """
    for form in shell_resolved_forms(token):
        if form == "..":
            return True
        if "../" in form or "..\\" in form:
            return True
        for part in re.split(r"[\\/=]", form):
            if part == "..":
                return True
    return False


def has_ambiguous_command_head(segment):
    """Return True when shell expansion could change the executable name."""
    effective = effective_command_tokens(segment)
    if not effective:
        return False
    return any(character in effective[0] for character in "*?[{")


def has_brace_expansion(token):
    """Return True when a token contains active Bash brace expansion."""
    unquoted = []
    quote = None
    escaped = False
    for character in token:
        if escaped:
            escaped = False
            continue
        if quote:
            if character == quote:
                quote = None
            continue
        if character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        unquoted.append(character)

    visible_text = "".join(unquoted)
    return bool(re.search(r"\{[^{}]*(?:,|\.\.)[^{}]*\}", visible_text))


def _has_inline_code_flag(head_names, tokens):
    """Return True for interpreter flags that execute an inline string."""
    lowered = [token.lower() for token in tokens]
    if any(_PYTHON_PROGRAM.match(name) for name in head_names):
        return any(
            token.startswith("-") and not token.startswith("--") and "c" in token[1:]
            for token in lowered
        )
    if head_names & {"py"}:
        return any(token.startswith("-c") for token in lowered)
    if head_names & {"node", "nodejs"}:
        return any(
            token.startswith(("-e", "--eval=", "-p", "--print="))
            or token in {"--eval", "--print"}
            for token in lowered
        )
    if head_names & {"perl", "ruby"}:
        return any(token.startswith("-e") for token in lowered)
    return False


def _wrapper_hides_command(segment):
    """Return True when a wrapper receives an opaque command string."""
    index = _skip_command_prefix(segment, 0)
    if index >= len(segment):
        return False
    if not program_names(segment[index]) & {"env"}:
        return False

    index += 1
    while index < len(segment):
        token = segment[index]
        forms = shell_resolved_forms(token)
        if any(form.startswith("-S") for form in forms):
            return True
        if any(form.lower().startswith("--split-string") for form in forms):
            return True
        if token == "--" or not token.startswith("-"):
            return False
        index += 2 if _option_consumes_value("env", token) else 1
    return False


def _privilege_opens_shell(effective):
    """Return True when privilege options request an interactive shell."""
    head_names = program_names(effective[0])
    if not head_names & {"sudo", "doas"}:
        return False

    index = 1
    while index < len(effective):
        token = effective[index]
        lowered = token.lower()
        if lowered in {"-s", "-i", "--shell", "--login"}:
            return True
        if _short_privilege_options_open_shell(token):
            return True
        if token == "--" or not token.startswith("-"):
            return False
        index += 2 if token in _PRIVILEGE_VALUE_OPTIONS else 1
    return False


def _short_privilege_options_open_shell(token):
    """Return True when a short-option cluster requests a shell."""
    if not token.startswith("-") or token.startswith("--"):
        return False
    for option in token[1:]:
        if option in {"i", "s"}:
            return True
        if f"-{option}" in _PRIVILEGE_VALUE_OPTIONS:
            return False
    return False


def has_unanalyzable_execution(segment):
    """Return True when a segment delegates execution to hidden code."""
    if _wrapper_hides_command(segment):
        return True

    effective = effective_command_tokens(segment)
    if not effective:
        return False

    head_names = program_names(effective[0])
    if head_names & NESTED_SHELL_PROGRAMS or head_names & {"su"}:
        return True
    if _privilege_opens_shell(effective):
        return True
    if _has_inline_code_flag(head_names, effective[1:]):
        return True

    privileged = _privileged_command_tokens(effective)
    return bool(privileged and has_unanalyzable_execution(privileged))


def _segment_is_destructive(segment, destructive_commands):
    """True if one command segment is destructive or escalates privilege."""
    if has_output_redirection(segment):
        return True

    initial_names = initial_command_names(segment)
    if initial_names & WRAPPER_COMMANDS:
        return True

    effective = effective_command_tokens(segment)
    if not effective:
        return False

    head_names = program_names(effective[0])
    if head_names & PRIVILEGE_COMMANDS:
        return True
    if head_names & destructive_commands:
        return True
    if head_names & POWERSHELL_DESTRUCTIVE_COMMANDS:
        return True
    if head_names & NESTED_SHELL_PROGRAMS or _has_inline_code_flag(head_names, effective[1:]):
        return True

    # Two-word destructive forms: "git push", "docker rm", "crontab -r",
    # "find -delete". Every later token is checked so option reordering
    # ("git -C /repo push", "crontab -u user -r") cannot dodge the match.
    rest_names = set()
    for token in effective[1:]:
        rest_names |= program_names(token)
    return any(
        f"{head} {name}" in destructive_commands
        for head in head_names
        for name in rest_names
    )


def _has_rm_destruction(head_names, arguments):
    """Return True for recursive forced deletion of a root or home target."""
    if not head_names & {"rm", "remove-item", "ri", "del", "erase"}:
        return False
    option_tokens = [
        form.lower()
        for token in arguments
        for form in shell_resolved_forms(token)
        if _is_delete_option(form)
    ]
    recursive = _delete_option_enabled(option_tokens, "r", "recursive", {"/r", "/s"})
    forced = _delete_option_enabled(option_tokens, "f", "force", {"/f", "/q"})
    targets = [token for token in arguments if token != "--" and not _is_delete_option(token)]
    return recursive and forced and any(_is_root_or_home_target(target) for target in targets)


def _is_delete_option(token):
    """Return True for POSIX or cmd/PowerShell deletion options."""
    if token.startswith("-"):
        return True
    return token.lower() in {"/f", "/q", "/r", "/s"}


def _delete_option_enabled(options, short_name, long_name, windows_names):
    """Return True when deletion options enable one requested behavior."""
    for option in options:
        if option in windows_names or option == f"--{long_name}":
            return True
        if option.startswith("-") and not option.startswith("--"):
            if short_name in option[1:]:
                return True
    return False


def _is_root_or_home_target(token):
    """Return True for POSIX roots, home expansions, or Windows drive roots."""
    return any(_is_root_or_home_value(form) for form in shell_resolved_forms(token))


def _is_root_or_home_value(value):
    """Evaluate one shell-resolved path form for root or home targeting."""
    value = value.strip().replace("\\", "/")
    if _is_root_contents_glob_value(value):
        return True
    if value.startswith("~"):
        home_name, separator, suffix = value.partition("/")
        if home_name in {"~+", "~-"}:
            return False
        if not separator:
            return True
        return str(PurePosixPath(f"/{suffix}")) == "/"
    if re.fullmatch(r"[a-zA-Z]:/*", value):
        return True
    value = re.sub(r"^/{2,}", "/", value)
    return str(PurePosixPath(value)) in {"/", "/*"}


def _is_root_contents_glob_value(value):
    """Return True when a glob targets entries directly under a root."""
    path_from_root = None
    if re.match(r"^[a-zA-Z]:/", value):
        path_from_root = value[3:]
    elif value.startswith("~"):
        home_name, separator, suffix = value.partition("/")
        if separator and home_name not in {"~+", "~-"}:
            path_from_root = suffix
    elif value.startswith("/"):
        path_from_root = value.lstrip("/")

    if path_from_root is None:
        return False
    path_parts = PurePosixPath(f"/{path_from_root}").parts[1:]
    if not path_parts:
        return False
    first_part = path_parts[0]
    return "*" in first_part or "?" in first_part or bool(re.search(r"\[[^]]+\]", first_part))


def _is_device_target(token):
    """Return True for device nodes where writing may destroy a disk."""
    return any(_is_device_value(form) for form in shell_resolved_forms(token))


def _is_device_value(value):
    """Evaluate one shell-resolved path form for device targeting."""
    value = value.lower().replace("\\", "/")
    if value.startswith("//./physicaldrive"):
        return True
    if not value.startswith("/dev/"):
        return False
    safe_devices = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/zero"}
    return value not in safe_devices and not value.startswith("/dev/fd/")


def _privileged_command_tokens(effective):
    """Return argv invoked through sudo, doas, or pkexec."""
    if not program_names(effective[0]) & PRIVILEGE_COMMANDS:
        return []
    index = 1
    while index < len(effective):
        token = effective[index]
        if token == "--":
            return effective[index + 1:]
        if token in _PRIVILEGE_VALUE_OPTIONS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return effective[index:]
    return []


def _redirection_targets(tokens):
    """Yield targets of output redirections."""
    for index, token in enumerate(tokens):
        operator_index = index
        if token.isdigit() and index + 1 < len(tokens):
            operator_index = index + 1
        if tokens[operator_index] not in OUTPUT_REDIRECTION_OPERATORS | {">&"}:
            continue
        target_index = operator_index + 1
        if target_index < len(tokens):
            yield tokens[target_index]


def _has_root_permission_destruction(head_names, arguments):
    """Return True for recursive permission or ownership changes at root."""
    if not head_names & {"chmod", "chown"}:
        return False
    recursive = any(
        token == "--recursive" or (token.startswith("-") and "r" in token[1:].lower())
        for token in arguments
    )
    if not recursive or not any(_is_root_or_home_target(token) for token in arguments):
        return False
    if "chown" in head_names:
        return True
    return any(token.lstrip("0") == "777" for token in arguments)


def _moves_root_to_null(head_names, arguments):
    """Return True for moving a filesystem root into the null device."""
    if not head_names & {"mv", "move-item"}:
        return False
    values = [token for token in arguments if not token.startswith("-")]
    if len(values) < 2:
        return False
    return _is_root_or_home_target(values[-2]) and values[-1].lower() in {
        "/dev/null",
        "nul",
    }


def _segment_is_catastrophic(segment):
    """Return True for structurally recognizable catastrophic operations."""
    if any(has_brace_expansion(token) for token in segment):
        return True
    if has_unanalyzable_execution(segment):
        return True

    effective = effective_command_tokens(segment)
    if not effective or has_ambiguous_command_head(segment):
        return has_ambiguous_command_head(segment)

    head_names = program_names(effective[0])
    arguments = effective[1:]
    privileged = _privileged_command_tokens(effective)
    if privileged and _segment_is_catastrophic(privileged):
        return True
    if _has_rm_destruction(head_names, arguments):
        return True
    if _has_root_permission_destruction(head_names, arguments):
        return True
    if _moves_root_to_null(head_names, arguments):
        return True
    if any(name.startswith("mkfs") for name in head_names) or head_names & {"wipefs", "format-volume", "clear-disk", "initialize-disk"}:
        return True
    if head_names & {"dd", "tee"} and any(_is_device_target(token.split("=", 1)[-1]) for token in arguments):
        return True
    return any(_is_device_target(target) for target in _redirection_targets(segment))


def is_catastrophic_command(command):
    """Return True when a command must be blocked without an override."""
    try:
        segments = split_into_segments(tokenize(command))
    except ValueError:
        return True
    return any(_segment_is_catastrophic(segment) for segment in segments)


def is_destructive_command(command, destructive_commands):
    """True if any segment runs a destructive or privilege-escalating program.

    Centralizes destructive classification so wrapped, quoted, and
    absolute-path forms (e.g. "env sudo", 'su"do"', "/usr/bin/sudo") cannot
    bypass confirmation.

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
