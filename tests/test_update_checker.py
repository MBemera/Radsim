# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Tests for the auto-update checker."""

import json
import time
from unittest.mock import patch

from radsim.update_checker import (
    _cache_is_fresh,
    _get_cached_version,
    _save_cache,
    _version_is_newer,
    check_for_updates,
    format_update_notice,
)


class TestVersionComparison:
    """Tests for version comparison logic."""

    def test_newer_patch(self):
        assert _version_is_newer("1.2.1", "1.2.0") is True

    def test_newer_minor(self):
        assert _version_is_newer("1.3.0", "1.2.0") is True

    def test_newer_major(self):
        assert _version_is_newer("2.0.0", "1.2.0") is True

    def test_same_version(self):
        assert _version_is_newer("1.2.0", "1.2.0") is False

    def test_older_version(self):
        assert _version_is_newer("1.1.0", "1.2.0") is False

    def test_different_length(self):
        assert _version_is_newer("1.2.1", "1.2") is True

    def test_invalid_version(self):
        assert _version_is_newer("abc", "1.2.0") is False

    def test_empty_version(self):
        assert _version_is_newer("", "1.2.0") is False


class TestCache:
    """Tests for cache read/write/freshness."""

    def test_cache_fresh(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "update_check.json"
        monkeypatch.setattr("radsim.update_checker.CACHE_FILE", cache_file)

        data = {"checked_at": time.time(), "latest_version": "1.3.0"}
        cache_file.write_text(json.dumps(data))

        assert _cache_is_fresh() is True

    def test_cache_stale(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "update_check.json"
        monkeypatch.setattr("radsim.update_checker.CACHE_FILE", cache_file)

        data = {"checked_at": time.time() - (25 * 3600), "latest_version": "1.3.0"}
        cache_file.write_text(json.dumps(data))

        assert _cache_is_fresh() is False

    def test_cache_missing(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr("radsim.update_checker.CACHE_FILE", cache_file)

        assert _cache_is_fresh() is False

    def test_save_and_get_cached_version(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        cache_file = cache_dir / "update_check.json"
        monkeypatch.setattr("radsim.update_checker.CACHE_DIR", cache_dir)
        monkeypatch.setattr("radsim.update_checker.CACHE_FILE", cache_file)

        _save_cache("2.0.0")
        assert _get_cached_version() == "2.0.0"


class TestCheckForUpdates:
    """Tests for the main check_for_updates function."""

    def test_opt_out_via_env(self, monkeypatch):
        monkeypatch.setenv("RADSIM_SKIP_UPDATE_CHECK", "1")
        assert check_for_updates("1.0.0") is None

    def test_returns_none_on_same_version(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        cache_file = cache_dir / "update_check.json"
        monkeypatch.setattr("radsim.update_checker.CACHE_DIR", cache_dir)
        monkeypatch.setattr("radsim.update_checker.CACHE_FILE", cache_file)
        monkeypatch.delenv("RADSIM_SKIP_UPDATE_CHECK", raising=False)

        # Write fresh cache with same version
        cache_dir.mkdir(parents=True)
        data = {"checked_at": time.time(), "latest_version": "1.1.0"}
        cache_file.write_text(json.dumps(data))

        assert check_for_updates("1.1.0") is None

    def test_returns_newer_version_from_cache(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        cache_file = cache_dir / "update_check.json"
        monkeypatch.setattr("radsim.update_checker.CACHE_DIR", cache_dir)
        monkeypatch.setattr("radsim.update_checker.CACHE_FILE", cache_file)
        monkeypatch.delenv("RADSIM_SKIP_UPDATE_CHECK", raising=False)

        # Write fresh cache with newer version
        cache_dir.mkdir(parents=True)
        data = {"checked_at": time.time(), "latest_version": "2.0.0"}
        cache_file.write_text(json.dumps(data))

        assert check_for_updates("1.1.0") == "2.0.0"

    def test_network_failure_returns_none(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr("radsim.update_checker.CACHE_FILE", cache_file)
        monkeypatch.setattr("radsim.update_checker.CACHE_DIR", tmp_path)
        monkeypatch.delenv("RADSIM_SKIP_UPDATE_CHECK", raising=False)

        # Mock urllib to raise an error
        with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
            assert check_for_updates("1.0.0") is None


class TestFormatUpdateNotice:
    """Tests for update notice formatting."""

    def test_format(self):
        notice = format_update_notice("2.0.0", "1.1.0")
        assert "2.0.0" in notice
        assert "1.1.0" in notice
        assert "Update available" in notice
