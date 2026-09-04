# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Background job manager for sub-agent tasks.

Allows sub-agents to run in background threads so the user
can keep working in the main input loop. Jobs track status,
output, and token usage.
"""

import inspect
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# Stored job output is displayed in a terminal and injected back into the
# conversation, so it is bounded and escaped at the point it is stored.
MAX_STORED_RESULT_CHARS = 20_000
MAX_STORED_ERROR_CHARS = 2_000
DEFAULT_MAX_FINISHED_JOBS = 100


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
    provider: str = ""
    profile: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    result_content: str = ""
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
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

    def is_cancelled(self):
        """Return True once cancellation has been signalled."""
        return bool(self._cancel_event and self._cancel_event.is_set())


class BackgroundJobManager:
    """Manages background sub-agent jobs."""

    def __init__(self, max_finished_jobs=DEFAULT_MAX_FINISHED_JOBS):
        self._jobs: dict[int, BackgroundJob] = {}
        self._next_id: int = 1
        self._lock = threading.Lock()
        self._completion_callback = None
        self.max_finished_jobs = max(1, int(max_finished_jobs))
        self.finished_job_evictions = 0

    def start_job(
        self,
        description,
        run_function,
        model="",
        provider="",
        profile="",
        sub_tasks=None,
    ):
        """Start a background job in a daemon thread.

        The job's cancel event is passed into ``run_function`` when it accepts
        an argument, so cancelling a job stops the work rather than only
        relabelling its status.

        Args:
            description: Human-readable task description
            run_function: Callable returning a SubAgentResult. It may accept
                the job's ``threading.Event`` as its single argument.
            model: Model ID snapshotted at launch
            provider: Provider snapshotted at launch
            profile: Capability profile the sub-agent runs under
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
            provider=provider,
            profile=profile,
            started_at=time.time(),
            sub_tasks=sub_tasks or [],
            _cancel_event=cancel_event,
        )

        def worker():
            try:
                result = _call_with_optional_cancel(run_function, cancel_event)
                self._record_success(job, result)
            except Exception as error:
                self._record_failure(job, error)

            if self._completion_callback:
                try:
                    self._completion_callback(job)
                except Exception:
                    logger.debug("Background job completion callback failed", exc_info=True)

        thread = threading.Thread(target=worker, daemon=True)
        job._thread = thread

        with self._lock:
            self._jobs[job_id] = job

        thread.start()
        return job

    def _record_success(self, job, result):
        """Store a finished job's bounded, terminal-safe output."""
        from .terminal import escape_terminal_controls

        with self._lock:
            if job.status == JobStatus.CANCELLED:
                return
            if result is not None and getattr(result, "cancelled", False):
                job.status = JobStatus.CANCELLED
                job.finished_at = time.time()
                return

            job.status = JobStatus.COMPLETED
            content = getattr(result, "content", "") if result else ""
            job.result_content = escape_terminal_controls(
                content[:MAX_STORED_RESULT_CHARS], preserve_layout=True
            )
            job.input_tokens = getattr(result, "input_tokens", 0) if result else 0
            job.output_tokens = getattr(result, "output_tokens", 0) if result else 0
            job.tool_calls = getattr(result, "tool_calls", 0) if result else 0
            job.finished_at = time.time()
            self._prune_finished_jobs_locked()

    def _record_failure(self, job, error):
        """Store a failed job's bounded, terminal-safe error."""
        from .terminal import escape_terminal_controls

        with self._lock:
            if job.status == JobStatus.CANCELLED:
                return
            job.status = JobStatus.FAILED
            job.error = escape_terminal_controls(str(error))[:MAX_STORED_ERROR_CHARS]
            job.finished_at = time.time()
            self._prune_finished_jobs_locked()
        logger.error("Background job #%d failed: %s", job.job_id, error)

    def get_job(self, job_id):
        """Get a job by ID. Returns None if not found."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self):
        """List all jobs, newest first."""
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.job_id, reverse=True)

    def cancel_job(self, job_id):
        """Cancel a running job. Returns True if cancelled, False if not found/not running."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status != JobStatus.RUNNING:
                return False
            job.status = JobStatus.CANCELLED
            job.finished_at = time.time()
            if job._cancel_event:
                job._cancel_event.set()
            self._prune_finished_jobs_locked()

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

    def stats(self):
        """Return bounded job-retention counts for soak tests and telemetry."""
        with self._lock:
            running = sum(job.status == JobStatus.RUNNING for job in self._jobs.values())
            return {
                "jobs": len(self._jobs),
                "running": running,
                "finished": len(self._jobs) - running,
                "max_finished": self.max_finished_jobs,
                "finished_evictions": self.finished_job_evictions,
            }

    def _prune_finished_jobs_locked(self):
        """Evict the earliest completed jobs while retaining every running job."""
        finished = [job for job in self._jobs.values() if job.status != JobStatus.RUNNING]
        overflow = len(finished) - self.max_finished_jobs
        if overflow <= 0:
            return
        finished.sort(key=lambda job: (job.finished_at, job.job_id))
        for job in finished[:overflow]:
            self._jobs.pop(job.job_id, None)
            self.finished_job_evictions += 1


def _call_with_optional_cancel(run_function, cancel_event):
    """Call a job function, passing the cancel event when it accepts one.

    Older call sites take no arguments; the subagent runner takes the event so
    it can stop between API and tool calls.
    """
    try:
        signature = inspect.signature(run_function)
    except (TypeError, ValueError):
        return run_function()

    if not signature.parameters:
        return run_function()
    return run_function(cancel_event)


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
