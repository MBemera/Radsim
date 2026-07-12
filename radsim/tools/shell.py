"""Shell execution for RadSim tools.

RadSim Principle: Explicit Over Implicit
"""

import math
import os
import shlex
import signal
import subprocess
import threading

from .constants import (
    MAX_COMMAND_SIZE,
    MAX_ERROR_OUTPUT_SIZE,
    MAX_OUTPUT_SIZE,
    MAX_SHELL_TIMEOUT,
)
from .environment import build_child_environment
from .validation import validate_shell_command


def _resolve_working_dir(working_dir):
    """Validate the requested working directory.

    Returns:
        Tuple of (cwd, error). cwd is the directory to run in; error is a
        message when the directory is invalid.
    """
    if working_dir is None:
        return os.getcwd(), None

    try:
        working_dir = os.fspath(working_dir)
    except TypeError:
        return None, "Working directory must be a non-empty path"

    if not isinstance(working_dir, str) or not working_dir.strip():
        return None, "Working directory must be a non-empty path"

    resolved = os.path.abspath(working_dir)
    if not os.path.isdir(resolved):
        return None, f"Working directory does not exist: {working_dir}"

    return resolved, None


def _truncate(text, limit, label):
    """Return text capped at limit, appending a truncation notice if cut."""
    text = text or ""
    if len(text) > limit:
        return text[:limit] + f"\n... [{label} truncated]"
    return text


class _BoundedOutput:
    """Collect a byte stream without allowing unbounded memory growth."""

    def __init__(self, limit):
        self.limit = limit
        self.data = bytearray()
        self.truncated = False

    def append(self, chunk):
        remaining = self.limit - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])
        if len(chunk) > remaining:
            self.truncated = True

    def render(self, label):
        text = self.data.decode("utf-8", errors="replace")
        if self.truncated:
            return text + f"\n... [{label} truncated]"
        return text


def _drain_stream(stream, output):
    """Drain one subprocess pipe while retaining only bounded output."""
    try:
        while chunk := stream.read(8192):
            output.append(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _start_output_readers(process):
    """Start daemon readers for stdout and stderr."""
    stdout = _BoundedOutput(MAX_OUTPUT_SIZE)
    stderr = _BoundedOutput(MAX_ERROR_OUTPUT_SIZE)
    readers = [
        threading.Thread(target=_drain_stream, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=_drain_stream, args=(process.stderr, stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    return stdout, stderr, readers


def _finish_output_readers(process, readers):
    """Wait briefly for pipe readers and close pipes held by escaped children."""
    for reader in readers:
        reader.join(timeout=1)
    for stream, reader in zip((process.stdout, process.stderr), readers, strict=True):
        if reader.is_alive():
            try:
                stream.close()
            except OSError:
                pass


def _kill_process_group(process):
    """Kill the child's whole process group, falling back to the child alone."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
        return
    except ProcessLookupError:
        return
    except (PermissionError, OSError):
        pass

    try:
        process.kill()
    except ProcessLookupError:
        pass


def _kill_windows_process_tree(process):
    """Terminate a Windows process and descendants with taskkill."""
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        result = None

    if result is not None and result.returncode == 0:
        return

    try:
        process.kill()
    except ProcessLookupError:
        pass


def _kill_process_tree(process):
    """Terminate the platform process tree rooted at process."""
    if os.name == "nt":
        _kill_windows_process_tree(process)
        return
    _kill_process_group(process)


def _reap_process(process):
    """Wait for a killed child, with one final direct-kill fallback."""
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _popen_kwargs(cwd, env):
    """Build platform-specific Popen isolation arguments."""
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": cwd,
        "env": env,
        "bufsize": 0,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _execute(shell_cmd, timeout, cwd, env):
    """Run argv with bounded output and process-tree cleanup on timeout.

    On POSIX the child runs as its own session leader, so RadSim's terminal
    signals don't leak into it and a timeout kills the whole group.
    subprocess.run alone would kill only the direct shell and orphan any
    grandchildren it had spawned.

    Returns:
        subprocess.CompletedProcess with decoded, bounded output.

    Raises:
        subprocess.TimeoutExpired when the command exceeds the timeout.
    """
    process = subprocess.Popen(shell_cmd, **_popen_kwargs(cwd, env))
    stdout, stderr, readers = _start_output_readers(process)
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(process)
        _reap_process(process)
    finally:
        _finish_output_readers(process, readers)

    if timed_out:
        raise subprocess.TimeoutExpired(shell_cmd, timeout)
    return subprocess.CompletedProcess(
        shell_cmd,
        process.returncode,
        stdout.render("Output"),
        stderr.render("Error output"),
    )


def _validate_timeout(timeout):
    """Return a safe numeric timeout or an error message."""
    if isinstance(timeout, bool):
        return None, "Timeout must be a number of seconds"
    try:
        seconds = float(timeout)
    except (TypeError, ValueError):
        return None, "Timeout must be a number of seconds"
    if not math.isfinite(seconds) or seconds <= 0:
        return None, "Timeout must be greater than zero"
    if seconds > MAX_SHELL_TIMEOUT:
        return None, f"Timeout cannot exceed {MAX_SHELL_TIMEOUT} seconds"
    return seconds, None


def _format_result(result):
    """Convert CompletedProcess into the public tool result shape."""
    return {
        "success": result.returncode == 0,
        "stdout": _truncate(result.stdout, MAX_OUTPUT_SIZE, "Output"),
        "stderr": _truncate(result.stderr, MAX_ERROR_OUTPUT_SIZE, "Error output"),
        "returncode": result.returncode,
    }


def format_process_command(arguments):
    """Return argv as a platform-appropriate display string."""
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def quote_shell_argument(value):
    """Quote one literal argument for the shell used on this platform."""
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("Shell arguments must be strings without null bytes")
    if os.name == "nt":
        return "'" + value.replace("'", "''") + "'"
    return shlex.quote(value)


def _validate_arguments(arguments):
    """Return a normalized argv list or an error message."""
    if not isinstance(arguments, (list, tuple)) or not arguments:
        return None, "Process arguments must be a non-empty list"
    if any(not isinstance(argument, str) or not argument for argument in arguments):
        return None, "Every process argument must be a non-empty string"
    if any("\x00" in argument for argument in arguments):
        return None, "Null bytes are forbidden in process arguments"
    if sum(len(argument) for argument in arguments) > MAX_COMMAND_SIZE:
        return None, f"Process arguments exceed the {MAX_COMMAND_SIZE}-character limit"
    return list(arguments), None


def run_process(arguments, timeout=120, working_dir=None):
    """Execute trusted program arguments without a command shell."""
    arguments, error = _validate_arguments(arguments)
    if error:
        return {"success": False, "error": error}

    return _run_arguments(arguments, timeout, working_dir)


def _run_arguments(arguments, timeout, working_dir):
    """Execute validated argv and return the public result shape."""
    timeout, error = _validate_timeout(timeout)
    if error:
        return {"success": False, "error": error}
    cwd, error = _resolve_working_dir(working_dir)
    if error:
        return {"success": False, "error": error}
    try:
        result = _execute(
            arguments,
            timeout=timeout,
            cwd=cwd,
            env=build_child_environment(),
        )
        return _format_result(result)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout:g} seconds"}
    except Exception as error:
        return {"success": False, "error": str(error)}


def run_shell_command(command, timeout=120, working_dir=None):
    """Execute a shell command.

    Args:
        command: Command to execute
        timeout: Timeout in seconds (default: 120)
        working_dir: Working directory (default: current)

    Returns:
        dict with success, stdout, stderr, returncode
    """
    is_valid, error = validate_shell_command(command)
    if not is_valid:
        return {"success": False, "error": error}

    if os.name == "nt":
        arguments = ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        arguments = ["bash", "--noprofile", "--norc", "-c", command]
    return _run_arguments(arguments, timeout, working_dir)
