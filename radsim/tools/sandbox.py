"""Confine agent shell commands with the macOS seatbelt sandbox.

RadSim Principle: Explicit Over Implicit.

The request classifier can only judge the command string it is handed.
``pytest -q`` is routine, but the test code it then runs is arbitrary and
executes with the user's full permissions — a fixture calling
``shutil.rmtree`` never produces a command string for any rule to match.

This module wraps auto-mode shell commands in the macOS sandbox so that
filesystem writes stay inside the working directory and known build caches
whatever the child process attempts. Only writes are restricted: reads,
network access and process execution are untouched, so ordinary inspection
and verification commands keep working.
"""

import logging
import os
import shutil
import sys
import tempfile

logger = logging.getLogger(__name__)

SANDBOX_EXECUTABLE = "sandbox-exec"

# Build tools write outside the project by design. Each entry is expanded
# against the user's home directory and allowed only when it already exists,
# so an unused toolchain never widens the sandbox.
WRITABLE_CACHE_PATHS = (
    "~/Library/Caches",
    "~/.cache",
    "~/.npm",
    "~/.cargo",
    "~/.rustup",
    "~/.gradle",
    "~/.m2",
    "~/go/pkg/mod",
)

# Device nodes ordinary pipelines need. Listed individually because the whole
# of /dev includes raw disks, which is exactly what the sandbox must deny.
WRITABLE_DEVICE_FILES = (
    "/dev/null",
    "/dev/zero",
    "/dev/random",
    "/dev/urandom",
    "/dev/tty",
    "/dev/stdout",
    "/dev/stderr",
    "/dev/ptmx",
)

WRITABLE_DEVICE_DIRECTORIES = ("/dev/fd",)

_auto_mode_enabled = False


def set_auto_mode(enabled):
    """Record whether RadSim started in auto mode for this process.

    Called once from the CLI with the value of ``--yes``. The setting is a
    startup property of the session, so the model cannot reach it through
    tool input and cannot turn its own sandbox off.
    """
    global _auto_mode_enabled
    _auto_mode_enabled = bool(enabled)


def auto_mode_enabled():
    """True when RadSim is running in auto mode."""
    return _auto_mode_enabled


def sandbox_available():
    """True when this platform can confine child processes with seatbelt."""
    return sys.platform == "darwin" and shutil.which(SANDBOX_EXECUTABLE) is not None


def sandbox_requested():
    """True when the user's settings ask for auto-mode sandboxing."""
    try:
        from ..agent_config import get_agent_config_manager

        return bool(get_agent_config_manager().get("sandbox.auto_mode", True))
    except Exception:
        logger.warning("Sandbox setting could not be read; keeping the sandbox on")
        return True


def sandbox_enabled():
    """True when the next shell command should run confined."""
    if not _auto_mode_enabled:
        return False
    if not sandbox_requested():
        return False
    if not sandbox_available():
        logger.warning(
            "Auto-mode sandboxing needs macOS %s; commands run unconfined",
            SANDBOX_EXECUTABLE,
        )
        return False
    return True


def _quote_profile_path(path):
    """Escape one filesystem path for use inside a sandbox profile."""
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _existing_real_directories(candidates):
    """Resolve candidate directories to existing real paths, without duplicates."""
    resolved = []
    for candidate in candidates:
        real_path = os.path.realpath(os.path.expanduser(candidate))
        if real_path == os.sep:
            continue
        if os.path.isdir(real_path) and real_path not in resolved:
            resolved.append(real_path)
    return resolved


def writable_directories(working_dir):
    """List the directories a confined command may write to.

    Symlinks are resolved because the sandbox matches real paths: on macOS
    /tmp is a symlink to /private/tmp, and a rule naming /tmp would never fire.
    """
    candidates = [
        working_dir,
        tempfile.gettempdir(),
        "/private/tmp",
        "/private/var/tmp",
        *WRITABLE_CACHE_PATHS,
    ]
    return _existing_real_directories(candidates)


def build_sandbox_profile(working_dir):
    """Build a seatbelt profile denying writes outside the allowed paths.

    Later rules win in seatbelt, so the blanket deny comes before the
    allowances that carve exceptions out of it.
    """
    lines = ["(version 1)", "(allow default)", "(deny file-write*)"]
    for path in writable_directories(working_dir):
        lines.append(f"(allow file-write* (subpath {_quote_profile_path(path)}))")
    for path in WRITABLE_DEVICE_DIRECTORIES:
        lines.append(f"(allow file-write* (subpath {_quote_profile_path(path)}))")
    for path in WRITABLE_DEVICE_FILES:
        lines.append(f"(allow file-write* (literal {_quote_profile_path(path)}))")
    return "\n".join(lines)


def wrap_shell_arguments(arguments, working_dir):
    """Return argv confined by the sandbox, or unchanged when not sandboxing."""
    if not sandbox_enabled():
        return arguments
    profile = build_sandbox_profile(working_dir)
    return [SANDBOX_EXECUTABLE, "-p", profile, *arguments]
