"""User-defined lifecycle hooks: shell commands that run on agent events.

Hooks live in ~/.radsim/hooks.json and are managed with /hook. Each hook
names an event, a tool-name matcher, and a shell command. The command
receives a JSON payload on stdin and reports through its exit code:

- exit 0: allow the action to proceed
- exit 2: block the action (pre_tool only); stderr becomes the reason

Security model — hooks can only tighten, never loosen:
- A hook can block a tool call; nothing a hook does can approve one,
  skip a confirmation, or bypass command validation.
- Hook commands pass validate_shell_command when added AND before every
  run, so hand-editing hooks.json cannot smuggle in a blocked command.
- A pre_tool hook that cannot run (invalid, crashed, timed out) blocks
  the action: a gate that fails must fail closed. Observe-only events
  (post_tool, session_*, on_error) warn and continue instead.
- Hook subprocesses run with the secret-scrubbed child environment.

In-process hooks registered through radsim.hooks (get_hooks_manager)
fire at the same points, before the JSON-defined hooks.
"""

import fnmatch
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

HOOKS_FILE = Path.home() / ".radsim" / "hooks.json"

VALID_EVENTS = ("pre_tool", "post_tool", "session_start", "session_end", "on_error")
BLOCKING_EVENTS = ("pre_tool",)
TOOL_EVENTS = ("pre_tool", "post_tool", "on_error")

MAX_USER_HOOKS = 20
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 120
DEFAULT_TIMEOUT_SECONDS = 10
MAX_REASON_CHARS = 300
MAX_PAYLOAD_VALUE_CHARS = 2000

HOOK_NAME_MAX_LENGTH = 40
HOOK_MATCHER_MAX_LENGTH = 80


@dataclass
class UserHook:
    """One persisted hook definition."""

    name: str
    event: str
    matcher: str
    command: str
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    enabled: bool = True


def _is_valid_hook_name(name):
    if not name or len(name) > HOOK_NAME_MAX_LENGTH:
        return False
    return all(ch.isalnum() or ch in "-_" for ch in name)


def validate_hook_definition(name, event, matcher, command, timeout):
    """Validate every field of a hook before it is saved or run.

    Returns:
        Tuple of (is_valid, error_message).
    """
    from .tools.validation import validate_shell_command

    if not _is_valid_hook_name(name):
        return False, (
            f"Invalid hook name: use 1-{HOOK_NAME_MAX_LENGTH} letters, "
            "digits, '-' or '_'"
        )
    if event not in VALID_EVENTS:
        return False, f"Invalid event '{event}'. Valid: {', '.join(VALID_EVENTS)}"
    if not matcher or len(matcher) > HOOK_MATCHER_MAX_LENGTH:
        return False, f"Matcher must be 1-{HOOK_MATCHER_MAX_LENGTH} characters"
    if any(not (ch.isprintable()) for ch in matcher):
        return False, "Matcher cannot contain control characters"
    if not isinstance(timeout, int) or not (
        MIN_TIMEOUT_SECONDS <= timeout <= MAX_TIMEOUT_SECONDS
    ):
        return False, (
            f"Timeout must be an integer between {MIN_TIMEOUT_SECONDS} "
            f"and {MAX_TIMEOUT_SECONDS} seconds"
        )

    command_ok, command_error = validate_shell_command(command)
    if not command_ok:
        return False, f"Hook command rejected: {command_error}"
    return True, None


def load_user_hooks():
    """Load hooks from disk, silently skipping entries that fail validation."""
    if not HOOKS_FILE.exists():
        return []
    try:
        raw_entries = json.loads(HOOKS_FILE.read_text())
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Could not read %s: %s", HOOKS_FILE, error)
        return []
    if not isinstance(raw_entries, list):
        logger.warning("%s must contain a JSON list; ignoring it", HOOKS_FILE)
        return []

    hooks = []
    for entry in raw_entries[:MAX_USER_HOOKS]:
        hook = _parse_hook_entry(entry)
        if hook:
            hooks.append(hook)
    return hooks


def _parse_hook_entry(entry):
    """Build a UserHook from one JSON entry, or None if it is malformed."""
    if not isinstance(entry, dict):
        return None
    try:
        hook = UserHook(
            name=str(entry["name"]),
            event=str(entry["event"]),
            matcher=str(entry.get("matcher", "*")),
            command=str(entry["command"]),
            timeout=int(entry.get("timeout", DEFAULT_TIMEOUT_SECONDS)),
            enabled=bool(entry.get("enabled", True)),
        )
    except (KeyError, TypeError, ValueError):
        logger.warning("Skipping malformed hook entry in %s", HOOKS_FILE)
        return None

    is_valid, error = validate_hook_definition(
        hook.name, hook.event, hook.matcher, hook.command, hook.timeout
    )
    if not is_valid:
        logger.warning("Skipping invalid hook '%s': %s", hook.name, error)
        return None
    return hook


def save_user_hooks(hooks):
    """Persist the full hook list to disk."""
    HOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOOKS_FILE.write_text(json.dumps([asdict(hook) for hook in hooks], indent=2) + "\n")


def add_user_hook(name, event, matcher, command, timeout=DEFAULT_TIMEOUT_SECONDS):
    """Validate and persist a new hook.

    Returns:
        Dict with success status and the saved hook or an error.
    """
    is_valid, error = validate_hook_definition(name, event, matcher, command, timeout)
    if not is_valid:
        return {"success": False, "error": error}

    hooks = load_user_hooks()
    if len(hooks) >= MAX_USER_HOOKS:
        return {"success": False, "error": f"Hook limit reached ({MAX_USER_HOOKS})"}
    if any(hook.name == name for hook in hooks):
        return {"success": False, "error": f"A hook named '{name}' already exists"}

    # Session events have no tool to match; store "*" so the list is honest.
    if event not in TOOL_EVENTS:
        matcher = "*"

    hook = UserHook(name=name, event=event, matcher=matcher, command=command, timeout=timeout)
    hooks.append(hook)
    save_user_hooks(hooks)
    return {"success": True, "hook": asdict(hook)}


def remove_user_hook(name):
    """Delete a hook by name."""
    hooks = load_user_hooks()
    remaining = [hook for hook in hooks if hook.name != name]
    if len(remaining) == len(hooks):
        return {"success": False, "error": f"No hook named '{name}'"}
    save_user_hooks(remaining)
    return {"success": True}


def set_user_hook_enabled(name, enabled):
    """Enable or disable a hook without deleting it."""
    hooks = load_user_hooks()
    for hook in hooks:
        if hook.name == name:
            hook.enabled = enabled
            save_user_hooks(hooks)
            return {"success": True, "enabled": enabled}
    return {"success": False, "error": f"No hook named '{name}'"}


def _compact_payload_value(value):
    """Bound payload values so hooks never receive huge stdin blobs."""
    if isinstance(value, str) and len(value) > MAX_PAYLOAD_VALUE_CHARS:
        return value[:MAX_PAYLOAD_VALUE_CHARS] + "...(truncated)"
    return value


def _build_payload(event, tool_name, extra):
    payload = {"event": event, "tool_name": tool_name}
    for key, value in (extra or {}).items():
        if isinstance(value, dict):
            payload[key] = {k: _compact_payload_value(v) for k, v in value.items()}
        else:
            payload[key] = _compact_payload_value(value)
    return payload


def _sanitize_reason(text):
    """Keep hook stderr printable so it cannot inject terminal controls."""
    printable = "".join(ch for ch in text if ch.isprintable() or ch in " \t\n")
    return " ".join(printable.split())[:MAX_REASON_CHARS]


def _run_hook_command(hook, payload):
    """Run one hook subprocess.

    Returns:
        Tuple of (outcome, reason) where outcome is "allow", "block",
        or "failed".
    """
    from .tools.environment import build_child_environment
    from .tools.validation import validate_shell_command

    # Re-validate at run time: hooks.json is user-editable on disk.
    command_ok, command_error = validate_shell_command(hook.command)
    if not command_ok:
        return "failed", f"command failed validation: {command_error}"

    try:
        completed = subprocess.run(
            hook.command,
            shell=True,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=hook.timeout,
            env=build_child_environment(),
            start_new_session=True,
        )
    except subprocess.TimeoutExpired:
        return "failed", f"timed out after {hook.timeout}s"
    except OSError as error:
        return "failed", str(error)

    if completed.returncode == 0:
        return "allow", completed.stdout or ""
    if completed.returncode == 2:
        return "block", _sanitize_reason(completed.stderr or "exit code 2 (no reason on stderr)")
    return "failed", f"exited with code {completed.returncode}"


def _hook_matches(hook, event, tool_name):
    """Session events always match — there is no tool name to glob against."""
    if hook.event != event:
        return False
    if event in TOOL_EVENTS:
        return fnmatch.fnmatchcase(tool_name, hook.matcher)
    return True


def _print_hook_output(name, stdout):
    """Show a hook's first output lines so the user can see it fired."""
    from .output import print_info

    lines = [line for line in (stdout or "").strip().splitlines() if line.strip()][:3]
    for line in lines:
        print_info(f"hook {name}: {_sanitize_reason(line)}")


def fire_hooks(event, tool_name="", extra=None):
    """Run every enabled hook matching this event and tool name.

    Blocking events fail closed: a matching pre_tool hook that blocks or
    fails stops the action. Observe-only events warn and continue.

    Returns:
        Tuple of (should_proceed, reason).
    """
    from .output import print_warning

    payload = None
    for hook in load_user_hooks():
        if not hook.enabled or not _hook_matches(hook, event, tool_name):
            continue
        if payload is None:
            payload = _build_payload(event, tool_name, extra)

        outcome, detail = _run_hook_command(hook, payload)
        if outcome == "allow":
            _print_hook_output(hook.name, detail)
            continue
        if event in BLOCKING_EVENTS:
            if outcome == "failed":
                detail = f"hook could not run ({detail}) — failing closed"
            return False, f"hook '{hook.name}': {detail}"
        print_warning(f"Hook '{hook.name}' failed: {detail}")

    return True, None


def fire_tool_hooks(event, tool_name, tool_input, result=None):
    """Fire in-process hooks, then JSON-defined hooks, for one tool call.

    Returns:
        Tuple of (should_proceed, reason).
    """
    from .hooks import HookContext, HookType, get_hooks_manager

    hook_type = HookType.PRE_TOOL if event == "pre_tool" else HookType.POST_TOOL
    context = get_hooks_manager().execute(
        hook_type,
        HookContext(
            hook_type=hook_type,
            tool_name=tool_name,
            tool_input=tool_input if isinstance(tool_input, dict) else {},
            tool_result=result if isinstance(result, dict) else {},
        ),
    )
    if not context.should_proceed:
        reason = (
            context.metadata.get("validation_error")
            or context.metadata.get("hook_error")
            or "blocked by in-process hook"
        )
        return False, _sanitize_reason(str(reason))

    extra = {"tool_input": tool_input if isinstance(tool_input, dict) else {}}
    if event == "post_tool" and isinstance(result, dict):
        extra["success"] = bool(result.get("success"))
        extra["error"] = str(result.get("error", ""))[:MAX_REASON_CHARS]
    return fire_hooks(event, tool_name=tool_name, extra=extra)


def fire_session_hooks(event, provider="", model=""):
    """Fire session lifecycle hooks. Never blocks."""
    import os

    fire_hooks(event, tool_name="", extra={"cwd": os.getcwd(), "provider": provider, "model": model})


def fire_error_hooks(tool_name, error_type, error_message):
    """Fire on_error hooks after a tool crash. Never blocks."""
    from .hooks import HookContext, HookType, get_hooks_manager

    get_hooks_manager().execute(
        HookType.ON_ERROR,
        HookContext(
            hook_type=HookType.ON_ERROR,
            tool_name=tool_name,
            metadata={
                "error_type": str(error_type)[:MAX_REASON_CHARS],
                "error_message": str(error_message)[:MAX_REASON_CHARS],
            },
        ),
    )
    fire_hooks(
        "on_error",
        tool_name=tool_name,
        extra={"error_type": error_type, "error_message": str(error_message)[:MAX_REASON_CHARS]},
    )
