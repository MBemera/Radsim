"""Tests for the Task Scheduler module."""

import pytest

from radsim.scheduler import sanitize_cron_command, validate_cron_schedule


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
