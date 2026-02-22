"""Health check and monitoring utilities for RadSim Agent.

Production Readiness: Health checks and startup validation
ensure the application is ready to serve before accepting requests.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Health check result."""

    healthy: bool
    checks: dict = field(default_factory=dict)
    timestamp: str = ""
    duration_ms: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class HealthChecker:
    """Production-ready health check system.

    Validates all dependencies are available before starting.
    """

    def __init__(self, config=None):
        self.config = config
        self._checks = {}

    def check_api_key_present(self) -> tuple[bool, str]:
        """Verify API key is configured."""
        if self.config and self.config.api_key:
            # Mask the key for display
            masked = self.config.api_key[:8] + "..." if len(self.config.api_key) > 8 else "***"
            return True, f"API key configured ({masked})"

        # Check environment variables
        env_vars = [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENROUTER_API_KEY",
            "RADSIM_API_KEY",
        ]

        for var in env_vars:
            if os.getenv(var):
                return True, f"{var} found in environment"

        return False, "No API key configured"

    def check_log_directory(self) -> tuple[bool, str]:
        """Verify log directory is writable."""
        log_dir = Path.home() / ".radsim" / "logs"

        try:
            log_dir.mkdir(parents=True, exist_ok=True)

            # Test write
            test_file = log_dir / ".health_check"
            test_file.write_text("ok")
            test_file.unlink()

            return True, f"Log directory writable: {log_dir}"
        except Exception as e:
            return False, f"Log directory not writable: {e}"

    def check_config_directory(self) -> tuple[bool, str]:
        """Verify config directory exists and is accessible."""
        config_dir = Path.home() / ".radsim"

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            return True, f"Config directory accessible: {config_dir}"
        except Exception as e:
            return False, f"Config directory not accessible: {e}"

    def check_provider_import(self) -> tuple[bool, str]:
        """Verify at least one provider SDK is available."""
        import importlib.util

        providers_found = []

        if importlib.util.find_spec("anthropic"):
            providers_found.append("anthropic")

        if importlib.util.find_spec("openai"):
            providers_found.append("openai")

        if importlib.util.find_spec("google.genai"):
            providers_found.append("google-genai")

        if providers_found:
            return True, f"Provider SDKs available: {', '.join(providers_found)}"

        return False, "No provider SDKs installed (need anthropic, openai, or google-genai)"

    def run_all_checks(self) -> HealthStatus:
        """Run all health checks and return status."""
        start_time = time.time()

        checks = {
            "api_key": self.check_api_key_present(),
            "log_directory": self.check_log_directory(),
            "config_directory": self.check_config_directory(),
            "provider_sdk": self.check_provider_import(),
        }

        duration_ms = (time.time() - start_time) * 1000
        all_healthy = all(status for status, _ in checks.values())

        return HealthStatus(
            healthy=all_healthy,
            checks={name: {"ok": ok, "message": msg} for name, (ok, msg) in checks.items()},
            duration_ms=duration_ms,
        )

    def run_startup_validation(self) -> bool:
        """Run startup validation and fail fast if critical checks fail.

        Returns:
            True if all critical checks pass.

        Raises:
            RuntimeError: If critical checks fail.
        """
        status = self.run_all_checks()

        if not status.healthy:
            failed = [
                f"  - {name}: {info['message']}"
                for name, info in status.checks.items()
                if not info["ok"]
            ]
            raise RuntimeError("Startup validation failed:\n" + "\n".join(failed))

        return True


@dataclass
class SecretExpirationMonitor:
    """Monitor for API key and certificate expiration.

    Production Readiness: Alert when secrets are approaching expiration.
    """

    # Track known expiration dates (user-configured)
    expirations: dict = field(default_factory=dict)
    warning_days: int = 30  # Warn this many days before expiration

    def add_expiration(self, secret_name: str, expiration_date: datetime):
        """Register a secret's expiration date."""
        self.expirations[secret_name] = expiration_date

    def check_expirations(self) -> list[dict]:
        """Check all registered secrets for upcoming expirations.

        Returns:
            List of warnings for secrets expiring soon.
        """
        warnings = []
        now = datetime.now()
        warning_threshold = timedelta(days=self.warning_days)

        for name, expiration in self.expirations.items():
            if expiration <= now:
                warnings.append(
                    {
                        "secret": name,
                        "status": "expired",
                        "message": f"{name} has EXPIRED as of {expiration.isoformat()}",
                        "days_until": 0,
                    }
                )
            elif expiration - now <= warning_threshold:
                days_left = (expiration - now).days
                warnings.append(
                    {
                        "secret": name,
                        "status": "expiring_soon",
                        "message": f"{name} expires in {days_left} days ({expiration.isoformat()})",
                        "days_until": days_left,
                    }
                )

        return warnings

    def load_from_env(self):
        """Load expiration dates from environment variables.

        Expected format: RADSIM_SECRET_EXPIRY_<NAME>=YYYY-MM-DD
        Example: RADSIM_SECRET_EXPIRY_ANTHROPIC=2024-12-31
        """
        prefix = "RADSIM_SECRET_EXPIRY_"

        for key, value in os.environ.items():
            if key.startswith(prefix):
                secret_name = key[len(prefix) :]
                try:
                    expiration = datetime.fromisoformat(value)
                    self.expirations[secret_name] = expiration
                except ValueError:
                    logger.debug(f"Invalid date format for secret expiry: {key}={value}")


# Global instances
_health_checker: HealthChecker | None = None
_expiration_monitor: SecretExpirationMonitor | None = None


def get_health_checker(config=None) -> HealthChecker:
    """Get or create the global health checker."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker(config)
    elif config:
        _health_checker.config = config
    return _health_checker


def get_expiration_monitor() -> SecretExpirationMonitor:
    """Get or create the global expiration monitor."""
    global _expiration_monitor
    if _expiration_monitor is None:
        _expiration_monitor = SecretExpirationMonitor()
        _expiration_monitor.load_from_env()
    return _expiration_monitor


def check_health(config=None) -> HealthStatus:
    """Convenience function to run health checks."""
    return get_health_checker(config).run_all_checks()


def validate_startup(config=None) -> bool:
    """Convenience function to run startup validation."""
    return get_health_checker(config).run_startup_validation()


def check_secret_expirations() -> list[dict]:
    """Convenience function to check secret expirations."""
    return get_expiration_monitor().check_expirations()
