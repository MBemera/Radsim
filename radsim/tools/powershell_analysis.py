"""Command policy rules for Windows PowerShell.

The bash rules forbid `$`, backticks, `&`, parentheses and braces because
they can hide what a bash command runs. PowerShell needs all of them for
ordinary work, so on Windows the command is read from PowerShell's own parse
tree instead: every command anywhere in it (inside script blocks, pipelines
and subexpressions) is checked, and only constructs whose target cannot be
seen are refused.

Three outcomes, matching the bash rules:
- unanalyzable: refused, because nothing can say what it would run
- catastrophic: refused at every security level (can wreck the machine)
- destructive: always needs an explicit "yes"; auto mode refuses it
"""

import ntpath
import os
import re
import shlex
from dataclasses import dataclass

from .command_analysis import NESTED_SHELL_PROGRAMS, has_inline_code_flag, is_path_traversal
from .powershell_parser import (
    PowerShellArgument,
    PowerShellCommand,
    PowerShellParse,
    PowerShellParserError,
    PowerShellRedirection,
    parse_powershell,
)

EXECUTABLE_EXTENSIONS = {".exe", ".com", ".cmd", ".bat"}

# Programs that run code the parse tree cannot see.
WINDOWS_NESTED_PROGRAMS = NESTED_SHELL_PROGRAMS | {"powershell_ise", "wsl", "mshta"}
UNANALYZABLE_COMMANDS = {
    "invoke-expression",
    "add-type",
    "set-alias",
    "new-alias",
    "import-alias",
}
COMMAND_REDEFINITION_PREFIXES = ("alias:", "function:")

# Wipe, repartition or encrypt disks, or break booting and recovery.
CATASTROPHIC_COMMANDS = {
    "diskpart",
    "format-volume",
    "clear-disk",
    "initialize-disk",
    "remove-partition",
    "resize-partition",
    "set-partition",
    "set-disk",
    "reset-physicaldisk",
    "remove-physicaldisk",
    "remove-virtualdisk",
    "remove-storagepool",
    "mkfs",
    "wipefs",
    "bcdedit",
    "bcdboot",
    "bootrec",
    "bootsect",
    "reagentc",
    "systemreset",
    "sysprep",
    "manage-bde",
    "enable-bitlocker",
    "disable-bitlocker",
    "lock-bitlocker",
    "remove-bitlockerkeyprotector",
}
# "format" is only catastrophic as the program itself; "npm run format" is fine.
FORMAT_PROGRAM_NAMES = {"format", "format.com"}
CATASTROPHIC_SUBCOMMANDS = {
    "vssadmin": {"delete", "resize"},
    "wbadmin": {"delete"},
}

DELETION_COMMANDS = {"remove-item", "rm", "rmdir", "rd", "del", "erase", "ri", "clear-content", "clear-item"}
MOVE_COMMANDS = {"move-item", "mv", "move", "mi"}
ITEM_LISTING_COMMANDS = {"get-childitem", "get-item"}
PERMISSION_COMMANDS = {"takeown", "icacls", "cacls", "set-acl"}
ICACLS_CHANGE_SWITCHES = (
    "/grant",
    "/deny",
    "/remove",
    "/reset",
    "/setowner",
    "/setintegritylevel",
    "/inheritance",
    "/restore",
    "/substitute",
    "/t",
)
PRIVILEGE_WRAPPERS = {"sudo", "gsudo"}
LOCATION_COMMANDS = {"set-location", "push-location", "pop-location", "new-psdrive", "remove-psdrive"}
PROVIDER_MUTATION_COMMANDS = DELETION_COMMANDS | MOVE_COMMANDS | {
    "set-item", "new-item", "set-content", "add-content", "rename-item", "copy-item",
}
CMD_DELETE_SWITCHES = {"/s", "/q", "/f", "/p", "/a"}

# Parameters of the item cmdlets above that take a value; any other parameter
# is a switch, so the value after it is positional.
VALUE_PARAMETERS = {
    "path",
    "literalpath",
    "pspath",
    "lp",
    "filter",
    "include",
    "exclude",
    "credential",
    "stream",
    "destination",
    "depth",
    "attributes",
    "aclobject",
    "erroraction",
    "warningaction",
    "informationaction",
    "errorvariable",
    "warningvariable",
    "informationvariable",
    "outvariable",
    "outbuffer",
    "pipelinevariable",
    "ea",
    "wa",
    "infa",
    "ev",
    "wv",
    "iv",
    "ov",
    "ob",
    "pv",
    "filepath",
    "argumentlist",
    "args",
    "verb",
    "workingdirectory",
    "windowstyle",
    "redirectstandardinput",
    "redirectstandardoutput",
    "redirectstandarderror",
}
PATH_PARAMETERS = {"path", "literalpath", "pspath", "lp"}

MACHINE_REGISTRY_PATH = re.compile(
    r"^(?:[\w.]+\\)?(?:registry::)?"
    r"(?:hklm|hkcr|hku|hkcc|hkey_local_machine|hkey_classes_root|hkey_users|hkey_current_config)"
    r":?(?:[\\/]|$)",
    re.IGNORECASE,
)
RAW_DEVICE_PATH = re.compile(
    r"^(?:\\\\|//)[.?][\\/](?:physicaldrive\d|[a-z]:|harddisk|volume\{|globalroot)|^\\device\\harddisk",
    re.IGNORECASE,
)
FILESYSTEM_PROVIDER_PREFIX = re.compile(r"^(?:[\w.]+\\)?filesystem::", re.IGNORECASE)
ENVIRONMENT_REFERENCE = re.compile(r"\$\{env:([^}]+)\}|\$env:([A-Za-z0-9_]+)", re.IGNORECASE)
AUTOMATIC_PATH_VARIABLE = re.compile(r"\$(home|pwd)(?![\w:])", re.IGNORECASE)
WILDCARD_CHARACTERS = "*?["
HARMLESS_REDIRECTION_TARGETS = {"$null", "nul", "nul:"}

COMPUTED_DELETION_REASON = (
    "Command is catastrophic: recursive deletion needs a literal path "
    "(an empty or wrong variable could wipe a whole drive)"
)

WINDOWS_DESTRUCTIVE_COMMANDS = {
    # Write, move or delete files and provider items
    "remove-item",
    "move-item",
    "clear-content",
    "clear-item",
    "set-content",
    "add-content",
    "out-file",
    "tee-object",
    "set-item",
    "remove-itemproperty",
    "set-itemproperty",
    "new-itemproperty",
    "clear-itemproperty",
    "rd",
    "erase",
    # Run other programs or code out of sight
    "start-process",
    "invoke-item",
    "invoke-command",
    "start-job",
    "invoke-cimmethod",
    "invoke-wmimethod",
    "remove-ciminstance",
    "remove-wmiobject",
    # Change system state, services, accounts, scheduled tasks and security
    "stop-computer",
    "restart-computer",
    "shutdown",
    "stop-process",
    "taskkill",
    "stop-service",
    "restart-service",
    "set-service",
    "sc",
    "set-executionpolicy",
    "set-mppreference",
    "add-mppreference",
    "remove-mppreference",
    "disable-computerrestore",
    "register-scheduledtask",
    "unregister-scheduledtask",
    "set-scheduledtask",
    "schtasks",
    "remove-localuser",
    "disable-localuser",
    "set-localuser",
    "add-localgroupmember",
    "remove-localgroupmember",
    "takeown",
    "icacls",
    "cacls",
    "set-acl",
    "fsutil",
    "msiexec",
    "runas",
    "gsudo",
    "uninstall-package",
    "uninstall-module",
}
WINDOWS_DESTRUCTIVE_SUBCOMMANDS = {
    "reg add",
    "reg delete",
    "reg import",
    "reg restore",
    "reg load",
    "reg unload",
    "reg copy",
    "net user",
    "net localgroup",
    "net stop",
    "winget uninstall",
    "choco uninstall",
    "robocopy /mir",
    "robocopy /purge",
}


@dataclass(frozen=True)
class WindowsPathContext:
    """Where relative paths resolve and what the environment variables hold."""

    working_dir: str
    environment: dict[str, str]

    @classmethod
    def current(cls) -> "WindowsPathContext":
        return cls(working_dir=os.getcwd(), environment=dict(os.environ))

    def variable(self, name: str) -> str:
        """Return an environment variable the way PowerShell reads it (case-insensitive)."""
        wanted = name.lower()
        for key, value in self.environment.items():
            if key.lower() == wanted:
                return value
        return ""

    @property
    def home(self) -> str:
        return self.variable("USERPROFILE") or self.variable("HOME")


# ---------------------------------------------------------------------------
# Public entry points: parse, then apply one rule set
# ---------------------------------------------------------------------------


def unanalyzable_reason(command: str) -> str | None:
    """Return why a command cannot be checked, or None when it can."""
    try:
        parsed = parse_powershell(command)
    except PowerShellParserError as error:
        return f"PowerShell could not check the command ({error}); blocked for safety"
    return find_unanalyzable_reason(parsed)


def catastrophic_reason(command: str, context: WindowsPathContext | None = None) -> str | None:
    """Return why a command could wreck the machine, or None."""
    try:
        parsed = parse_powershell(command)
    except PowerShellParserError as error:
        return f"Command could not be checked by PowerShell ({error}); blocked for safety"
    return find_catastrophic_reason(parsed, context or WindowsPathContext.current())


def is_destructive(command: str, destructive_commands) -> bool:
    """Return True when a command must have explicit confirmation. Fails closed."""
    try:
        parsed = parse_powershell(command)
    except PowerShellParserError:
        return True
    return parse_is_destructive(parsed, destructive_commands)


# ---------------------------------------------------------------------------
# Names and arguments
# ---------------------------------------------------------------------------


def command_names(command: PowerShellCommand) -> set[str]:
    """Return every lowercase name the command could run under, alias included."""
    names = set()
    for raw_name in (command.name, command.alias_of):
        if not raw_name:
            continue
        base_name = re.split(r"[\\/]", raw_name)[-1].lower()
        names.add(base_name)
        stem, extension = ntpath.splitext(base_name)
        if extension in EXECUTABLE_EXTENSIONS:
            names.add(stem)
    return names


def literal_values(command: PowerShellCommand) -> list[str]:
    """Return every literal string among a command's arguments (list items included)."""
    return [item for argument in command.arguments for item in (argument.items or ())]


def bound_arguments(command: PowerShellCommand) -> list[tuple[str | None, PowerShellArgument]]:
    """Pair each value with the parameter it binds to; None means positional."""
    pairs = []
    pending = None
    for argument in command.arguments:
        if argument.kind != "parameter":
            pairs.append((pending, argument))
            pending = None
            continue
        name = (argument.name or "").lower()
        if argument.has_argument:
            pairs.append((name, argument))
            pending = None
        elif name and any(parameter.startswith(name) for parameter in VALUE_PARAMETERS):
            pending = name
        else:
            pending = None
    return pairs


def path_arguments(command: PowerShellCommand, sources_only: bool = False) -> list[PowerShellArgument]:
    """Return arguments that name paths: positionals and -Path/-LiteralPath values.

    With sources_only, a second positional (a move destination) is left out.
    """
    arguments = []
    positional_count = 0
    for parameter, argument in bound_arguments(command):
        if parameter is None:
            positional_count += 1
            if sources_only and positional_count > 1:
                continue
            arguments.append(argument)
        elif any(path.startswith(parameter) for path in PATH_PARAMETERS):
            arguments.append(argument)
    return arguments


def literal_paths(argument: PowerShellArgument, context: WindowsPathContext) -> list[str] | None:
    """Return the paths one argument names, or None when they are computed at run time."""
    if argument.items is not None:
        return list(argument.items)
    resolved = resolve_template(argument.template, context)
    return None if resolved is None else [resolved]


def resolve_template(template: str | None, context: WindowsPathContext) -> str | None:
    """Expand $env:, $HOME and $PWD in a string; None when anything else is computed."""
    if template is None:
        return None
    expanded = ENVIRONMENT_REFERENCE.sub(
        lambda match: context.variable(match.group(1) or match.group(2)), template
    )
    expanded = AUTOMATIC_PATH_VARIABLE.sub(
        lambda match: context.home if match.group(1).lower() == "home" else context.working_dir,
        expanded,
    )
    if "$" in expanded or "`" in expanded:
        return None
    return expanded


# ---------------------------------------------------------------------------
# Unanalyzable constructs
# ---------------------------------------------------------------------------


def find_unanalyzable_reason(parsed: PowerShellParse) -> str | None:
    """Refuse commands whose real program or code is hidden from analysis."""
    if parsed.errors:
        return f"PowerShell could not parse the command: {parsed.errors[0]}"
    if any(name.lower().endswith("scriptblock") for name in parsed.type_names):
        return "Building script blocks from text is forbidden (the code cannot be checked)"
    for command in parsed.commands:
        reason = _command_unanalyzable_reason(command)
        if reason:
            return reason
    return None


def _command_unanalyzable_reason(command: PowerShellCommand) -> str | None:
    """Check one command for hidden execution."""
    if command.name is None:
        return "The program name must be written literally, not computed from a variable or expression"
    names = command_names(command)
    if names & WINDOWS_NESTED_PROGRAMS:
        return "Nested shells and inline interpreter code are forbidden"
    if has_inline_code_flag(names, [argument.text for argument in command.arguments]):
        return "Nested shells and inline interpreter code are forbidden"
    if "start-process" in names:
        reason = _launch_unanalyzable_reason(command)
        if reason:
            return reason
    if names & PRIVILEGE_WRAPPERS:
        wrapped = _wrapped_command(command)
        if wrapped is None:
            return "Wrapped program names must be literal; blocked for safety"
        reason = _command_unanalyzable_reason(wrapped)
        if reason:
            return reason
    if names & UNANALYZABLE_COMMANDS:
        return "Invoke-Expression, Add-Type and alias changes are forbidden (they hide what runs)"
    if any(value.lower().startswith(COMMAND_REDEFINITION_PREFIXES) for value in literal_values(command)):
        return "Redefining aliases or functions is forbidden (it hides what runs)"
    for text in [command.name_text] + [argument.text for argument in command.arguments]:
        if is_path_traversal(text):
            return "Path traversal ('..') is forbidden in command"
    return None


def _launch_unanalyzable_reason(command: PowerShellCommand) -> str | None:
    """Check the actual Start-Process target and its flattened argument list."""
    pairs = bound_arguments(command)
    targets = [argument for name, argument in pairs if name is None or "filepath".startswith(name)]
    if not targets or targets[0].value is None:
        return "Start-Process needs a literal program name; blocked for safety"
    target_argument = targets[0]
    target = target_argument.value
    base_name = re.split(r"[\\/]", target)[-1].lower()
    stem, extension = ntpath.splitext(base_name)
    names = {base_name, stem} if extension in EXECUTABLE_EXTENSIONS else {base_name}
    if names & WINDOWS_NESTED_PROGRAMS:
        return "Nested shells and inline interpreter code are forbidden"
    arguments = [
        argument for name, argument in pairs
        if argument is not target_argument and (name is None or name == "args" or "argumentlist".startswith(name))
    ]
    return _launch_arguments_reason(names, arguments)


def _launch_arguments_reason(names: set[str], arguments: list[PowerShellArgument]) -> str | None:
    """Refuse computed or inline-code arguments passed through Start-Process."""
    if any(argument.items is None for argument in arguments):
        return "Start-Process arguments must be literal; blocked for safety"
    try:
        tokens = shlex.split(" ".join(item for argument in arguments for item in argument.items), posix=False)
    except ValueError:
        return "Start-Process arguments could not be checked; blocked for safety"
    if has_inline_code_flag(names, [token.strip("'\"") for token in tokens]):
        return "Nested shells and inline interpreter code are forbidden"
    return None


# ---------------------------------------------------------------------------
# Catastrophic operations
# ---------------------------------------------------------------------------


def find_catastrophic_reason(parsed: PowerShellParse, context: WindowsPathContext) -> str | None:
    """Return the first machine-wrecking operation found, or None."""
    unanalyzable = find_unanalyzable_reason(parsed)
    if unanalyzable:
        return f"Command cannot be analysed ({unanalyzable}); blocked for safety"
    for redirection in parsed.redirections:
        if _is_raw_device(redirection.target_text or ""):
            return "Command is catastrophic: it writes to a raw disk device"
    for command in parsed.commands:
        reason = _command_catastrophic_reason(command, parsed, context)
        if reason:
            return reason
    protected_operations = DELETION_COMMANDS | MOVE_COMMANDS | PERMISSION_COMMANDS | PRIVILEGE_WRAPPERS
    if any(command_names(command) & protected_operations for command in parsed.commands):
        if _changes_path_context(parsed, context):
            return "Command is catastrophic: location or environment changes invalidate protected path checks"
    return None


def _changes_path_context(parsed: PowerShellParse, context: WindowsPathContext) -> bool:
    """Reject a changed or unknown path context when checking protected operations."""
    if parsed.context_mutations:
        return True
    if any(name.strip("'\"").lower() in {"setenvironmentvariable", "setcurrentdirectory"} for name in parsed.method_calls):
        return True
    check_computed_paths = len(parsed.commands) > 1
    return any(_command_changes_path_context(command, context, check_computed_paths) for command in parsed.commands)


def _command_changes_path_context(
    command: PowerShellCommand, context: WindowsPathContext, check_computed_paths: bool
) -> bool:
    """Detect location, drive, environment-provider and automatic-variable changes."""
    names = command_names(command)
    if names & LOCATION_COMMANDS:
        return True
    if names & {"set-variable", "new-variable", "remove-variable", "clear-variable"}:
        return any(value.lower() in {"home", "pwd"} or value.lower().startswith("env:") for value in literal_values(command))
    if not names & PROVIDER_MUTATION_COMMANDS:
        return False
    for argument in path_arguments(command):
        values = literal_paths(argument, context)
        if values is None and check_computed_paths:
            return True
        if any(re.match(r"^(?:[\w.]+\\)?(?:environment::|env:)", value, re.IGNORECASE) for value in values or []):
            return True
    return False


def _command_catastrophic_reason(
    command: PowerShellCommand, parsed: PowerShellParse, context: WindowsPathContext
) -> str | None:
    """Apply every catastrophic rule to one command."""
    names = command_names(command)
    values = literal_values(command)
    lowered_values = [value.lower() for value in values]

    if names & CATASTROPHIC_COMMANDS or names & FORMAT_PROGRAM_NAMES:
        return "Command is catastrophic: it formats, wipes or repartitions disks, or breaks booting"
    for program, subcommands in CATASTROPHIC_SUBCOMMANDS.items():
        if program in names and subcommands.intersection(lowered_values):
            return "Command is catastrophic: it deletes system backups or restore points"
    if "wmic" in names and "shadowcopy" in lowered_values and "delete" in lowered_values:
        return "Command is catastrophic: it deletes system restore points"
    if any(_names_catastrophic_program(value) for value in values):
        return "Command is catastrophic: it names a disk-wiping or boot-breaking program"
    if any(_is_raw_device(text) for text in values + [argument.text for argument in command.arguments]):
        return "Command is catastrophic: it targets a raw disk device"
    if names & PRIVILEGE_WRAPPERS:
        wrapped = _wrapped_command(command)
        if wrapped is not None:
            return _command_catastrophic_reason(wrapped, parsed, context)
    if "reg" in names and _deletes_machine_registry_key(lowered_values):
        return "Command is catastrophic: it deletes machine-wide registry keys"
    if names & (DELETION_COMMANDS | MOVE_COMMANDS):
        return _deletion_catastrophic_reason(command, parsed, context)
    if names & PERMISSION_COMMANDS and _changes_permissions(names, lowered_values):
        return _permission_catastrophic_reason(command, context)
    return None


def _names_catastrophic_program(value: str) -> bool:
    """Return True when a literal value names a disk or boot program (alias or Start-Process targets)."""
    base_name = re.split(r"[\\/]", value)[-1].lower()
    stem, extension = ntpath.splitext(base_name)
    if base_name in CATASTROPHIC_COMMANDS or base_name == "format.com":
        return True
    return extension in EXECUTABLE_EXTENSIONS and stem in CATASTROPHIC_COMMANDS


def _is_raw_device(text: str) -> bool:
    """Return True for \\\\.\\PhysicalDrive0-style device paths, including dd's of=<device>."""
    candidates = {text, text.split("=", 1)[-1]}
    return any(RAW_DEVICE_PATH.match(candidate.strip("'\"")) for candidate in candidates)


def _wrapped_command(command: PowerShellCommand) -> PowerShellCommand | None:
    """Return the command a sudo-style wrapper runs, or None when it is not literal."""
    arguments = list(command.arguments)
    while arguments and (arguments[0].kind == "parameter" or (arguments[0].value or "").startswith(("-", "/"))):
        arguments.pop(0)
    if not arguments or arguments[0].value is None:
        return None
    return PowerShellCommand(
        name=arguments[0].value,
        alias_of=None,
        name_text=arguments[0].text,
        invocation="Unknown",
        pipeline_id=command.pipeline_id,
        pipeline_index=command.pipeline_index,
        arguments=tuple(arguments[1:]),
    )


def _deletes_machine_registry_key(lowered_values: list[str]) -> bool:
    """Return True for `reg delete <HKLM|HKCR|HKU key>` without /v (a single value)."""
    if not lowered_values or lowered_values[0] != "delete":
        return False
    if "/v" in lowered_values:
        return False
    return any(MACHINE_REGISTRY_PATH.match(value) for value in lowered_values[1:])


def _changes_permissions(names: set[str], lowered_values: list[str]) -> bool:
    """takeown and Set-Acl always change ownership; icacls only with change switches."""
    if not names & {"icacls", "cacls"}:
        return True
    return any(value.startswith(ICACLS_CHANGE_SWITCHES) for value in lowered_values)


def _deletion_catastrophic_reason(
    command: PowerShellCommand, parsed: PowerShellParse, context: WindowsPathContext
) -> str | None:
    """Refuse deleting or moving system folders, drive roots or the user profile."""
    is_deletion = bool(command_names(command) & DELETION_COMMANDS)
    arguments = path_arguments(command, sources_only=not is_deletion)
    targets = _resolved_targets(arguments, context)

    for target in targets:
        if MACHINE_REGISTRY_PATH.match(target):
            return "Command is catastrophic: it deletes machine-wide registry keys"
        reason = protected_path_reason(target, context)
        if reason:
            return f"Command is catastrophic: it deletes or moves {reason}"

    if not is_deletion:
        return None
    if _is_recursive(command) and len(targets) < _path_count(arguments):
        return COMPUTED_DELETION_REASON
    if command.pipeline_index > 0 and not arguments:
        return _piped_deletion_reason(command, parsed, context)
    return None


def _resolved_targets(arguments: list[PowerShellArgument], context: WindowsPathContext) -> list[str]:
    """Return the literal paths of the given arguments, skipping computed ones and cmd switches."""
    targets = []
    for argument in arguments:
        for path in literal_paths(argument, context) or []:
            if path.lower() not in CMD_DELETE_SWITCHES:
                targets.append(path)
    return targets


def _path_count(arguments: list[PowerShellArgument]) -> int:
    """Return how many paths the arguments name, counting a computed argument as one."""
    count = 0
    for argument in arguments:
        items = [item for item in (argument.items or ()) if item.lower() not in CMD_DELETE_SWITCHES]
        count += len(items) if argument.items is not None else 1
    return count


def _is_recursive(command: PowerShellCommand) -> bool:
    """Return True for -Recurse (any abbreviation), rm-style -rf, or cmd /s."""
    for argument in command.arguments:
        if argument.kind == "parameter":
            name = (argument.name or "").lower()
            if name and "recurse".startswith(name):
                return True
            if "r" in name and set(name) <= {"r", "f", "v"}:
                return True
        elif (argument.value or "").lower() == "/s":
            return True
    return False


def _piped_deletion_reason(
    command: PowerShellCommand, parsed: PowerShellParse, context: WindowsPathContext
) -> str | None:
    """Check what a deletion receives from the commands before it in its pipeline."""
    upstream = [
        other
        for other in parsed.commands
        if other.pipeline_id == command.pipeline_id and other.pipeline_index < command.pipeline_index
    ]
    if len(upstream) < command.pipeline_index:
        return COMPUTED_DELETION_REASON if _is_recursive(command) else None

    for producer in upstream:
        if not command_names(producer) & ITEM_LISTING_COMMANDS:
            continue
        arguments = path_arguments(producer)
        targets = _resolved_targets(arguments, context)
        if len(targets) < _path_count(arguments) and (_is_recursive(command) or _is_recursive(producer)):
            return COMPUTED_DELETION_REASON
        for source in targets or [context.working_dir]:
            reason = protected_path_reason(_as_contents(source), context)
            if reason:
                return f"Command is catastrophic: it deletes {reason}"
    return None


def _as_contents(path_text: str) -> str:
    """Treat a listed folder as its contents, so listing a protected folder counts."""
    if any(character in path_text for character in WILDCARD_CHARACTERS):
        return path_text
    return path_text.rstrip("\\/") + "\\*"


def _permission_catastrophic_reason(command: PowerShellCommand, context: WindowsPathContext) -> str | None:
    """Refuse taking over or resetting permissions on system folders or drive roots."""
    for argument in command.arguments:
        for path in literal_paths(argument, context) or []:
            if path.startswith("/"):
                continue
            reason = protected_path_reason(path, context)
            if reason:
                return f"Command is catastrophic: it changes ownership or permissions of {reason}"
    return None


# ---------------------------------------------------------------------------
# Protected locations
# ---------------------------------------------------------------------------


def protected_path_reason(path_text: str, context: WindowsPathContext) -> str | None:
    """Return a description when a path is, or reaches into, a protected location."""
    path = _absolute_windows_path(path_text, context)
    if path is None:
        return None
    wildcard_container = _wildcard_container(path)
    if wildcard_container is not None:
        if _is_drive_root(wildcard_container):
            return "everything on a drive"
        reason = _protected_location_reason(wildcard_container, context)
        return None if reason is None else f"everything in {reason}"
    if _is_drive_root(path):
        return "a whole drive"
    return _protected_location_reason(path, context)


def _absolute_windows_path(path_text: str, context: WindowsPathContext) -> str | None:
    """Resolve a literal path against the working directory; None for non-file paths."""
    text = path_text.strip().strip("'\"")
    if not text or text.startswith("-"):
        return None
    text = FILESYSTEM_PROVIDER_PREFIX.sub("", text)
    if text.startswith(("\\\\?\\", "//?/")):
        text = text[4:]
    if text.startswith(("\\\\", "//")):
        return None
    if ":" in text and not re.match(r"^[a-zA-Z]:", text):
        return None
    if text == "~" or text.startswith(("~\\", "~/")):
        text = context.home + text[1:]
    return ntpath.normpath(ntpath.join(context.working_dir, text))


def _wildcard_container(path: str) -> str | None:
    """Return the folder whose entries a wildcard path selects, or None without wildcards."""
    drive, rest = ntpath.splitdrive(path)
    parts = [part for part in re.split(r"[\\/]", rest) if part]
    for index, part in enumerate(parts):
        if any(character in part for character in WILDCARD_CHARACTERS):
            return ntpath.normpath(drive + "\\" + "\\".join(parts[:index]))
    return None


def _is_drive_root(path: str) -> bool:
    """Return True for C:\\ or a bare drive such as C:."""
    return bool(re.fullmatch(r"[a-zA-Z]:[\\/]*", path))


def _normalized(path: str) -> str:
    """Case-fold and normalise a Windows path for comparison."""
    normalized = ntpath.normcase(ntpath.normpath(path))
    return normalized if _is_drive_root(normalized) else normalized.rstrip("\\")


def _is_inside(path: str, folder: str) -> bool:
    """Return True when path is strictly inside folder."""
    return _normalized(path).startswith(_normalized(folder) + "\\")


def _is_same_or_inside(path: str, folder: str) -> bool:
    """Return True when path is folder or inside it."""
    return _normalized(path) == _normalized(folder) or _is_inside(path, folder)


def _protected_location_reason(path: str, context: WindowsPathContext) -> str | None:
    """Describe system folders, the Users folder, the user profile and its top-level folders."""
    normalized = _normalized(path)
    system_root = context.variable("SystemRoot") or context.variable("windir") or r"C:\Windows"
    if normalized == _normalized(system_root):
        return "the Windows folder"
    if _is_inside(path, system_root) and not _is_same_or_inside(path, ntpath.join(system_root, "Temp")):
        return "Windows system files"

    for variable, description in (
        ("ProgramFiles", "Program Files"),
        ("ProgramFiles(x86)", "Program Files (x86)"),
        ("ProgramW6432", "Program Files"),
        ("ProgramData", "ProgramData"),
    ):
        folder = context.variable(variable)
        if folder and normalized == _normalized(folder):
            return description

    home = context.home
    if not home:
        return None
    if normalized == _normalized(ntpath.dirname(home)):
        return "the Users folder"
    if normalized == _normalized(home):
        return "your user profile"
    if _normalized(ntpath.dirname(path)) == _normalized(home):
        return f"your profile folder {ntpath.basename(path)}"
    return None


# ---------------------------------------------------------------------------
# Destructive operations (explicit confirmation)
# ---------------------------------------------------------------------------


def parse_is_destructive(parsed: PowerShellParse, destructive_commands) -> bool:
    """Return True when any part of the command changes files or system state."""
    if find_unanalyzable_reason(parsed):
        return True
    if parsed.method_calls:
        return True
    if any(redirection_writes_file(redirection) for redirection in parsed.redirections):
        return True
    configured = {entry.lower() for entry in destructive_commands}
    names_to_check = {entry for entry in configured if " " not in entry} | WINDOWS_DESTRUCTIVE_COMMANDS
    subcommands = {entry for entry in configured if " " in entry} | WINDOWS_DESTRUCTIVE_SUBCOMMANDS
    return any(_command_is_destructive(command, names_to_check, subcommands) for command in parsed.commands)


def redirection_writes_file(redirection: PowerShellRedirection) -> bool:
    """Return True for > or >> into a real file (not $null or a stream merge)."""
    if redirection.kind != "file":
        return False
    return (redirection.target_text or "").strip("'\"").lower() not in HARMLESS_REDIRECTION_TARGETS


def _command_is_destructive(command: PowerShellCommand, names_to_check: set[str], subcommands: set[str]) -> bool:
    """Apply the destructive rules to one command."""
    names = command_names(command)
    if command.invocation == "Dot":
        return True
    if names & names_to_check:
        return True
    if names & (PRIVILEGE_WRAPPERS | {"su", "doas", "pkexec"}):
        return True
    if "new-item" in names and _has_parameter(command, "force"):
        return True
    if "foreach-object" in names and literal_values(command):
        return True
    later_words = set()
    for argument in command.arguments:
        if argument.kind == "parameter":
            later_words.add(argument.text.lower())
        for item in argument.items or ():
            later_words.add(item.lower())
            later_words.add(re.split(r"[\\/]", item)[-1].lower())
    return any(f"{name} {word}" in subcommands for name in names for word in later_words)


def _has_parameter(command: PowerShellCommand, full_name: str) -> bool:
    """Return True when a parameter abbreviates full_name (PowerShell accepts prefixes)."""
    return any(
        argument.kind == "parameter" and argument.name and full_name.startswith(argument.name.lower())
        for argument in command.arguments
    )
