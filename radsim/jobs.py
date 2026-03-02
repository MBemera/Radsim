"""Cron job manager for RadSim.

Manages scheduled tasks using OS-level cron (Mac/Linux) or Task Scheduler (Windows).
Jobs are stored in ~/.radsim/jobs.json and synced to the system scheduler.
RadSim-managed entries are tagged so existing user cron jobs are never touched.
"""

import json
import logging
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

JOBS_FILE = Path.home() / ".radsim" / "jobs.json"
RADSIM_CRON_TAG = "radsim-job"

SCHEDULE_PRESETS = {
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "weekly": "0 9 * * 1",
    "weekdays": "0 9 * * 1-5",
    "monthly": "0 9 1 * *",
}


@dataclass
class CronJob:
    job_id: int
    schedule: str
    command: str
    description: str
    is_radsim_task: bool
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run: str = ""


def _load_jobs() -> list[CronJob]:
    """Load all jobs from the storage file."""
    if not JOBS_FILE.exists():
        return []

    try:
        data = json.loads(JOBS_FILE.read_text())
        return [CronJob(**job) for job in data]
    except (json.JSONDecodeError, TypeError, KeyError) as error:
        logger.warning("Failed to load jobs file: %s", error)
        return []


def _save_jobs(jobs: list[CronJob]):
    """Save all jobs to the storage file."""
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(job) for job in jobs]
    JOBS_FILE.write_text(json.dumps(data, indent=2))


def _next_job_id(jobs: list[CronJob]) -> int:
    """Get the next available job ID."""
    if not jobs:
        return 1
    return max(job.job_id for job in jobs) + 1


def resolve_schedule(schedule_input: str) -> str | None:
    """Resolve a schedule string to a cron expression.

    Accepts preset names ('daily', 'hourly'), preset with time ('daily @14:30'),
    or raw cron expressions ('0 9 * * *').

    Returns the cron expression or None if invalid.
    """
    schedule_input = schedule_input.strip().lower()

    # Check presets
    if schedule_input in SCHEDULE_PRESETS:
        return SCHEDULE_PRESETS[schedule_input]

    # Handle "daily @HH:MM" syntax
    if schedule_input.startswith("daily @"):
        time_part = schedule_input.replace("daily @", "").strip()
        return _parse_time_to_cron(time_part, "* * *")

    if schedule_input.startswith("weekdays @"):
        time_part = schedule_input.replace("weekdays @", "").strip()
        return _parse_time_to_cron(time_part, "* * 1-5")

    if schedule_input.startswith("weekly @"):
        time_part = schedule_input.replace("weekly @", "").strip()
        return _parse_time_to_cron(time_part, "* * 1")

    # Validate raw cron expression
    if validate_cron_expression(schedule_input):
        return schedule_input

    return None


def _parse_time_to_cron(time_str: str, day_fields: str) -> str | None:
    """Parse HH:MM or HH time string into cron minute/hour fields."""
    try:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None

        return f"{minute} {hour} {day_fields}"
    except (ValueError, IndexError):
        return None


def validate_cron_expression(expression: str) -> bool:
    """Validate a cron expression has 5 valid fields."""
    fields = expression.strip().split()
    if len(fields) != 5:
        return False

    # Basic range checks for each field
    ranges = [
        (0, 59),   # minute
        (0, 23),   # hour
        (1, 31),   # day of month
        (1, 12),   # month
        (0, 7),    # day of week (0 and 7 are Sunday)
    ]

    for field_value, (min_val, max_val) in zip(fields, ranges, strict=True):
        if not _validate_cron_field(field_value, min_val, max_val):
            return False

    return True


def _validate_cron_field(field_value: str, min_val: int, max_val: int) -> bool:
    """Validate a single cron field (supports *, ranges, lists, steps)."""
    if field_value == "*":
        return True

    # Handle step values like */5 or 1-10/2
    if "/" in field_value:
        parts = field_value.split("/")
        if len(parts) != 2:
            return False
        base = parts[0]
        try:
            step = int(parts[1])
            if step < 1:
                return False
        except ValueError:
            return False
        if base == "*":
            return True
        return _validate_cron_field(base, min_val, max_val)

    # Handle lists like 1,3,5
    if "," in field_value:
        return all(
            _validate_cron_field(part.strip(), min_val, max_val)
            for part in field_value.split(",")
        )

    # Handle ranges like 1-5
    if "-" in field_value:
        parts = field_value.split("-")
        if len(parts) != 2:
            return False
        try:
            start = int(parts[0])
            end = int(parts[1])
            return min_val <= start <= max_val and min_val <= end <= max_val
        except ValueError:
            return False

    # Single number
    try:
        value = int(field_value)
        return min_val <= value <= max_val
    except ValueError:
        return False


def _build_shell_command(job: CronJob) -> str:
    """Build the full shell command for a cron job."""
    radsim_path = shutil.which("radsim") or "radsim"

    if job.is_radsim_task:
        escaped_command = job.command.replace('"', '\\"')
        return f'{radsim_path} "{escaped_command}"'

    return job.command


def _is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system().lower() == "windows"


# --- Crontab integration (Mac/Linux) ---

def _read_crontab() -> str:
    """Read the current user crontab. Returns empty string if no crontab exists."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ""
        return result.stdout
    except FileNotFoundError:
        return ""


def _write_crontab(content: str):
    """Write a new crontab, replacing the current one."""
    subprocess.run(
        ["crontab", "-"],
        input=content,
        capture_output=True,
        text=True,
        check=True,
    )


def _remove_radsim_lines(crontab_text: str) -> str:
    """Remove all RadSim-tagged lines from crontab text."""
    lines = crontab_text.splitlines()
    filtered_lines = []
    skip_next = False

    for line in lines:
        if skip_next:
            skip_next = False
            continue
        if line.strip().startswith(f"# {RADSIM_CRON_TAG}"):
            skip_next = True
            continue
        filtered_lines.append(line)

    return "\n".join(filtered_lines)


def _build_crontab_entries(jobs: list[CronJob]) -> str:
    """Build crontab entries for all enabled RadSim jobs."""
    entries = []
    for job in jobs:
        if not job.enabled:
            continue
        shell_command = _build_shell_command(job)
        entries.append(f"# {RADSIM_CRON_TAG}-{job.job_id}: {job.description}")
        entries.append(f"{job.schedule} {shell_command}")

    return "\n".join(entries)


def sync_crontab():
    """Sync the system crontab with the stored RadSim jobs.

    Reads the current crontab, removes all RadSim-tagged lines,
    then appends entries for all enabled jobs.
    """
    if _is_windows():
        _sync_windows_tasks()
        return

    jobs = _load_jobs()
    current_crontab = _read_crontab()

    # Remove old RadSim entries
    cleaned_crontab = _remove_radsim_lines(current_crontab)

    # Build new entries
    new_entries = _build_crontab_entries(jobs)

    # Combine: existing user entries + RadSim entries
    parts = [cleaned_crontab.rstrip()]
    if new_entries:
        parts.append(new_entries)

    final_crontab = "\n".join(part for part in parts if part) + "\n"

    _write_crontab(final_crontab)


# --- Windows Task Scheduler integration ---

def _sync_windows_tasks():
    """Sync Windows Task Scheduler with stored RadSim jobs."""
    jobs = _load_jobs()

    # Remove all existing RadSim tasks
    _remove_all_windows_tasks()

    # Create tasks for enabled jobs
    for job in jobs:
        if job.enabled:
            _create_windows_task(job)


def _remove_all_windows_tasks():
    """Remove all RadSim tasks from Windows Task Scheduler."""
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/fo", "LIST"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if "RadSim_Job_" in line:
                task_name = line.split(":")[-1].strip()
                subprocess.run(
                    ["schtasks", "/delete", "/tn", task_name, "/f"],
                    capture_output=True,
                    text=True,
                )
    except FileNotFoundError:
        logger.warning("schtasks not found — cannot manage Windows scheduled tasks")


def _create_windows_task(job: CronJob):
    """Create a Windows scheduled task for a job."""
    task_name = f"RadSim_Job_{job.job_id}"
    shell_command = _build_shell_command(job)

    # Convert cron schedule to schtasks format (simplified)
    schedule_type, schedule_args = _cron_to_schtasks(job.schedule)

    try:
        cmd = [
            "schtasks", "/create",
            "/tn", task_name,
            "/tr", shell_command,
            "/sc", schedule_type,
            *schedule_args,
            "/f",
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        logger.warning("Failed to create Windows task: %s", error)


def _cron_to_schtasks(cron_expr: str) -> tuple[str, list[str]]:
    """Convert a cron expression to schtasks schedule type and arguments.

    This is a simplified conversion covering common patterns.
    """
    fields = cron_expr.split()
    minute, hour = fields[0], fields[1]
    dom, month, dow = fields[2], fields[3], fields[4]

    start_time = f"{int(hour):02d}:{int(minute):02d}"

    # Hourly: 0 * * * *
    if hour == "*" and dom == "*" and month == "*" and dow == "*":
        return "HOURLY", ["/st", f"00:{int(minute):02d}"]

    # Daily: M H * * *
    if dom == "*" and month == "*" and dow == "*":
        return "DAILY", ["/st", start_time]

    # Weekdays: M H * * 1-5
    if dom == "*" and month == "*" and dow == "1-5":
        return "WEEKLY", ["/d", "MON,TUE,WED,THU,FRI", "/st", start_time]

    # Weekly: M H * * N
    if dom == "*" and month == "*" and dow not in ("*", "1-5"):
        day_map = {"0": "SUN", "1": "MON", "2": "TUE", "3": "WED",
                   "4": "THU", "5": "FRI", "6": "SAT", "7": "SUN"}
        day = day_map.get(dow, "MON")
        return "WEEKLY", ["/d", day, "/st", start_time]

    # Monthly: M H D * *
    if month == "*" and dow == "*":
        return "MONTHLY", ["/d", dom, "/st", start_time]

    # Fallback to daily
    return "DAILY", ["/st", start_time]


# --- Public API ---

def add_job(schedule: str, command: str, description: str, is_radsim_task: bool) -> CronJob:
    """Add a new scheduled job.

    Args:
        schedule: Cron expression (e.g., '0 9 * * *').
        command: Shell command or radsim task text.
        description: Human-readable label.
        is_radsim_task: True if command should be wrapped as 'radsim "..."'.

    Returns:
        The created CronJob.
    """
    jobs = _load_jobs()
    job_id = _next_job_id(jobs)

    job = CronJob(
        job_id=job_id,
        schedule=schedule,
        command=command,
        description=description,
        is_radsim_task=is_radsim_task,
        enabled=True,
    )

    jobs.append(job)
    _save_jobs(jobs)
    sync_crontab()

    return job


def remove_job(job_id: int) -> bool:
    """Remove a job completely (from storage and system scheduler).

    Returns True if the job was found and removed.
    """
    jobs = _load_jobs()
    original_count = len(jobs)
    jobs = [job for job in jobs if job.job_id != job_id]

    if len(jobs) == original_count:
        return False

    _save_jobs(jobs)
    sync_crontab()
    return True


def enable_job(job_id: int) -> bool:
    """Enable a disabled job (adds it back to the system scheduler).

    Returns True if the job was found and enabled.
    """
    jobs = _load_jobs()
    for job in jobs:
        if job.job_id == job_id:
            job.enabled = True
            _save_jobs(jobs)
            sync_crontab()
            return True
    return False


def disable_job(job_id: int) -> bool:
    """Disable a job (removes from scheduler, keeps in storage).

    Returns True if the job was found and disabled.
    """
    jobs = _load_jobs()
    for job in jobs:
        if job.job_id == job_id:
            job.enabled = False
            _save_jobs(jobs)
            sync_crontab()
            return True
    return False


def list_jobs() -> list[CronJob]:
    """Return all stored jobs."""
    return _load_jobs()


def get_job(job_id: int) -> CronJob | None:
    """Get a specific job by ID."""
    jobs = _load_jobs()
    for job in jobs:
        if job.job_id == job_id:
            return job
    return None


def run_job_now(job_id: int) -> tuple[bool, str]:
    """Execute a job immediately (one-off run).

    Returns (success, output_or_error).
    """
    job = get_job(job_id)
    if not job:
        return False, f"Job #{job_id} not found"

    shell_command = _build_shell_command(job)

    try:
        result = subprocess.run(
            shell_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Update last_run timestamp
        jobs = _load_jobs()
        for stored_job in jobs:
            if stored_job.job_id == job_id:
                stored_job.last_run = datetime.now().isoformat()
                break
        _save_jobs(jobs)

        output = result.stdout or result.stderr or "(no output)"
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, "Job timed out after 5 minutes"
    except Exception as error:
        return False, str(error)


def describe_schedule(cron_expr: str) -> str:
    """Return a human-readable description of a cron expression."""
    # Check known presets
    for preset_name, preset_expr in SCHEDULE_PRESETS.items():
        if cron_expr == preset_expr:
            return preset_name

    fields = cron_expr.split()
    if len(fields) != 5:
        return cron_expr

    minute, hour, dom, month, dow = fields

    # Common patterns
    if dom == "*" and month == "*" and dow == "*":
        if hour == "*":
            return f"every hour at :{minute.zfill(2)}"
        return f"daily @{hour}:{minute.zfill(2)}"

    if dom == "*" and month == "*" and dow == "1-5":
        return f"weekdays @{hour}:{minute.zfill(2)}"

    if dom == "*" and month == "*":
        day_names = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed",
                     "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun"}
        day = day_names.get(dow, f"day {dow}")
        return f"{day} @{hour}:{minute.zfill(2)}"

    if month == "*" and dow == "*":
        return f"monthly day {dom} @{hour}:{minute.zfill(2)}"

    return cron_expr
