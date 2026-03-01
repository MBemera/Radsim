# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Background job manager for sub-agent tasks.

Allows sub-agents to run in background threads so the user
can keep working in the main input loop. Jobs track status,
output, and token usage.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundJob:
    """A sub-agent task running in the background."""

    job_id: int
    description: str
    status: JobStatus = JobStatus.RUNNING
    model: str = ""
    tier: str = "fast"
    started_at: float = 0.0
    finished_at: float = 0.0
    result_content: str = ""
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    sub_tasks: list = field(default_factory=list)  # Individual task descriptions for parallel jobs
    _thread: threading.Thread = field(default=None, repr=False)
    _cancel_event: threading.Event = field(default=None, repr=False)

    @property
    def duration(self):
        """Duration in seconds. Uses current time if still running."""
        if self.finished_at > 0:
            return self.finished_at - self.started_at
        if self.started_at > 0:
            return time.time() - self.started_at
        return 0.0


class BackgroundJobManager:
    """Manages background sub-agent jobs."""

    def __init__(self):
        self._jobs: dict[int, BackgroundJob] = {}
        self._next_id: int = 1
        self._lock = threading.Lock()
        self._completion_callback = None

    def start_job(self, description, run_function, model="", tier="fast", sub_tasks=None):
        """Start a background job in a daemon thread.

        Args:
            description: Human-readable task description
            run_function: Callable that returns a SubAgentResult
            model: Model ID being used
            tier: Task tier (fast, capable, review)
            sub_tasks: List of individual task descriptions (for parallel jobs)

        Returns:
            BackgroundJob instance
        """
        cancel_event = threading.Event()

        with self._lock:
            job_id = self._next_id
            self._next_id += 1

        job = BackgroundJob(
            job_id=job_id,
            description=description,
            status=JobStatus.RUNNING,
            model=model,
            tier=tier,
            started_at=time.time(),
            sub_tasks=sub_tasks or [],
            _cancel_event=cancel_event,
        )

        def worker():
            try:
                result = run_function()
                with self._lock:
                    if job.status == JobStatus.CANCELLED:
                        return
                    job.status = JobStatus.COMPLETED
                    job.result_content = result.content if result else ""
                    job.input_tokens = result.input_tokens if result else 0
                    job.output_tokens = result.output_tokens if result else 0
                    job.finished_at = time.time()
            except Exception as e:
                with self._lock:
                    if job.status == JobStatus.CANCELLED:
                        return
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    job.finished_at = time.time()
                logger.error("Background job #%d failed: %s", job_id, e)

            if self._completion_callback:
                try:
                    self._completion_callback(job)
                except Exception:
                    pass

        thread = threading.Thread(target=worker, daemon=True)
        job._thread = thread

        with self._lock:
            self._jobs[job_id] = job

        thread.start()
        return job

    def get_job(self, job_id):
        """Get a job by ID. Returns None if not found."""
        return self._jobs.get(job_id)

    def list_jobs(self):
        """List all jobs, newest first."""
        return sorted(self._jobs.values(), key=lambda j: j.job_id, reverse=True)

    def cancel_job(self, job_id):
        """Cancel a running job. Returns True if cancelled, False if not found/not running."""
        job = self._jobs.get(job_id)
        if not job:
            return False

        with self._lock:
            if job.status != JobStatus.RUNNING:
                return False
            job.status = JobStatus.CANCELLED
            job.finished_at = time.time()
            if job._cancel_event:
                job._cancel_event.set()

        return True

    def clear_finished(self):
        """Remove all non-running jobs. Returns count of removed jobs."""
        with self._lock:
            to_remove = [
                jid for jid, job in self._jobs.items()
                if job.status != JobStatus.RUNNING
            ]
            for jid in to_remove:
                del self._jobs[jid]
        return len(to_remove)

    def set_completion_callback(self, callback):
        """Set a callback invoked when any job finishes.

        Args:
            callback: Function that takes a BackgroundJob argument
        """
        self._completion_callback = callback


# Module-level singleton (session-scoped)
_manager = None


def get_job_manager():
    global _manager
    if _manager is None:
        _manager = BackgroundJobManager()
    return _manager


def reset_job_manager():
    global _manager
    _manager = BackgroundJobManager()
