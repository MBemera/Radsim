"""Tests for background job manager."""

import threading
import time
import unittest

from radsim.background import (
    BackgroundJob,
    BackgroundJobManager,
    JobStatus,
    get_job_manager,
    reset_job_manager,
)


class TestJobStatus(unittest.TestCase):
    """Test JobStatus enum values."""

    def test_enum_values(self):
        assert JobStatus.RUNNING == "running"
        assert JobStatus.COMPLETED == "completed"
        assert JobStatus.FAILED == "failed"
        assert JobStatus.CANCELLED == "cancelled"


class TestBackgroundJob(unittest.TestCase):
    """Test BackgroundJob dataclass."""

    def test_duration_when_finished(self):
        job = BackgroundJob(job_id=1, description="test", started_at=100.0, finished_at=112.5)
        assert job.duration == 12.5

    def test_duration_when_not_started(self):
        job = BackgroundJob(job_id=1, description="test")
        assert job.duration == 0.0


class TestBackgroundJobManager(unittest.TestCase):
    """Test BackgroundJobManager operations."""

    def setUp(self):
        self.manager = BackgroundJobManager()

    def test_start_job_assigns_id(self):
        """Job gets an ID and completes successfully."""
        result_holder = type("R", (), {"content": "done", "input_tokens": 10, "output_tokens": 20})()

        def run():
            return result_holder

        job = self.manager.start_job("test task", run, model="haiku", tier="fast")
        assert job.job_id == 1
        assert job.model == "haiku"
        assert job.tier == "fast"

        # Wait for completion
        job._thread.join(timeout=2)

        assert job.status == JobStatus.COMPLETED
        assert job.result_content == "done"
        assert job.input_tokens == 10
        assert job.output_tokens == 20

    def test_sequential_ids(self):
        """Job IDs increment sequentially."""
        def run():
            return type("R", (), {"content": "", "input_tokens": 0, "output_tokens": 0})()

        job1 = self.manager.start_job("task 1", run)
        job2 = self.manager.start_job("task 2", run)
        job3 = self.manager.start_job("task 3", run)

        assert job1.job_id == 1
        assert job2.job_id == 2
        assert job3.job_id == 3

    def test_failed_job(self):
        """Exception in run_function results in FAILED status."""
        def run():
            raise ValueError("something broke")

        job = self.manager.start_job("failing task", run)
        job._thread.join(timeout=2)

        assert job.status == JobStatus.FAILED
        assert "something broke" in job.error

    def test_cancel_running_job(self):
        """Cancelling a running job sets CANCELLED status."""
        started = threading.Event()

        def run():
            started.set()
            time.sleep(10)  # Long-running task
            return type("R", (), {"content": "", "input_tokens": 0, "output_tokens": 0})()

        job = self.manager.start_job("long task", run)
        started.wait(timeout=2)

        result = self.manager.cancel_job(job.job_id)
        assert result is True
        assert job.status == JobStatus.CANCELLED
        assert job.finished_at > 0

    def test_cancel_nonexistent(self):
        """Cancelling a non-existent job returns False."""
        result = self.manager.cancel_job(999)
        assert result is False

    def test_cancel_completed_job(self):
        """Cancelling an already-completed job returns False."""
        def run():
            return type("R", (), {"content": "", "input_tokens": 0, "output_tokens": 0})()

        job = self.manager.start_job("quick task", run)
        job._thread.join(timeout=2)

        result = self.manager.cancel_job(job.job_id)
        assert result is False

    def test_get_job(self):
        """get_job returns the correct job or None."""
        def run():
            return type("R", (), {"content": "", "input_tokens": 0, "output_tokens": 0})()

        job = self.manager.start_job("task", run)
        assert self.manager.get_job(job.job_id) is job
        assert self.manager.get_job(999) is None

    def test_list_jobs(self):
        """list_jobs returns all jobs, newest first."""
        def run():
            return type("R", (), {"content": "", "input_tokens": 0, "output_tokens": 0})()

        self.manager.start_job("task 1", run)
        self.manager.start_job("task 2", run)
        self.manager.start_job("task 3", run)

        jobs = self.manager.list_jobs()
        assert len(jobs) == 3
        assert jobs[0].job_id == 3  # Newest first
        assert jobs[2].job_id == 1

    def test_clear_finished(self):
        """clear_finished removes completed/failed jobs but keeps running ones."""
        started = threading.Event()

        def quick_run():
            return type("R", (), {"content": "", "input_tokens": 0, "output_tokens": 0})()

        def slow_run():
            started.set()
            time.sleep(10)
            return type("R", (), {"content": "", "input_tokens": 0, "output_tokens": 0})()

        job1 = self.manager.start_job("quick", quick_run)
        job1._thread.join(timeout=2)

        job2 = self.manager.start_job("slow", slow_run)
        started.wait(timeout=2)

        removed = self.manager.clear_finished()
        assert removed == 1  # Only the completed job

        remaining = self.manager.list_jobs()
        assert len(remaining) == 1
        assert remaining[0].job_id == job2.job_id

        # Clean up
        self.manager.cancel_job(job2.job_id)

    def test_completion_callback(self):
        """Completion callback is called when a job finishes."""
        callback_jobs = []

        def on_complete(job):
            callback_jobs.append(job)

        self.manager.set_completion_callback(on_complete)

        def run():
            return type("R", (), {"content": "result", "input_tokens": 0, "output_tokens": 0})()

        job = self.manager.start_job("task", run)
        job._thread.join(timeout=2)

        assert len(callback_jobs) == 1
        assert callback_jobs[0].job_id == job.job_id

    def test_completion_callback_on_failure(self):
        """Completion callback is also called when a job fails."""
        callback_jobs = []

        def on_complete(job):
            callback_jobs.append(job)

        self.manager.set_completion_callback(on_complete)

        def run():
            raise RuntimeError("oops")

        job = self.manager.start_job("failing", run)
        job._thread.join(timeout=2)

        assert len(callback_jobs) == 1
        assert callback_jobs[0].status == JobStatus.FAILED


class TestSingleton(unittest.TestCase):
    """Test singleton pattern."""

    def setUp(self):
        reset_job_manager()

    def test_get_returns_same_instance(self):
        manager1 = get_job_manager()
        manager2 = get_job_manager()
        assert manager1 is manager2

    def test_reset_creates_new_instance(self):
        manager1 = get_job_manager()
        reset_job_manager()
        manager2 = get_job_manager()
        assert manager1 is not manager2


if __name__ == "__main__":
    unittest.main()
