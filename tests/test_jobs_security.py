"""Security and cross-platform regression tests for the cron job manager."""

import json
import shlex
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from radsim import jobs


def build_job(**overrides):
    """Build one valid job with focused overrides."""
    values = {
        "job_id": 1,
        "schedule": "0 9 * * *",
        "command": "review the project",
        "description": "daily review",
        "is_radsim_task": True,
    }
    values.update(overrides)
    return jobs.CronJob(**values)


class TestPersistedJobValidation:
    def test_tampered_description_cannot_inject_crontab_line(self, tmp_path, monkeypatch):
        jobs_file = tmp_path / "jobs.json"
        payload = [
            {
                "job_id": 1,
                "schedule": "0 9 * * *",
                "command": "echo safe",
                "description": "safe\n* * * * * injected",
                "is_radsim_task": False,
            }
        ]
        jobs_file.write_text(json.dumps(payload))
        monkeypatch.setattr(jobs, "JOBS_FILE", jobs_file)

        with pytest.raises(ValueError, match="refusing to modify"):
            jobs.list_jobs()

    def test_add_job_rejects_invalid_schedule_before_write(self, tmp_path, monkeypatch):
        jobs_file = tmp_path / "jobs.json"
        monkeypatch.setattr(jobs, "JOBS_FILE", jobs_file)

        with pytest.raises(ValueError, match="Invalid cron schedule"):
            jobs.add_job("99 99 * * *", "echo safe", "invalid", False)

        assert not jobs_file.exists()

    def test_sync_failure_rolls_back_jobs_file(self, tmp_path, monkeypatch):
        jobs_file = tmp_path / "jobs.json"
        monkeypatch.setattr(jobs, "JOBS_FILE", jobs_file)

        with patch(
            "radsim.jobs.sync_crontab",
            side_effect=RuntimeError("cron unavailable"),
        ) as mock_sync:
            with pytest.raises(RuntimeError, match="cron unavailable"):
                jobs.add_job("0 9 * * *", "echo safe", "safe", False)

        assert json.loads(jobs_file.read_text()) == []
        assert mock_sync.call_count == 2

    def test_duplicate_job_ids_are_rejected(self, tmp_path, monkeypatch):
        jobs_file = tmp_path / "jobs.json"
        payload = [build_job().__dict__, build_job(description="duplicate").__dict__]
        jobs_file.write_text(json.dumps(payload))
        monkeypatch.setattr(jobs, "JOBS_FILE", jobs_file)

        with pytest.raises(ValueError, match="refusing to modify"):
            jobs.list_jobs()

    def test_terminal_controls_are_rejected_before_persistence(self, tmp_path, monkeypatch):
        jobs_file = tmp_path / "jobs.json"
        monkeypatch.setattr(jobs, "JOBS_FILE", jobs_file)

        for control_character in ("\x1b", "\x9b", "\u202e"):
            with pytest.raises(ValueError, match="control characters"):
                jobs.add_job(
                    "0 9 * * *",
                    "echo safe",
                    f"safe{control_character}[2Khidden",
                    False,
                )

        assert not jobs_file.exists()


class TestCrontabPreservation:
    @patch("radsim.cron_utils.subprocess.run")
    def test_read_failure_does_not_write_crontab(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="permission denied")

        with patch("radsim.jobs._load_jobs", return_value=[]):
            with pytest.raises(RuntimeError, match="Unable to read"):
                jobs.sync_crontab()

        assert mock_run.call_count == 1

    def test_only_exact_radsim_marker_removes_following_entry(self):
        existing = "# radsim-job notes\n0 1 * * * keep-me\n# radsim-job-2: owned\n0 2 * * * remove-me"

        cleaned = jobs._remove_radsim_lines(existing)

        assert "keep-me" in cleaned
        assert "remove-me" not in cleaned


class TestCommandRendering:
    def test_posix_radsim_path_and_task_round_trip(self):
        job = build_job(command="say 'hello' and finish\\")
        with patch("radsim.jobs.is_windows", return_value=False), patch(
            "radsim.jobs.shutil.which", return_value="/Applications/Rad Sim/radsim"
        ):
            rendered = jobs._build_shell_command(job)

        assert shlex.split(rendered) == ["/Applications/Rad Sim/radsim", job.command]

    def test_percent_escaping_is_idempotent(self):
        assert jobs.escape_cron_percent("date +%F") == "date +\\%F"
        assert jobs.escape_cron_percent("date +\\%F") == "date +\\%F"

    def test_windows_task_uses_standard_command_line_quoting(self):
        job = build_job(command='say "hello" and finish\\')
        executable = r"C:\Program Files\RadSim\radsim.exe"
        with patch("radsim.jobs.is_windows", return_value=True), patch(
            "radsim.jobs.shutil.which", return_value=executable
        ):
            rendered = jobs._build_shell_command(job)

        assert rendered == subprocess.list2cmdline([executable, job.command])

    def test_windows_shell_job_runs_through_noninteractive_powershell(self):
        job = build_job(command='Write-Output "safe" | Out-File result.txt', is_radsim_task=False)

        with patch("radsim.jobs.is_windows", return_value=True):
            rendered = jobs._build_shell_command(job)

        assert rendered == subprocess.list2cmdline(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                job.command,
            ]
        )


class TestWindowsScheduleConversion:
    @pytest.mark.parametrize(
        ("schedule", "schedule_type", "arguments"),
        [
            ("* * * * *", "MINUTE", ["/mo", "1"]),
            ("*/5 * * * *", "MINUTE", ["/mo", "5"]),
            ("0 * * * *", "HOURLY", ["/st", "00:00"]),
            ("30 14 * * *", "DAILY", ["/st", "14:30"]),
        ],
    )
    def test_common_presets_convert_without_crashing(self, schedule, schedule_type, arguments):
        assert jobs._cron_to_schtasks(schedule) == (schedule_type, arguments)

    def test_unsupported_valid_expression_fails_explicitly(self):
        with pytest.raises(ValueError, match="unsupported"):
            jobs._cron_to_schtasks("0,30 9-17 * * 1-5")


class TestWindowsTaskReconciliation:
    def test_creates_desired_tasks_before_deleting_exact_stale_tasks(self):
        desired_job = build_job(job_id=1)
        events = []

        with patch("radsim.jobs._load_jobs", return_value=[desired_job]), patch(
            "radsim.jobs._list_windows_task_names",
            return_value={r"\RadSim_Job_1", r"\RadSim_Job_2"},
        ), patch(
            "radsim.jobs._create_windows_task",
            side_effect=lambda job: events.append(("create", job.job_id)),
        ), patch(
            "radsim.jobs._delete_windows_task",
            side_effect=lambda name: events.append(("delete", name)),
        ):
            jobs._sync_windows_tasks()

        assert events == [("create", 1), ("delete", r"\RadSim_Job_2")]

    def test_create_failure_does_not_delete_existing_tasks(self):
        desired_job = build_job(job_id=1)

        with patch("radsim.jobs._load_jobs", return_value=[desired_job]), patch(
            "radsim.jobs._list_windows_task_names",
            return_value={r"\RadSim_Job_2"},
        ), patch(
            "radsim.jobs._create_windows_task",
            side_effect=RuntimeError("create failed"),
        ), patch("radsim.jobs._delete_windows_task") as mock_delete:
            with pytest.raises(RuntimeError, match="create failed"):
                jobs._sync_windows_tasks()

        mock_delete.assert_not_called()

    @patch("radsim.jobs.subprocess.run")
    def test_task_query_keeps_only_exact_managed_names(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=(
                '"\\RadSim_Job_1","12:00","Ready"\n'
                '"\\RadSim_Job_backup","12:00","Ready"\n'
                '"\\Other_Task","12:00","Ready"\n'
            )
        )

        assert jobs._list_windows_task_names() == {r"\RadSim_Job_1"}


class TestImmediateJobExecution:
    def test_radsim_task_runs_as_argv_without_powershell_rendering(self):
        job = build_job(command='say "hello" and finish\\')
        executable = r"C:\Program Files\RadSim\radsim.exe"

        with patch("radsim.jobs.get_job", return_value=job), patch(
            "radsim.jobs._load_jobs", return_value=[build_job()]
        ), patch("radsim.jobs._save_jobs"), patch(
            "radsim.jobs._resolve_radsim_path", return_value=executable
        ), patch(
            "radsim.jobs.run_process",
            return_value={"success": True, "stdout": "done", "stderr": "", "returncode": 0},
        ) as mock_process, patch("radsim.jobs.run_shell_command") as mock_shell:
            result = jobs.run_job_now(1)

        assert result == (True, "done")
        mock_process.assert_called_once_with([executable, job.command], timeout=300)
        mock_shell.assert_not_called()
