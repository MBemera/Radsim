"""Scheduling tools exposed to the model.

`schedule_task` and `list_schedules` are thin wrappers over `jobs.py` so that
model-scheduled tasks land in the same store the user manages with `/job`.
The legacy `Scheduler` class and its separate `schedules.json` store were
removed; `jobs.py` is the single source of truth for cron state.
"""


def schedule_task(name, schedule, command, description=None):
    """Schedule a recurring task.

    Args:
        name: Human label for the job (stored as the description).
        schedule: Cron expression ("0 9 * * *") or a preset ("daily",
                  "weekdays @8:00").
        command: Shell command to execute.
        description: Optional description (falls back to name).

    Returns:
        dict with success status and the created job.
    """
    from .jobs import add_job, resolve_schedule

    cron = resolve_schedule(schedule)
    if cron is None:
        return {"success": False, "error": f"Invalid schedule: {schedule}"}
    try:
        job = add_job(cron, command, description or name or command[:50], is_radsim_task=False)
        return {
            "success": True,
            "job": {
                "id": job.job_id,
                "name": name,
                "schedule": job.schedule,
                "command": job.command,
            },
        }
    except Exception as error:
        return {"success": False, "error": str(error)}


def list_schedules():
    """List all scheduled tasks from the shared jobs store.

    Returns:
        dict with success status and jobs list.
    """
    from .jobs import describe_schedule, list_jobs

    try:
        jobs = list_jobs()
    except Exception as error:
        return {"success": False, "error": str(error)}
    return {
        "success": True,
        "count": len(jobs),
        "jobs": [
            {
                "id": job.job_id,
                "schedule": job.schedule,
                "human": describe_schedule(job.schedule),
                "command": job.command,
                "enabled": job.enabled,
            }
            for job in jobs
        ],
    }
