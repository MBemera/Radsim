"""Classify routine commands for explicit auto mode, without model calls."""

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from .tools import command_analysis
from .tools.constants import DESTRUCTIVE_COMMANDS
from .tools.validation import is_secret_read_path, validate_shell_command


@dataclass(frozen=True)
class RequestClassification:
    decision: str
    reason: str


# Only listed options are automatic; options that execute helpers or write files prompt.
COMMAND_FLAGS = {
    "echo": {"-n"},
    "pwd": {"-L", "-P"},
    "ls": {"-a", "-l", "-h", "-t", "-r", "-d", "-1", "--all", "--long"},
    "cat": {"-n", "-b", "-s", "--number"},
    "head": set(),
    "tail": set(),
    "wc": {"-l", "-w", "-c", "-m", "-L"},
    "rg": {"-n", "-i", "-l", "-q", "-F", "-w", "--files", "--fixed-strings"},
    "grep": {"-n", "-i", "-l", "-q", "-F", "-w"},
    "pytest": {"-q", "-v", "-x", "-s", "--collect-only", "--disable-warnings", "--lf", "--ff"},
    "ruff check": {"--no-cache", "--quiet", "--verbose"},
    "ruff format": {"--check", "--diff", "--no-cache", "--quiet", "--verbose"},
    "git status": {"--short", "--branch", "--porcelain", "-s", "-b"},
    "git diff": {
        "--stat",
        "--name-only",
        "--name-status",
        "--cached",
        "--staged",
        "--no-ext-diff",
        "--no-textconv",
    },
    "git log": {"--oneline", "--stat", "--no-decorate"},
    "npm test": set(),
    "jest": {"--runInBand", "--ci", "--verbose"},
    "vitest run": {"--silent"},
    "mocha": set(),
    "go test": {"-v", "-race", "-short"},
    "cargo test": {"--quiet", "--locked", "--offline"},
}
VALUE_FLAGS = {
    "head": {"-n", "--lines"},
    "tail": {"-n", "--lines"},
    "pytest": {"-k", "-m", "--maxfail", "--tb"},
    "git log": {"-n", "--max-count"},
}
CONTENT_READERS = {"cat", "head", "tail", "wc", "rg", "grep"}


def classify_request(tool_name, tool_input):
    """Return allow, ask, or block for a shell or custom test request."""
    key = {"run_shell_command": "command", "run_tests": "test_command"}.get(tool_name)
    if key is None or not isinstance(tool_input, dict):
        return RequestClassification("ask", "No automatic rule for this request")
    command = tool_input.get(key, "")
    valid, reason = validate_shell_command(command)
    if not valid:
        return RequestClassification("block", reason)
    try:
        root = Path.cwd().resolve()
        working_dir = tool_input.get("working_dir") if tool_name == "run_shell_command" else None
        directory = Path(working_dir or root).resolve()
        if not directory.is_dir() or not directory.is_relative_to(root):
            return RequestClassification(
                "ask", "Working directory is outside the project or missing"
            )
        test_path = tool_input.get("test_path") if tool_name == "run_tests" else None
        return _classify_command(command, directory, test_path)
    except (OSError, RuntimeError, TypeError, ValueError):
        return RequestClassification("ask", "Request could not be classified reliably")


def _classify_command(command, directory, test_path):
    """Require every command segment and extra test path to match."""
    if os.name == "nt":
        return RequestClassification("ask", "Automatic shell classification requires a POSIX shell")
    if command_analysis.is_destructive_command(command, DESTRUCTIVE_COMMANDS):
        return RequestClassification("block", "Destructive or privileged command")
    if test_path:
        if not isinstance(test_path, str) or test_path.startswith("-"):
            return RequestClassification("ask", "Test path needs explicit approval")
        command += f" {shlex.quote(test_path)}"
        valid, _reason = validate_shell_command(command)
        if not valid:
            return RequestClassification("ask", "Test path needs explicit approval")
    tokens = command_analysis.tokenize(command)
    for segment, piped_input in _command_segments(tokens):
        if not _routine_segment(segment, directory, piped_input):
            return RequestClassification("ask", "Command, options, or paths need explicit approval")
    return RequestClassification("allow", "Routine project inspection or verification")


def _command_segments(tokens):
    """Track whether each segment receives an already-checked pipeline's output."""
    segment = []
    piped_input = False
    for token in tokens:
        if token not in command_analysis.SEGMENT_OPERATORS:
            segment.append(token)
            continue
        if segment:
            yield segment, piped_input
        segment = []
        piped_input = token in {"|", "|&"}
    if segment:
        yield segment, piped_input


def _routine_segment(segment, directory, piped_input=False):
    """Match a literal executable and its supported argument grammar."""
    if any(token in command_analysis.REDIRECTION_OPERATORS for token in segment):
        return False
    if any(any(char in token for char in "*?[]{}~\\") for token in segment):
        return False
    arguments = shlex.split(" ".join(segment))
    name = arguments.pop(0)
    if name in {"python", "python3"} and arguments[:1] == ["-m"]:
        arguments.pop(0)
        name = arguments.pop(0) if arguments else ""
        if name not in {"pytest", "ruff"}:
            return False
    if name in {"git", "ruff", "npm", "vitest", "go", "cargo"}:
        name += " " + (arguments.pop(0) if arguments else "")
    if name not in COMMAND_FLAGS:
        return False
    options = _arguments_before_separator(arguments)
    if name == "ruff format" and not {"--check", "--diff"}.intersection(options):
        return False
    if name == "git diff" and not {"--stat", "--name-only", "--name-status"}.intersection(options):
        return False
    return _routine_arguments(name, arguments, directory, piped_input)


def _routine_arguments(name, arguments, directory, piped_input=False):
    """Reject unknown flags, secret paths, and recursive content reads."""
    positionals = []
    after_separator = False
    pending_value = False
    for argument in arguments:
        if pending_value:
            pending_value = False
            continue
        if argument == "--" and not after_separator:
            after_separator = True
            continue
        if argument == "-" and name in CONTENT_READERS and piped_input:
            positionals.append(argument)
            continue
        if argument.startswith("-") and not after_separator:
            option, separator, _value = argument.partition("=")
            if option in VALUE_FLAGS.get(name, set()):
                pending_value = not separator
            elif not _known_flag(argument, COMMAND_FLAGS[name]):
                return False
            continue
        if not _positional_argument_safe(name, argument, directory):
            return False
        positionals.append(argument)
    if pending_value:
        return False
    return _content_targets_safe(name, arguments, positionals, directory, piped_input)


def _positional_argument_safe(name: str, argument: str, directory: Path) -> bool:
    """Interpret only supported command-specific path syntax."""
    if name in {"npm test", "cargo test"} and argument.startswith("-"):
        return False
    if name.startswith("git ") and ":" in argument:
        return False
    path_argument = argument.split("::", 1)[0] if name == "pytest" else argument
    return _project_argument(path_argument, directory)


def _known_flag(argument, flags):
    """Accept exact flags and clusters of explicitly supported short flags."""
    if argument in flags:
        return True
    return (
        argument.startswith("-")
        and not argument.startswith("--")
        and all(f"-{letter}" in flags for letter in argument[1:])
        and len(argument) > 1
    )


def _project_argument(argument, directory):
    """Keep literal paths in the project and away from secret material."""
    path_text = str(argument)
    target = (directory / path_text).resolve()
    if not target.is_relative_to(Path.cwd().resolve()):
        return False
    secret, _reason = is_secret_read_path(path_text, str(target))
    return not secret


def _arguments_before_separator(arguments: list[str]) -> list[str]:
    """Return only arguments that can still be interpreted as options."""
    if "--" in arguments:
        return arguments[: arguments.index("--")]
    return arguments


def _content_targets_safe(name, arguments, positionals, directory, piped_input=False):
    """Content readers need explicit regular files; listings may use directories."""
    options = _arguments_before_separator(arguments)
    if name not in CONTENT_READERS or (name == "rg" and "--files" in options):
        return True
    paths = positionals[1:] if name in {"rg", "grep"} else positionals
    if name in {"rg", "grep"} and not positionals:
        return False
    if not paths:
        return piped_input
    return all((path == "-" and piped_input) or (directory / path).is_file() for path in paths)
