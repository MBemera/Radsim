"""Safety guardrails and confirmations for RadSim Agent."""

import logging
import os
import select
import sys
from pathlib import Path

from .terminal import escape_terminal_controls

logger = logging.getLogger(__name__)


# Commands that trigger immediate process termination from any prompt
STOP_COMMANDS = {"/stop", "/kill", "/abort"}

# Module-level callback for Telegram confirmation forwarding.
# When set, confirm_action/confirm_write use this instead of terminal input().
_telegram_confirm_fn = None


def set_telegram_confirm(fn):
    """Set or clear the Telegram confirmation callback.

    Args:
        fn: Callable that takes a prompt string and returns True/False,
            or None to disable Telegram confirmation.
    """
    global _telegram_confirm_fn
    _telegram_confirm_fn = fn


def _emergency_stop():
    """Immediately terminate the process."""
    print("\n  EMERGENCY STOP EMERGENCY STOP - Terminating immediately!")
    os._exit(1)


def _flush_stdin_buffer():
    """Discard buffered terminal input before showing a blocking prompt."""
    try:
        while select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.read(1)
    except Exception:
        logger.debug("Draining buffered stdin failed", exc_info=True)


def _prompt_for_confirmation(prompt: str) -> str:
    """Show a blocking confirmation prompt in a terminal-safe way."""
    from .escape_listener import pause_escape_listener, resume_escape_listener

    pause_escape_listener()
    try:
        _flush_stdin_buffer()
        safe_prompt = escape_terminal_controls(prompt)
        print(f"\n{safe_prompt}", end="", flush=True)
        return input().strip()
    except (KeyboardInterrupt, EOFError):
        print()
        raise
    finally:
        resume_escape_listener()


# Patterns that should never be written
DANGEROUS_PATTERNS = [
    ".env",
    "credentials",
    "secrets",
    ".git/config",
    "id_rsa",
    "id_ed25519",
    ".pem",
    "password",
]

# File extensions that are safe to write
SAFE_EXTENSIONS = [
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".rb",
    ".java",
    ".kt",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".html",
    ".css",
    ".scss",
    ".sass",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".md",
    ".txt",
    ".rst",
    ".vue",
    ".svelte",
]


def is_self_modification(file_path):
    """Check if a file path is within RadSim's own source directory.

    Returns:
        (is_self_mod: bool, package_dir: Path or None)
    """
    try:
        from .config import PACKAGE_DIR

        target = Path(file_path).resolve()
        source_dir = PACKAGE_DIR.resolve()
        return str(target).startswith(str(source_dir)), source_dir
    except Exception:
        return False, None


# Source files that carry RadSim's own policy. A runtime tool call may never
# write to these: a content sentinel only proves some text survived the edit,
# while the real risk is a rewrite that keeps the opening line and guts the
# rules below it. The boundary is the path, so no proposed content can argue
# its way past it.
CORE_POLICY_FILENAMES = frozenset(
    {
        "prompts.py",
        "safety.py",
        "agent_policy.py",
        "sub_agent_policy.py",
        "sub_agent_profiles.py",
        "agent_constants.py",
        "access_control.py",
    }
)

# Checked-in prompt text the user may change through an explicit request.
# These shape behaviour; they do not define permissions.
EDITABLE_PROMPT_FRAGMENTS = frozenset(
    {
        "personality.md",
        "tool_use.md",
        "response_style.md",
        "subagents.md",
    }
)


def is_core_policy_path(file_path):
    """Check whether a path is a protected core policy file.

    Only files inside RadSim's own package count: a project file that happens
    to be named ``safety.py`` is ordinary user code and stays editable.

    Returns:
        (is_core: bool, reason: str)
    """
    is_selfmod, _package_dir = is_self_modification(file_path)
    if not is_selfmod:
        return False, ""

    try:
        target = Path(file_path).resolve()
    except (OSError, ValueError):
        return False, ""

    if target.parent.name == "prompt_fragments":
        if target.name in EDITABLE_PROMPT_FRAGMENTS:
            return False, ""
        return True, (
            f"BLOCKED: '{target.name}' is not an editable prompt fragment. "
            f"Editable fragments: {', '.join(sorted(EDITABLE_PROMPT_FRAGMENTS))}."
        )

    if target.name in CORE_POLICY_FILENAMES:
        return True, (
            f"BLOCKED: '{target.name}' is a RadSim core policy file and cannot be "
            "edited by a runtime tool call. Change it through a reviewed source edit."
        )

    return False, ""


def is_core_prompt_intact(new_content):
    """Check that the core system prompt is preserved in proposed content.

    Retained as a defence in depth behind :func:`is_core_policy_path`, which
    already blocks runtime writes to ``prompts.py`` outright. Checks that the
    sentinel (first 100 chars) is still present.

    Returns:
        (intact: bool, reason: str)
    """
    try:
        from .prompts import RADSIM_SYSTEM_PROMPT

        sentinel = RADSIM_SYSTEM_PROMPT[:100]
        if sentinel in new_content:
            return True, "Core prompt intact"
        return False, "BLOCKED: This edit would remove the core system prompt (RADSIM_SYSTEM_PROMPT)"
    except Exception:
        return False, "Could not verify core prompt integrity"


def is_path_safe(file_path):
    """Check if a file path is safe to write to."""
    path_lower = file_path.lower()

    # Check for dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if pattern in path_lower:
            return False, f"Cannot write to files matching '{pattern}'"

    return True, None


def is_extension_safe(file_path):
    """Check if file extension is in the safe list."""
    path = Path(file_path)
    extension = path.suffix.lower()

    if not extension:
        return True, None  # No extension is okay (like Makefile)

    if extension in SAFE_EXTENSIONS:
        return True, None

    return False, f"Uncommon file extension: {extension}"


def _should_auto_confirm_write(file_path, config):
    """Return whether the trust bandit can skip a write prompt."""
    try:
        from .trust_bandit_integration import should_auto_confirm_action

        return should_auto_confirm_action("write_file", {"file_path": file_path}, config=config)
    except Exception:
        return False, "trust_unavailable"


def _record_write_decision(file_path, accepted, config):
    """Record a write prompt decision if trust learning is enabled."""
    try:
        from .trust_bandit_integration import record_user_decision

        record_user_decision("write_file", {"file_path": file_path}, accepted, config=config)
    except Exception:
        logger.warning("Write decision was not recorded for trust learning", exc_info=True)


def confirm_write(file_path, content, config=None):
    """Ask user to confirm a file write operation."""
    display_file_path = escape_terminal_controls(file_path)
    display_content = escape_terminal_controls(content, preserve_layout=True)

    # Check safety first, even in auto mode
    safe, reason = is_path_safe(file_path)
    if not safe:
        print(f"\nwarning:  BLOCKED: {escape_terminal_controls(reason)}")
        return False

    if config and config.auto_confirm:
        print(f"  > Auto-writing: {display_file_path}")
        return True

    # Check extension before any learned auto-confirm shortcut.
    ext_safe, ext_reason = is_extension_safe(file_path)
    if not ext_safe:
        print(f"\nwarning:  Warning: {escape_terminal_controls(ext_reason)}")

    if ext_safe:
        auto_confirm, reason = _should_auto_confirm_write(file_path, config)
        if auto_confirm:
            safe_reason = escape_terminal_controls(reason)
            print(f"  > Auto-writing (trusted): {display_file_path} ({safe_reason})")
            return True

    # Telegram confirmation mode — send summary instead of terminal prompt
    if _telegram_confirm_fn:
        line_count = len(content.splitlines())
        summary = f"Write file: {display_file_path} ({line_count} lines)"
        confirmed = _telegram_confirm_fn(summary)
        _record_write_decision(file_path, confirmed, config)
        return confirmed

    # Show preview - use teach-aware display when teach mode is active
    teach_active = False
    try:
        from .modes import is_mode_active
        teach_active = is_mode_active("teach")
    except Exception:
        logger.debug("Teach-mode lookup failed; showing the plain preview", exc_info=True)

    if teach_active:
        from .output import print_code_content
        print()
        print_code_content(
            display_content,
            display_file_path,
            max_lines=50,
            collapsed=False,
            highlight_teach=True,
        )
    else:
        print(f"\nFile: {display_file_path}")
        print("-" * 50)

        # Show content preview (first 30 lines)
        lines = display_content.split("\n")
        preview_lines = lines[:30]
        print("\n".join(preview_lines))

        if len(lines) > 30:
            print(f"\n... ({len(lines) - 30} more lines)")

        print("-" * 50)

    # Check if file exists
    if Path(file_path).exists():
        print("warning: This will OVERWRITE the existing file!")

    # Ask for confirmation - loop to allow 's' to show full code first
    try:
        while True:
            # Check if teach mode is active for the prompt hint
            show_hint = ""
            try:
                from .modes import is_mode_active
                if is_mode_active("teach"):
                    show_hint = "/s=show all"
            except Exception:
                logger.debug("Teach-mode lookup failed; hiding the show-all hint", exc_info=True)

            prompt_options = "[y/n/all]" if not show_hint else f"[y/n/all/{show_hint}]"
            response = _prompt_for_confirmation(f"Write this file? {prompt_options}: ")

            # Check for emergency stop commands
            if response.lower() in STOP_COMMANDS:
                _emergency_stop()

            # Handle Shift+Tab (\x1b[Z)
            if "\x1b[Z" in response:
                response = "all"

            response_lower = response.lower()

            # Handle 's' - show full code and re-prompt
            if response_lower == "s":
                from .output import print_code_content
                print()
                print_code_content(
                    display_content,
                    display_file_path,
                    max_lines=0,  # Show ALL lines
                    collapsed=False,
                    highlight_teach=True,
                )
                print()
                continue  # Re-prompt for y/n/all

            if response_lower in ["y", "yes"]:
                _record_write_decision(file_path, True, config)
                return True

            if response_lower in ["a", "all", "always"]:
                if config:
                    config.auto_confirm = True
                    print("  ok Auto-confirm enabled (dangerous actions will still prompt)")
                _record_write_decision(file_path, True, config)
                return True

            _record_write_decision(file_path, False, config)
            return False
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        _record_write_decision(file_path, False, config)
        return False


def ask_confirmation(message, offer_all=False):
    """Prompt for a decision and return "yes", "no", or "all".

    "all" is offered and accepted only when the caller can actually
    honor it — the prompt suffix always matches what an answer does.

    Returns:
        "yes", "no", or "all" (only when offer_all is True).
    """
    # Telegram confirmation mode
    if _telegram_confirm_fn:
        return "yes" if _telegram_confirm_fn(message) else "no"

    suffix = "[y/n/all]" if offer_all else "[y/n]"
    try:
        response = _prompt_for_confirmation(f"{message} {suffix}: ")

        # Check for emergency stop commands
        if response.lower() in STOP_COMMANDS:
            _emergency_stop()

        # Handle Shift+Tab (\x1b[Z)
        if offer_all and "\x1b[Z" in response:
            response = "all"

        response = response.lower()

        if response in ["y", "yes"]:
            return "yes"

        if offer_all and response in ["a", "all", "always"]:
            return "all"

        return "no"
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return "no"


def confirm_action(message, config=None):
    """Ask user to confirm an action.

    "all" is only offered when a config is present to persist it —
    otherwise the prompt shows [y/n] so it never promises an
    auto-confirm it cannot deliver.
    """
    if config and config.auto_confirm:
        return True

    answer = ask_confirmation(message, offer_all=bool(config))

    if answer == "all":
        config.auto_confirm = True
        print("  ok Auto-confirm enabled (dangerous actions will still prompt)")

    return answer in ("yes", "all")
