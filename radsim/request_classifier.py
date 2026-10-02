"""Classify routine commands for explicit auto mode, without model calls."""

import ntpath
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from .tools import command_analysis, powershell_analysis
from .tools.constants import DESTRUCTIVE_COMMANDS
from .tools.powershell_parser import PowerShellParserError, parse_powershell
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
    "git show": {
        "--stat",
        "--summary",
        "--name-only",
        "--name-status",
        "--raw",
        "--no-patch",
        "--format=",
    },
    "git rev-parse": {"--show-toplevel", "--show-prefix", "--is-inside-work-tree", "--short"},
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


@dataclass(frozen=True)
class CmdletGrammar:
    """Read-only PowerShell cmdlet arguments that auto mode accepts.

    positionals: "none", "text", "paths" (listings), "files" (content
    readers need explicit regular files) or "pattern_then_files".
    """

    positionals: str
    switches: frozenset[str] = frozenset()
    number_parameters: frozenset[str] = frozenset()
    path_parameters: frozenset[str] = frozenset()
    text_parameters: frozenset[str] = frozenset()


# PowerShell equivalents of pwd, echo, ls, cat, head/tail, grep and wc.
# Parameter names must be written in full; abbreviations prompt instead.
CMDLET_GRAMMARS = {
    "get-location": CmdletGrammar("none"),
    "write-output": CmdletGrammar("text", switches=frozenset({"noenumerate"})),
    "get-childitem": CmdletGrammar(
        "paths",
        switches=frozenset({"name", "force", "file", "directory", "hidden"}),
        path_parameters=frozenset({"path", "literalpath"}),
    ),
    "get-content": CmdletGrammar(
        "files",
        switches=frozenset({"raw"}),
        number_parameters=frozenset({"totalcount", "head", "first", "tail", "last"}),
        path_parameters=frozenset({"path", "literalpath"}),
    ),
    "select-string": CmdletGrammar(
        "pattern_then_files",
        switches=frozenset({"simplematch", "casesensitive", "list", "quiet", "notmatch"}),
        path_parameters=frozenset({"path", "literalpath"}),
        text_parameters=frozenset({"pattern"}),
    ),
    "measure-object": CmdletGrammar("none", switches=frozenset({"line", "word", "character"})),
    "select-object": CmdletGrammar("none", number_parameters=frozenset({"first", "last", "skip"})),
}
FILE_OBJECT_PRODUCERS = {"get-childitem", "get-item"}
UNSAFE_WINDOWS_PATH_CHARACTERS = "*?[]{}~`$"


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
    if command_analysis.shell_is_powershell():
        return _classify_powershell_command(command, directory, test_path)
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
    return _routine_argv(shlex.split(" ".join(segment)), directory, piped_input)


def _routine_argv(arguments, directory, piped_input=False):
    """Match an executable name and its arguments against the routine grammar."""
    arguments = list(arguments)
    name = arguments.pop(0)
    if name in {"python", "python3"} and arguments[:1] == ["-m"]:
        arguments.pop(0)
        name = arguments.pop(0) if arguments else ""
        if name not in {"pytest", "ruff"}:
            return False
    if name == "git" and arguments[:1] == ["-C"]:
        if len(arguments) < 3 or not _project_argument(arguments[1], directory):
            return False
        directory = (directory / arguments[1]).resolve()
        if not directory.is_dir():
            return False
        arguments = arguments[2:]
    if name in {"git", "ruff", "npm", "vitest", "go", "cargo"}:
        name += " " + (arguments.pop(0) if arguments else "")
    if name not in COMMAND_FLAGS:
        return False
    options = _arguments_before_separator(arguments)
    if name == "ruff format" and not {"--check", "--diff"}.intersection(options):
        return False
    if name == "git show" and not {
        "--stat",
        "--summary",
        "--name-only",
        "--name-status",
        "--raw",
        "--no-patch",
    }.intersection(options):
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


# ---------------------------------------------------------------------------
# Windows PowerShell
# ---------------------------------------------------------------------------


def _classify_powershell_command(command, directory, test_path):
    """Allow only plain read-only PowerShell commands with literal arguments."""
    if test_path:
        if not isinstance(test_path, str) or test_path.startswith("-"):
            return RequestClassification("ask", "Test path needs explicit approval")
        command += " " + _powershell_quote(test_path)
        valid, _reason = validate_shell_command(command)
        if not valid:
            return RequestClassification("ask", "Test path needs explicit approval")
    if powershell_analysis.is_destructive(command, DESTRUCTIVE_COMMANDS):
        return RequestClassification("block", "Destructive or privileged command")
    try:
        parsed = parse_powershell(command)
    except PowerShellParserError:
        return RequestClassification("ask", "Request could not be classified reliably")
    if not parsed.plain or parsed.redirections:
        return RequestClassification("ask", "Variables, script blocks or redirection need explicit approval")
    for parsed_command in parsed.commands:
        if not _routine_powershell_command(parsed_command, parsed, directory):
            return RequestClassification("ask", "Command, options, or paths need explicit approval")
    return RequestClassification("allow", "Routine project inspection or verification")


def _powershell_quote(value):
    """Quote one literal argument for PowerShell."""
    return "'" + value.replace("'", "''") + "'"


def _routine_powershell_command(command, parsed, directory):
    """Match one command against the cmdlet table or the shared native-tool grammar."""
    canonical_name = (command.alias_of or command.name or "").lower()
    grammar = CMDLET_GRAMMARS.get(canonical_name)
    if grammar is not None:
        return _routine_cmdlet(grammar, command, parsed, directory)
    if command.alias_of is not None:
        return False
    return _routine_native_command(command, directory)


def _routine_cmdlet(grammar, command, parsed, directory):
    """Check a cmdlet's parameters and positionals against its grammar."""
    collected = _collect_cmdlet_arguments(grammar, command)
    if collected is None:
        return False
    positionals, paths, texts = collected

    if grammar.positionals == "none":
        return not positionals and not paths
    if grammar.positionals == "text":
        return True
    if grammar.positionals == "pattern_then_files" and not texts:
        if not positionals:
            return False
        positionals = positionals[1:]
    paths = paths + positionals
    if not all(_windows_project_path(path, directory) for path in paths):
        return False
    if grammar.positionals == "paths":
        return True
    if paths:
        return all((directory / path).is_file() for path in paths)
    receives_text = command.pipeline_index > 0 and not _receives_file_objects(command, parsed)
    return grammar.positionals == "pattern_then_files" and receives_text


def _collect_cmdlet_arguments(grammar, command):
    """Return (positionals, paths, texts), or None for any parameter outside the grammar."""
    positionals, paths, texts = [], [], []
    value_parameters = grammar.number_parameters | grammar.path_parameters | grammar.text_parameters
    arguments = list(command.arguments)
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        index += 1
        if argument.kind != "parameter":
            positionals.append(argument.value)
            continue
        name = (argument.name or "").lower()
        if name in grammar.switches and not argument.has_argument:
            continue
        if name not in value_parameters:
            return None
        value = argument.value
        if not argument.has_argument:
            if index >= len(arguments) or arguments[index].kind == "parameter":
                return None
            value = arguments[index].value
            index += 1
        if name in grammar.number_parameters and not (value or "").isdigit():
            return None
        (paths if name in grammar.path_parameters else texts).append(value)
    return positionals, paths, texts


def _receives_file_objects(command, parsed):
    """Return True when an earlier command in the pipeline emits files (Select-String would read them)."""
    return any(
        other.pipeline_id == command.pipeline_id
        and other.pipeline_index < command.pipeline_index
        and powershell_analysis.command_names(other) & FILE_OBJECT_PRODUCERS
        for other in parsed.commands
    )


def _routine_native_command(command, directory):
    """Apply the shared git/pytest/ruff/npm grammar to a native program."""
    name = command.name or ""
    if re.search(r"[\\/]", name):
        return False
    stem, extension = ntpath.splitext(name.lower())
    if extension not in {"", ".exe"}:
        return False
    arguments = [
        argument.text if argument.kind == "parameter" else argument.value
        for argument in command.arguments
    ]
    if any(not _native_argument_safe(argument) for argument in arguments):
        return False
    return _routine_argv([stem, *arguments], directory, piped_input=command.pipeline_index > 0)


def _native_argument_safe(argument):
    """Refuse wildcards, UNC paths and provider or stream paths PowerShell would pass through."""
    if any(character in argument for character in UNSAFE_WINDOWS_PATH_CHARACTERS):
        return False
    if argument.startswith("-"):
        return True
    path_part = argument.split("::", 1)[0]
    if path_part.startswith(("\\\\", "//")):
        return False
    return ":" not in path_part or bool(re.fullmatch(r"[A-Za-z]:[\\/][^:]*", path_part))


def _windows_project_path(value, directory):
    """Keep a cmdlet path literal, inside the project and away from secrets."""
    if not value or value.startswith("-"):
        return False
    if any(character in value for character in UNSAFE_WINDOWS_PATH_CHARACTERS):
        return False
    if value.startswith(("\\\\", "//")):
        return False
    if ":" in value and not re.fullmatch(r"[A-Za-z]:[\\/][^:]*", value):
        return False
    return _project_argument(value, directory)
