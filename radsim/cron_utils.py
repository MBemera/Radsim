"""Shared crontab helpers.

RadSim Principle: One source of truth.

`jobs.py` is the only writer of the user crontab, so the primitives for
reading, writing, and escaping entries live here rather than in it.
"""

import platform
import subprocess


def is_windows():
    """Return whether the host uses Windows Task Scheduler instead of cron."""
    return platform.system().lower() == "windows"


def escape_cron_percent(command):
    """Escape bare percent characters without double-escaping existing ones.

    cron treats an unescaped % as end-of-command plus start-of-stdin, which
    would let a job line smuggle input into the command.
    """
    escaped = []
    backslashes = 0
    for character in command:
        if character == "%" and backslashes % 2 == 0:
            escaped.append("\\")
        escaped.append(character)
        backslashes = backslashes + 1 if character == "\\" else 0
    return "".join(escaped)


def read_crontab():
    """Read the current crontab, distinguishing absence from failure.

    Returns:
        The crontab text, or "" when the user simply has no crontab yet.

    Raises:
        RuntimeError when crontab is missing or cannot be read. Callers must
        not overwrite a crontab they could not read.
    """
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except OSError as error:
        raise RuntimeError("crontab is not installed or not accessible") from error

    if result.returncode == 0:
        return result.stdout
    if "no crontab" in result.stderr.lower():
        return ""
    message = result.stderr.strip() or f"crontab exited with status {result.returncode}"
    raise RuntimeError(f"Unable to read existing crontab: {message}")


def write_crontab(content):
    """Replace the user's crontab with the given content."""
    subprocess.run(
        ["crontab", "-"],
        input=content,
        capture_output=True,
        text=True,
        check=True,
    )
