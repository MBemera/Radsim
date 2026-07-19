#!/usr/bin/env python3
"""
RadSim Universal Installer

Cross-platform installer that works on Windows, macOS, and Linux.
Requires Python 3.10 or higher.

Usage:
    python install.py
"""

import argparse
import ntpath
import os
import platform
import subprocess
import sys
import sysconfig
from pathlib import Path

# Minimum Python version required
MIN_PYTHON_VERSION = (3, 10)


def print_banner():
    """Display the installation banner."""
    print()
    print("  +-------------------------------------+")
    print("  |         RadSim Installer            |")
    print("  |   Radically Simple Code Generator   |")
    print("  +-------------------------------------+")
    print()


def print_success(message):
    """Print success message."""
    print(f"[OK] {message}")


def print_info(message):
    """Print info message."""
    print(f"[..] {message}")


def print_error(message):
    """Print error message."""
    print(f"[ERROR] {message}")


def check_python_version():
    """Verify Python version is 3.10 or higher."""
    current_version = sys.version_info[:2]

    if current_version < MIN_PYTHON_VERSION:
        print_error(
            f"Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}+ required. "
            f"Found: {current_version[0]}.{current_version[1]}"
        )
        print()
        print("Please install a newer Python version from: https://www.python.org/downloads/")
        return False

    version_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print_success(f"Python {version_str} detected")
    return True


def check_pip():
    """Verify pip is available."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print_error("pip is not installed.")
        print()
        print("Please install pip:")
        print("  https://pip.pypa.io/en/stable/installation/")
        return False

    print_success("pip available")
    return True


def detect_platform():
    """Detect the operating system."""
    system = platform.system().lower()

    if system == "darwin":
        return "macos"
    elif system == "windows":
        return "windows"
    elif system == "linux":
        return "linux"
    else:
        return system


def install_radsim():
    """Install radsim from PyPI."""
    print_info("Installing RadSim from PyPI...")

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "radsimcli", "--quiet"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print_error(f"Installation failed: {result.stderr}")
        return False

    print_success("RadSim installed")
    return True


def verify_command():
    """Check if the radsim command is accessible."""
    # Check common locations
    import shutil

    if shutil.which("radsim"):
        print_success("'radsim' command is available")
        return True

    return False


def update_path_unix():
    """Add pip scripts directory to PATH if needed (Unix only)."""
    shell = os.environ.get("SHELL", "")
    home = Path.home()
    bin_dir = home / ".local" / "bin"

    # Determine shell config file
    shell_rc = None
    if "zsh" in shell:
        shell_rc = home / ".zshrc"
    elif "bash" in shell:
        if platform.system() == "Darwin":
            bash_profile = home / ".bash_profile"
            if bash_profile.exists():
                shell_rc = bash_profile
        if not shell_rc:
            shell_rc = home / ".bashrc"

    if not shell_rc:
        return False

    # Check if already in PATH config
    if shell_rc.exists():
        rc_content = shell_rc.read_text()
        if str(bin_dir) in rc_content or ".local/bin" in rc_content:
            print_success("PATH already configured")
            return False

    # Add to shell config
    with open(shell_rc, "a") as f:
        f.write("\n# RadSim\n")
        f.write('export PATH="$HOME/.local/bin:$PATH"\n')

    print_success(f"Added ~/.local/bin to PATH in {shell_rc.name}")
    return True


def find_windows_scripts_directory():
    """Return the Scripts directory containing radsim.exe when available."""
    candidates = [
        Path(sysconfig.get_path("scripts", "nt_user")),
        Path(sysconfig.get_path("scripts")),
    ]
    for scripts_directory in candidates:
        if (scripts_directory / "radsim.exe").is_file():
            return scripts_directory
    return candidates[-1]


def _path_contains_directory(path_value, directory):
    """Return whether a semicolon-delimited Windows PATH contains a directory."""
    expected = ntpath.normcase(ntpath.normpath(str(directory)))
    entries = [entry.strip().strip('"') for entry in path_value.split(";") if entry.strip()]
    return any(ntpath.normcase(ntpath.normpath(entry)) == expected for entry in entries)


def update_path_windows(scripts_directory=None):
    """Add the active pip Scripts directory to the user PATH."""
    scripts_directory = scripts_directory or find_windows_scripts_directory()
    scripts_directory = str(scripts_directory)
    user_path = os.environ.get("PATH", "")

    if _path_contains_directory(user_path, scripts_directory):
        print_success("PATH already configured")
        return False

    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS)
        try:
            try:
                current_path, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current_path = ""

            if _path_contains_directory(current_path, scripts_directory):
                print_success("PATH already configured")
                return False

            separator = ";" if current_path else ""
            new_path = f"{scripts_directory}{separator}{current_path}"
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
            print_success(f"Added {scripts_directory} to user PATH")
            return True
        finally:
            winreg.CloseKey(key)
    except Exception:
        print_info(f"Please add {scripts_directory} to your PATH manually")
        return True

def print_next_steps(os_type, path_updated):
    """Print post-installation instructions."""
    print()
    print("=" * 48)
    print("  RadSim installed successfully!")
    print("=" * 48)
    print()
    print("To get started:")
    print()

    if path_updated:
        print("  1. Restart your terminal")
        print()

    print("  Run RadSim:")
    print("     radsim")
    print()
    print("  On first run, RadSim will guide you through setup")
    print("  (provider selection, API key, preferences).")
    print()


def main():
    """Main installation entry point."""
    parser = argparse.ArgumentParser(
        description="RadSim Universal Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python install.py                    # Install RadSim with all providers
        """,
    )

    parser.parse_args()

    # Display banner
    print_banner()

    # Step 1: Check Python version
    if not check_python_version():
        sys.exit(1)

    # Step 2: Check pip
    if not check_pip():
        sys.exit(1)

    # Step 3: Detect platform
    os_type = detect_platform()
    print_success(f"Platform: {os_type}")

    # Step 4: Install radsim from PyPI
    if not install_radsim():
        sys.exit(1)

    # Step 6: Verify command and update PATH if needed
    path_updated = False
    if not verify_command():
        if os_type == "windows":
            path_updated = update_path_windows()
        else:
            path_updated = update_path_unix()

    # Step 7: Print next steps
    print_next_steps(os_type, path_updated)

    return 0


if __name__ == "__main__":
    sys.exit(main())
