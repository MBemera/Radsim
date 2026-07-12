"""Task scheduler for RadSim Agent.

Provides cron-style scheduling for recurring tasks.
"""

import json
import logging
import platform
import re
import subprocess
from datetime import datetime

from .config import SCHEDULES_FILE
from .jobs import cron_to_windows_schedule, validate_cron_expression
from .terminal import is_unsafe_terminal_character

logger = logging.getLogger(__name__)

# Only allows digits, commas, hyphens, slashes, asterisks, and spaces.
# Plain spaces, not \s: whitespace classes admit newlines, which would let a
# schedule smuggle extra crontab lines.
CRON_SCHEDULE_PATTERN = re.compile(r"^[0-9,\-*/ ]+$")

# Job names land in crontab marker comments, so they must stay on one line
# and contain nothing cron or the shell could reinterpret.
JOB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._\- ]+$")


def validate_cron_schedule(schedule):
    """Validate a cron schedule expression for safe characters only.

    Args:
        schedule: Cron schedule string (e.g., "0 9 * * *")

    Returns:
        True if valid

    Raises:
        ValueError if schedule contains unsafe characters
    """
    if not isinstance(schedule, str):
        raise ValueError("Cron schedule must be a string")

    if not schedule.strip():
        raise ValueError("Cron schedule cannot be empty")

    if not CRON_SCHEDULE_PATTERN.fullmatch(schedule):
        raise ValueError(
            f"Invalid cron schedule: {schedule!r}. "
            "Only digits, commas, hyphens, slashes, asterisks, and spaces are allowed."
        )

    # A cron expression must have exactly 5 fields
    fields = schedule.strip().split()
    if len(fields) != 5:
        raise ValueError(
            f"Cron schedule must have exactly 5 fields (minute hour day month weekday), got {len(fields)}"
        )

    if not validate_cron_expression(schedule):
        raise ValueError(f"Invalid cron schedule values: {schedule!r}")

    return True


def validate_job_name(name):
    """Validate a job name for safe use in a crontab marker comment.

    Args:
        name: Job name string

    Returns:
        The stripped name.

    Raises:
        ValueError if the name is empty or contains unsafe characters.
    """
    if not isinstance(name, str):
        raise ValueError("Job name must be a string")

    if not name.strip():
        raise ValueError("Job name cannot be empty")

    stripped = name.strip()
    if not JOB_NAME_PATTERN.fullmatch(stripped):
        raise ValueError(
            f"Invalid job name: {stripped!r}. "
            "Only letters, digits, spaces, '.', '_' and '-' are allowed."
        )

    return stripped


def sanitize_cron_command(command):
    """Validate a command for safe use in a single cron entry.

    A cron line hands the whole command to /bin/sh, so the command must be
    kept intact (NOT wrapped as one shlex-quoted token, which would make cron
    try to execute the entire string as one program name). We only reject
    control characters that could inject extra crontab lines.

    Args:
        command: Shell command string

    Returns:
        The command, stripped and safe to place on a cron line.

    Raises:
        ValueError if the command is empty or contains control characters.
    """
    if not isinstance(command, str):
        raise ValueError("Cron command must be a string")

    if not command.strip():
        raise ValueError("Cron command cannot be empty")

    if any(is_unsafe_terminal_character(character) for character in command):
        raise ValueError("Cron command must not contain control characters")

    return command.strip()


def validate_job_description(description):
    """Return a display-safe schedule description."""
    if description is None:
        return ""
    if not isinstance(description, str):
        raise ValueError("Job description must be a string")
    if any(is_unsafe_terminal_character(character) for character in description):
        raise ValueError("Job description must not contain control characters")
    return description


def _read_current_crontab():
    """Return crontab text, empty for a verified absence, or None on failure."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except OSError:
        logger.warning("Unable to read crontab")
        return None
    if result.returncode == 0:
        return result.stdout
    if "no crontab" in result.stderr.lower():
        return ""
    logger.warning("Unable to read crontab; refusing to overwrite it")
    return None


def _escape_cron_percent(command):
    """Escape bare percent characters without double-escaping existing ones."""
    escaped = []
    backslashes = 0
    for character in command:
        if character == "%" and backslashes % 2 == 0:
            escaped.append("\\")
        escaped.append(character)
        backslashes = backslashes + 1 if character == "\\" else 0
    return "".join(escaped)


def _is_windows():
    """Return whether the host uses Windows Task Scheduler."""
    return platform.system().lower() == "windows"


def _windows_task_name(name):
    """Return the exact managed Task Scheduler name for one job."""
    return f"RadSim_Schedule_{validate_job_name(name)}"


def _install_windows_task(name, schedule, command):
    """Create or update one noninteractive Windows scheduled task."""
    try:
        schedule_type, schedule_arguments = cron_to_windows_schedule(schedule)
        task_action = subprocess.list2cmdline(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
        )
        arguments = [
            "schtasks", "/create", "/tn", _windows_task_name(name),
            "/tr", task_action, "/sc", schedule_type, *schedule_arguments, "/f",
        ]
        subprocess.run(arguments, capture_output=True, text=True, check=True)
        return True
    except (OSError, subprocess.SubprocessError, ValueError):
        logger.warning("Failed to install Windows scheduled task '%s'", name)
        return False


def _uninstall_windows_task(name):
    """Delete one exact RadSim-managed Windows scheduled task."""
    arguments = ["schtasks", "/delete", "/tn", _windows_task_name(name), "/f"]
    try:
        subprocess.run(arguments, capture_output=True, text=True, check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        logger.warning("Failed to uninstall Windows scheduled task '%s'", name)
        return False


class Scheduler:
    """Cron-style task scheduler."""

    def __init__(self):
        """Initialize the scheduler."""
        self.schedules_file = SCHEDULES_FILE
        self.schedules = self._load_schedules()

    def _load_schedules(self):
        """Load and validate schedules, failing closed on corrupt storage."""
        if not self.schedules_file.exists():
            return {"jobs": []}
        try:
            schedules = json.loads(self.schedules_file.read_text())
            self._validate_schedules(schedules)
            return schedules
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError("Schedules file is invalid; refusing to modify cron") from error

    @staticmethod
    def _validate_schedules(schedules):
        """Validate persisted schedule records before trusting them."""
        if not isinstance(schedules, dict) or not isinstance(schedules.get("jobs"), list):
            raise ValueError("Schedules must contain a jobs list")
        names = set()
        for job in schedules["jobs"]:
            if not isinstance(job, dict):
                raise ValueError("Every schedule must be an object")
            stored_name = job.get("name")
            name = validate_job_name(stored_name)
            if name != stored_name:
                raise ValueError("Persisted schedule names must not have surrounding whitespace")
            if name in names:
                raise ValueError("Schedule names must be unique")
            names.add(name)
            validate_cron_schedule(job.get("schedule"))
            sanitize_cron_command(job.get("command"))
            if not isinstance(job.get("enabled"), bool):
                raise ValueError("Schedule enabled flag must be boolean")
            validate_job_description(job.get("description", ""))

    def _save_schedules(self):
        """Save schedules to file."""
        try:
            self.schedules_file.write_text(json.dumps(self.schedules, indent=2))
            return True
        except OSError:
            return False

    def add_job(self, name, schedule, command, description=None):
        """Add a scheduled job.

        Args:
            name: Unique job name
            schedule: Cron expression (e.g., "0 9 * * *" for 9am daily)
            command: Command to execute
            description: Optional description

        Returns:
            dict with success status
        """
        # Validate name, schedule, and command before anything else
        name = validate_job_name(name)
        validate_cron_schedule(schedule)
        sanitize_cron_command(command)
        description = validate_job_description(description)

        # Check for duplicate name
        for job in self.schedules["jobs"]:
            if job["name"] == name:
                return {"success": False, "error": f"Job '{name}' already exists"}

        job = {
            "name": name,
            "schedule": schedule,
            "command": command,
            "description": description,
            "enabled": True,
            "created_at": datetime.now().isoformat(),
            "last_run": None,
            "run_count": 0,
        }

        self.schedules["jobs"].append(job)
        if not self._save_schedules():
            self.schedules["jobs"].remove(job)
            return {"success": False, "error": "Failed to persist schedule"}
        if self._install_cron(job):
            return {"success": True, "job": job}

        self.schedules["jobs"].remove(job)
        rollback_saved = self._save_schedules()
        error = "Failed to install system cron entry"
        if not rollback_saved:
            error += "; failed to restore schedule storage"
        return {"success": False, "error": error}

    def remove_job(self, name):
        """Remove a scheduled job.

        Args:
            name: Job name to remove

        Returns:
            dict with success status
        """
        name = validate_job_name(name)
        for i, job in enumerate(self.schedules["jobs"]):
            if job["name"] == name:
                removed_job = self.schedules["jobs"].pop(i)
                if not self._save_schedules():
                    self.schedules["jobs"].insert(i, removed_job)
                    return {"success": False, "error": "Failed to persist schedule removal"}
                if self._uninstall_cron(name):
                    return {"success": True, "removed": name}
                self.schedules["jobs"].insert(i, removed_job)
                rollback_saved = self._save_schedules()
                error = "Failed to remove system cron entry"
                if not rollback_saved:
                    error += "; failed to restore schedule storage"
                return {"success": False, "error": error}

        return {"success": False, "error": f"Job '{name}' not found"}

    def list_jobs(self):
        """List all scheduled jobs.

        Returns:
            list: All jobs
        """
        return self.schedules["jobs"]

    def enable_job(self, name, enabled=True):
        """Enable or disable a job.

        Args:
            name: Job name
            enabled: Whether to enable or disable

        Returns:
            dict with success status
        """
        name = validate_job_name(name)
        if not isinstance(enabled, bool):
            raise ValueError("Enabled must be a boolean")
        for job in self.schedules["jobs"]:
            if job["name"] == name:
                previous_enabled = job["enabled"]
                job["enabled"] = enabled
                if not self._save_schedules():
                    job["enabled"] = previous_enabled
                    return {"success": False, "error": "Failed to persist schedule state"}

                changed = self._install_cron(job) if enabled else self._uninstall_cron(name)
                if changed:
                    return {"success": True, "job": name, "enabled": enabled}

                job["enabled"] = previous_enabled
                rollback_saved = self._save_schedules()
                error = "Failed to update system cron entry"
                if not rollback_saved:
                    error += "; failed to restore schedule storage"
                return {"success": False, "error": error}

        return {"success": False, "error": f"Job '{name}' not found"}

    def _install_cron(self, job):
        """Install job to system crontab."""
        if not job["enabled"]:
            return True

        name = validate_job_name(job["name"])
        validate_cron_schedule(job["schedule"])
        safe_command = sanitize_cron_command(job["command"])

        if _is_windows():
            return _install_windows_task(name, job["schedule"], safe_command)

        current_cron = _read_current_crontab()
        if current_cron is None:
            return False

        # Build cron entry with validated schedule and sanitized command.
        # Escape % across the whole command field (marker included): cron
        # treats a bare % as end-of-command and feeds the rest to stdin.
        marker = f"# RADSIM:{name}"
        safe_schedule = job["schedule"].strip()
        command_field = _escape_cron_percent(f"{safe_command} {marker}")
        cron_line = f"{safe_schedule} {command_field}\n"

        # Remove existing entry for this job
        lines = [line for line in current_cron.splitlines() if not line.endswith(marker)]

        # Add new entry
        lines.append(cron_line.strip())
        new_cron = "\n".join(lines) + "\n"

        # Install new crontab
        try:
            subprocess.run(
                ["crontab", "-"], input=new_cron, capture_output=True, text=True, check=True
            )
            return True
        except (OSError, subprocess.SubprocessError):
            logger.warning("Failed to install cron job, cron may not be available")
            return False

    def _uninstall_cron(self, name):
        """Remove job from system crontab."""
        name = validate_job_name(name)
        if _is_windows():
            return _uninstall_windows_task(name)

        current_cron = _read_current_crontab()
        if current_cron is None:
            return False

        marker = f"# RADSIM:{name}"
        lines = [line for line in current_cron.splitlines() if not line.endswith(marker)]
        new_cron = "\n".join(lines) + "\n" if lines else ""
        try:
            subprocess.run(
                ["crontab", "-"], input=new_cron, capture_output=True, text=True, check=True
            )
            return True
        except (OSError, subprocess.SubprocessError):
            logger.warning("Failed to uninstall cron job '%s'", name)
            return False


# =============================================================================
# Tool Functions
# =============================================================================


def schedule_task(name, schedule, command, description=None):
    """Schedule a recurring task.

    Args:
        name: Unique name for the job
        schedule: Cron expression (e.g., "0 9 * * *" for 9am daily)
                  Format: minute hour day-of-month month day-of-week
                  Common examples:
                    - "*/5 * * * *" = every 5 minutes
                    - "0 * * * *" = every hour
                    - "0 9 * * *" = daily at 9am
                    - "0 9 * * 1" = every Monday at 9am
                    - "0 0 1 * *" = 1st of each month
        command: Shell command to execute
        description: Optional description

    Returns:
        dict with success status
    """
    try:
        scheduler = Scheduler()
        result = scheduler.add_job(name, schedule, command, description)
        return result
    except Exception as error:
        return {"success": False, "error": str(error)}


def list_schedules():
    """List all scheduled tasks.

    Returns:
        dict with success status and jobs list
    """
    try:
        scheduler = Scheduler()
        jobs = scheduler.list_jobs()
        return {"success": True, "jobs": jobs, "count": len(jobs)}
    except Exception as error:
        return {"success": False, "error": str(error)}


def remove_schedule(name):
    """Remove a scheduled task.

    Args:
        name: Name of the job to remove

    Returns:
        dict with success status
    """
    try:
        scheduler = Scheduler()
        return scheduler.remove_job(name)
    except Exception as error:
        return {"success": False, "error": str(error)}


def toggle_schedule(name, enabled=True):
    """Enable or disable a scheduled task.

    Args:
        name: Name of the job
        enabled: True to enable, False to disable

    Returns:
        dict with success status
    """
    try:
        scheduler = Scheduler()
        return scheduler.enable_job(name, enabled)
    except Exception as error:
        return {"success": False, "error": str(error)}
