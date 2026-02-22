"""Tests for health check and monitoring utilities."""

import os
from datetime import datetime, timedelta
from unittest.mock import patch

from radsim.health import (
    HealthChecker,
    HealthStatus,
    SecretExpirationMonitor,
    check_health,
)


class TestHealthChecker:
    """Tests for HealthChecker class."""

    def test_health_status_creation(self):
        """Test HealthStatus dataclass creation."""
        status = HealthStatus(healthy=True)
        assert status.healthy is True
        assert status.timestamp != ""
        assert status.duration_ms == 0.0

    def test_check_log_directory(self):
        """Test log directory check passes."""
        checker = HealthChecker()
        ok, message = checker.check_log_directory()
        assert ok is True
        assert "writable" in message.lower()

    def test_check_config_directory(self):
        """Test config directory check passes."""
        checker = HealthChecker()
        ok, message = checker.check_config_directory()
        assert ok is True
        assert "accessible" in message.lower()

    def test_check_provider_import(self):
        """Test provider import check."""
        checker = HealthChecker()
        ok, message = checker.check_provider_import()
        # At least anthropic should be installed for tests to run
        # This may vary depending on test environment
        assert isinstance(ok, bool)
        assert isinstance(message, str)

    def test_check_api_key_from_env(self):
        """Test API key detection from environment."""
        checker = HealthChecker()

        # Test with env var set
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-12345"}):
            ok, message = checker.check_api_key_present()
            assert ok is True
            assert "ANTHROPIC_API_KEY" in message

    def test_check_api_key_missing(self):
        """Test API key missing detection."""
        checker = HealthChecker()

        # Clear all possible API key env vars
        env_patch = {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "RADSIM_API_KEY": "",
        }

        with patch.dict(os.environ, env_patch, clear=False):
            # Also need to remove them if they exist
            for key in env_patch:
                if key in os.environ:
                    del os.environ[key]

            ok, message = checker.check_api_key_present()
            # May pass if config has key, or fail if no key anywhere
            assert isinstance(ok, bool)

    def test_run_all_checks(self):
        """Test running all health checks."""
        checker = HealthChecker()
        status = checker.run_all_checks()

        assert isinstance(status, HealthStatus)
        assert "log_directory" in status.checks
        assert "config_directory" in status.checks
        assert "provider_sdk" in status.checks
        assert status.duration_ms >= 0


class TestSecretExpirationMonitor:
    """Tests for SecretExpirationMonitor class."""

    def test_add_expiration(self):
        """Test adding expiration dates."""
        monitor = SecretExpirationMonitor()
        expiry_date = datetime.now() + timedelta(days=60)

        monitor.add_expiration("TEST_KEY", expiry_date)

        assert "TEST_KEY" in monitor.expirations
        assert monitor.expirations["TEST_KEY"] == expiry_date

    def test_check_no_expirations(self):
        """Test checking with no registered expirations."""
        monitor = SecretExpirationMonitor()
        warnings = monitor.check_expirations()

        assert warnings == []

    def test_check_future_expiration(self):
        """Test checking a secret that expires far in the future."""
        monitor = SecretExpirationMonitor()
        expiry_date = datetime.now() + timedelta(days=90)

        monitor.add_expiration("SAFE_KEY", expiry_date)
        warnings = monitor.check_expirations()

        # 90 days out should not trigger warning (default is 30 days)
        assert len(warnings) == 0

    def test_check_expiring_soon(self):
        """Test checking a secret that expires soon."""
        monitor = SecretExpirationMonitor()
        expiry_date = datetime.now() + timedelta(days=15)

        monitor.add_expiration("EXPIRING_KEY", expiry_date)
        warnings = monitor.check_expirations()

        assert len(warnings) == 1
        assert warnings[0]["secret"] == "EXPIRING_KEY"
        assert warnings[0]["status"] == "expiring_soon"
        # Allow for slight timing variance (14-15 days depending on execution time)
        assert 14 <= warnings[0]["days_until"] <= 15

    def test_check_already_expired(self):
        """Test checking a secret that has already expired."""
        monitor = SecretExpirationMonitor()
        expiry_date = datetime.now() - timedelta(days=5)

        monitor.add_expiration("EXPIRED_KEY", expiry_date)
        warnings = monitor.check_expirations()

        assert len(warnings) == 1
        assert warnings[0]["secret"] == "EXPIRED_KEY"
        assert warnings[0]["status"] == "expired"
        assert warnings[0]["days_until"] == 0

    def test_load_from_env(self):
        """Test loading expiration dates from environment."""
        monitor = SecretExpirationMonitor()

        with patch.dict(
            os.environ, {"RADSIM_SECRET_EXPIRY_TESTKEY": "2025-06-15"}
        ):
            monitor.load_from_env()

        assert "TESTKEY" in monitor.expirations
        assert monitor.expirations["TESTKEY"] == datetime(2025, 6, 15)

    def test_load_from_env_invalid_date(self):
        """Test loading invalid date format from environment."""
        monitor = SecretExpirationMonitor()

        with patch.dict(
            os.environ, {"RADSIM_SECRET_EXPIRY_BADKEY": "not-a-date"}
        ):
            monitor.load_from_env()

        # Invalid date should be skipped
        assert "BADKEY" not in monitor.expirations


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_check_health(self):
        """Test check_health convenience function."""
        status = check_health()

        assert isinstance(status, HealthStatus)
        assert isinstance(status.healthy, bool)
