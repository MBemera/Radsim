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
    "git diff": {"--stat", "--name-only", "--name-status", "--cached", "--staged", "--check", "--no-ext-diff", "--no-textconv"},
    "git log": {"--oneline", "--stat", "--no-decorate"},
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
        directory = Path(tool_input.get("working_dir") or root).resolve()
        if not directory.is_dir() or not directory.is_relative_to(root):
            return RequestClassification("ask", "Working directory is outside the project or missing")
        return _classify_command(command, directory, tool_input.get("test_path"))
    except (OSError, RuntimeError, TypeError, ValueError):
        return RequestClassification("ask", "Request could not be classified reliably")


def _classify_command(command, directory, test_path):
    """Require every command segment and extra test path to match."""
    if os.name == "nt":
        return RequestClassification("ask", "Automatic shell classification requires a POSIX shell")
    if command_analysis.is_destructive_command(command, DESTRUCTIVE_COMMANDS):
        return RequestClassification("ask", "Destructive or privileged command")
    tokens = command_analysis.tokenize(command)
    segments = command_analysis.split_into_segments(tokens)
    for segment in segments:
        if not _routine_segment(segment, directory):
            return RequestClassification("ask", "Command, options, or paths need explicit approval")
    if test_path and (str(test_path).startswith("-") or not _project_argument(test_path, directory)):
        return RequestClassification("ask", "Test path needs explicit approval")
    return RequestClassification("allow", "Routine project inspection or verification")


def _routine_segment(segment, directory):
    """Match a literal executable and its supported argument grammar."""
    if any(token in command_analysis.REDIRECTION_OPERATORS for token in segment):
        return False
    if any(any(char in token for char in "*?{}~\\") for token in segment):
        return False
    arguments = shlex.split(" ".join(segment))
    name = arguments.pop(0)
    if name in {"python", "python3"} and arguments[:1] == ["-m"]:
        arguments.pop(0)
        name = arguments.pop(0) if arguments else ""
    if name in {"git", "ruff"}:
        name += " " + (arguments.pop(0) if arguments else "")
    if name not in COMMAND_FLAGS:
        return False
    if name == "ruff format" and not {"--check", "--diff"}.intersection(arguments):
        return False
    return _routine_arguments(name, arguments, directory)


def _routine_arguments(name, arguments, directory):
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
        if argument.startswith("-") and not after_separator:
            option, separator, _value = argument.partition("=")
            if option in VALUE_FLAGS.get(name, set()):
                pending_value = not separator
            elif not _known_flag(argument, COMMAND_FLAGS[name]):
                return False
            continue
        if not _project_argument(argument, directory):
            return False
        positionals.append(argument)
    if pending_value:
        return False
    return _content_targets_safe(name, arguments, positionals, directory)


def _known_flag(argument, flags):
    """Accept exact flags and clusters of explicitly supported short flags."""
    if argument in flags:
        return True
    return argument.startswith("-") and not argument.startswith("--") and all(
        f"-{letter}" in flags for letter in argument[1:]
    ) and len(argument) > 1


def _project_argument(argument, directory):
    """Keep literal paths in the project and away from secret material."""
    path_text = str(argument).split("::", 1)[0]
    target = (directory / path_text).resolve()
    if not target.is_relative_to(Path.cwd().resolve()):
        return False
    secret, _reason = is_secret_read_path(path_text, str(target))
    return not secret


def _content_targets_safe(name, arguments, positionals, directory):
    """Content readers need explicit regular files; listings may use directories."""
    if name not in CONTENT_READERS or (name == "rg" and "--files" in arguments):
        return True
    paths = positionals[1:] if name in {"rg", "grep"} else positionals
    return bool(paths) and all((directory / path).is_file() for path in paths)
