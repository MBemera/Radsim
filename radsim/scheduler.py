"""Task scheduler for RadSim Agent.

Provides cron-style scheduling for recurring tasks.
"""

import json
import logging
import re
import shlex
import subprocess
from datetime import datetime

from .config import SCHEDULES_FILE

logger = logging.getLogger(__name__)

# Only allows digits, commas, hyphens, slashes, asterisks, and whitespace
CRON_SCHEDULE_PATTERN = re.compile(r"^[0-9,\-\*/\s]+$")


def validate_cron_schedule(schedule):
    """Validate a cron schedule expression for safe characters only.

    Args:
        schedule: Cron schedule string (e.g., "0 9 * * *")

    Returns:
        True if valid

    Raises:
        ValueError if schedule contains unsafe characters
    """
    if not schedule or not schedule.strip():
        raise ValueError("Cron schedule cannot be empty")

    if not CRON_SCHEDULE_PATTERN.match(schedule):
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

    return True


def sanitize_cron_command(command):
    """Sanitize a command for safe use in a cron entry.

    Args:
        command: Shell command string

    Returns:
        Shell-escaped command string safe for cron

    Raises:
        ValueError if command is empty
    """
    if not command or not command.strip():
        raise ValueError("Cron command cannot be empty")

    return shlex.quote(command)


class Scheduler:
    """Cron-style task scheduler."""

    def __init__(self):
        """Initialize the scheduler."""
        self.schedules_file = SCHEDULES_FILE
        self.schedules = self._load_schedules()

    def _load_schedules(self):
        """Load schedules from file."""
        if self.schedules_file.exists():
            try:
                return json.loads(self.schedules_file.read_text())
            except (OSError, json.JSONDecodeError):
                return {"jobs": []}
        return {"jobs": []}

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
        # Validate schedule and command before anything else
        validate_cron_schedule(schedule)
        sanitize_cron_command(command)

        # Check for duplicate name
        for job in self.schedules["jobs"]:
            if job["name"] == name:
                return {"success": False, "error": f"Job '{name}' already exists"}

        job = {
            "name": name,
            "schedule": schedule,
            "command": command,
            "description": description or "",
            "enabled": True,
            "created_at": datetime.now().isoformat(),
            "last_run": None,
            "run_count": 0,
        }

        self.schedules["jobs"].append(job)

        if self._save_schedules():
            # Install to system crontab
            self._install_cron(job)
            return {"success": True, "job": job}
        return {"success": False, "error": "Failed to save schedule"}

    def remove_job(self, name):
        """Remove a scheduled job.

        Args:
            name: Job name to remove

        Returns:
            dict with success status
        """
        for i, job in enumerate(self.schedules["jobs"]):
            if job["name"] == name:
                self.schedules["jobs"].pop(i)
                self._save_schedules()
                self._uninstall_cron(name)
                return {"success": True, "removed": name}

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
        for job in self.schedules["jobs"]:
            if job["name"] == name:
                job["enabled"] = enabled
                self._save_schedules()
                if enabled:
                    self._install_cron(job)
                else:
                    self._uninstall_cron(name)
                return {"success": True, "job": name, "enabled": enabled}

        return {"success": False, "error": f"Job '{name}' not found"}

    def _install_cron(self, job):
        """Install job to system crontab."""
        if not job["enabled"]:
            return

        # Get current crontab
        try:
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            current_cron = result.stdout if result.returncode == 0 else ""
        except Exception:
            current_cron = ""

        # Build cron entry with validated schedule and sanitized command
        marker = f"# RADSIM:{job['name']}"
        safe_schedule = job["schedule"].strip()
        safe_command = sanitize_cron_command(job["command"])
        cron_line = f"{safe_schedule} {safe_command} {marker}\n"

        # Remove existing entry for this job
        lines = [line for line in current_cron.splitlines() if marker not in line]

        # Add new entry
        lines.append(cron_line.strip())
        new_cron = "\n".join(lines) + "\n"

        # Install new crontab
        try:
            proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
            proc.communicate(new_cron)
        except Exception:
            logger.warning("Failed to install cron job, cron may not be available")

    def _uninstall_cron(self, name):
        """Remove job from system crontab."""
        try:
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            if result.returncode != 0:
                return

            marker = f"# RADSIM:{name}"
            lines = [line for line in result.stdout.splitlines() if marker not in line]
            new_cron = "\n".join(lines) + "\n" if lines else ""

            proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
            proc.communicate(new_cron)
        except Exception:
            logger.warning(f"Failed to uninstall cron job '{name}', cron may not be available")


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
