"""Tests for fast and reliable package version lookup."""

import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path

from radsim.version import DIST_NAME, __version__, get_radsim_version

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_package_import_does_not_load_importlib_metadata():
    """Importing the package should not pay for metadata discovery."""
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import sys; import radsim; print('importlib.metadata' in sys.modules)",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False"


def test_version_uses_installed_package_metadata(monkeypatch):
    """Installed metadata remains authoritative when it exists."""
    import importlib.metadata

    monkeypatch.setattr(importlib.metadata, "version", lambda name: "9.9.9")

    assert get_radsim_version() == "9.9.9"


def test_version_falls_back_to_source_version(monkeypatch):
    """A source checkout without installed metadata uses __version__."""
    import importlib.metadata

    def raise_missing_package(name):
        assert name == DIST_NAME
        raise PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", raise_missing_package)

    assert get_radsim_version() == __version__
