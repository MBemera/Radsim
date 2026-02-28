# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Auto-update checker for RadSim.

Checks GitHub for newer releases on startup. Non-blocking, fail-silent.
Respects offline usage and caches results for 24 hours.
"""

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".radsim_cache"
CACHE_FILE = CACHE_DIR / "update_check.json"
CACHE_TTL_HOURS = 24
GITHUB_API_URL = "https://api.github.com/repos/MBemera/Radsim/releases/latest"
REQUEST_TIMEOUT = 3


def _cache_is_fresh() -> bool:
    """Check if the cache file exists and is less than CACHE_TTL_HOURS old."""
    try:
        if not CACHE_FILE.exists():
            return False
        data = json.loads(CACHE_FILE.read_text())
        last_check = data.get("checked_at", 0)
        age_hours = (time.time() - last_check) / 3600
        return age_hours < CACHE_TTL_HOURS
    except Exception:
        return False


def _save_cache(latest_version: str):
    """Save the latest version and timestamp to cache."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "checked_at": time.time(),
            "latest_version": latest_version,
        }
        CACHE_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        logger.debug("Failed to save update check cache")


def _get_cached_version() -> str | None:
    """Get the cached latest version, if cache is fresh."""
    try:
        if not _cache_is_fresh():
            return None
        data = json.loads(CACHE_FILE.read_text())
        return data.get("latest_version")
    except Exception:
        return None


def _version_is_newer(latest: str, current: str) -> bool:
    """Compare version strings (semver-style).

    Returns True if latest > current.
    """
    try:
        latest_parts = [int(x) for x in latest.split(".")]
        current_parts = [int(x) for x in current.split(".")]

        # Pad to same length
        max_len = max(len(latest_parts), len(current_parts))
        latest_parts.extend([0] * (max_len - len(latest_parts)))
        current_parts.extend([0] * (max_len - len(current_parts)))

        return latest_parts > current_parts
    except (ValueError, AttributeError):
        return False


def check_for_updates(current_version: str) -> str | None:
    """Check GitHub for a newer RadSim version. Non-blocking, fail-silent.

    Args:
        current_version: The currently installed version string (e.g., "1.1.0").

    Returns:
        The newer version string if available, or None.
    """
    # Opt-out via environment variable
    if os.getenv("RADSIM_SKIP_UPDATE_CHECK", "").strip() == "1":
        return None

    # Check cache first - skip network call if recently checked
    cached = _get_cached_version()
    if cached is not None:
        if _version_is_newer(cached, current_version):
            return cached
        return None

    # Make the network request
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
            latest_version = data.get("tag_name", "").lstrip("v")

            if not latest_version:
                return None

            _save_cache(latest_version)

            if _version_is_newer(latest_version, current_version):
                return latest_version

    except Exception:
        # Fail silently - network issues, rate limits, etc.
        logger.debug("Update check failed (network error or timeout)")
        return None

    return None


def format_update_notice(latest_version: str, current_version: str) -> str:
    """Format the update notice for display.

    Args:
        latest_version: The newer version available.
        current_version: The currently installed version.

    Returns:
        Formatted string for display.
    """
    return (
        f"  📦 Update available: v{current_version} → v{latest_version}\n"
        f"     Run 'git pull && pip install -e .' to update\n"
    )
