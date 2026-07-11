"""Detect the host OS and available package manager.

RadSim Principle: Explicit Over Implicit.

Installation must not assume Homebrew everywhere. These helpers report the
real operating system and the first package manager actually present, so
callers can pick a command that works on Linux, macOS, and Windows.
"""

import platform
import shutil

# Package managers to probe, in preference order, per OS family.
_MANAGERS_BY_OS = {
    "macos": ["brew"],
    "windows": ["winget", "choco", "scoop"],
    "linux": ["apt-get", "dnf", "yum", "pacman", "zypper", "apk", "brew"],
}


def detect_os():
    """Return the host OS family: 'macos', 'windows', or 'linux'."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return "linux"


def detect_package_manager(os_family=None):
    """Return the first available system package manager, or None.

    Args:
        os_family: Override the OS family (defaults to the detected host).
    """
    os_family = os_family or detect_os()
    for manager in _MANAGERS_BY_OS.get(os_family, []):
        if shutil.which(manager):
            return manager
    return None
