"""Safety guardrails and confirmations for RadSim Agent."""

import os
from pathlib import Path

# Commands that trigger immediate process termination from any prompt
STOP_COMMANDS = {"/stop", "/kill", "/abort"}


def _emergency_stop():
    """Immediately terminate the process."""
    print("\n  🛑 EMERGENCY STOP - Terminating immediately!")
    os._exit(1)


# Patterns that should never be written
DANGEROUS_PATTERNS = [
    ".env",
    "credentials",
    "secrets",
    ".git/config",
    "id_rsa",
    "id_ed25519",
    ".pem",
    "password",
]

# File extensions that are safe to write
SAFE_EXTENSIONS = [
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".rb",
    ".java",
    ".kt",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".html",
    ".css",
    ".scss",
    ".sass",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".md",
    ".txt",
    ".rst",
    ".vue",
    ".svelte",
]


def is_path_safe(file_path):
    """Check if a file path is safe to write to."""
    path_lower = file_path.lower()

    # Check for dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if pattern in path_lower:
            return False, f"Cannot write to files matching '{pattern}'"

    return True, None


def is_extension_safe(file_path):
    """Check if file extension is in the safe list."""
    path = Path(file_path)
    extension = path.suffix.lower()

    if not extension:
        return True, None  # No extension is okay (like Makefile)

    if extension in SAFE_EXTENSIONS:
        return True, None

    return False, f"Uncommon file extension: {extension}"


def confirm_write(file_path, content, config=None):
    """Ask user to confirm a file write operation."""
    # Check safety first, even in auto mode
    safe, reason = is_path_safe(file_path)
    if not safe:
        print(f"\n⚠️  BLOCKED: {reason}")
        return False

    if config and config.auto_confirm:
        print(f"  > Auto-writing: {file_path}")
        return True

    # Check extension
    ext_safe, ext_reason = is_extension_safe(file_path)
    if not ext_safe:
        print(f"\n⚠️  Warning: {ext_reason}")

    # Show preview - use teach-aware display when teach mode is active
    teach_active = False
    try:
        from .modes import is_mode_active
        teach_active = is_mode_active("teach")
    except Exception:
        pass

    if teach_active:
        from .output import print_code_content
        print()
        print_code_content(
            content,
            file_path,
            max_lines=50,
            collapsed=False,
            highlight_teach=True,
        )
    else:
        print(f"\n📄 File: {file_path}")
        print("-" * 50)

        # Show content preview (first 30 lines)
        lines = content.split("\n")
        preview_lines = lines[:30]
        print("\n".join(preview_lines))

        if len(lines) > 30:
            print(f"\n... ({len(lines) - 30} more lines)")

        print("-" * 50)

    # Check if file exists
    if Path(file_path).exists():
        print("⚠️  This will OVERWRITE the existing file!")

    # Ask for confirmation - loop to allow 's' to show full code first
    try:
        while True:
            # Check if teach mode is active for the prompt hint
            show_hint = ""
            try:
                from .modes import is_mode_active
                if is_mode_active("teach"):
                    show_hint = "/s=show all"
            except Exception:
                pass

            prompt_options = "[y/n/all]" if not show_hint else f"[y/n/all/{show_hint}]"
            response = input(f"\nWrite this file? {prompt_options}: ").strip()

            # Check for emergency stop commands
            if response.lower() in STOP_COMMANDS:
                _emergency_stop()

            # Handle Shift+Tab (\x1b[Z)
            if "\x1b[Z" in response:
                response = "all"

            response_lower = response.lower()

            # Handle 's' - show full code and re-prompt
            if response_lower == "s":
                from .output import print_code_content
                print()
                print_code_content(
                    content,
                    file_path,
                    max_lines=0,  # Show ALL lines
                    collapsed=False,
                    highlight_teach=True,
                )
                print()
                continue  # Re-prompt for y/n/all

            if response_lower in ["y", "yes"]:
                return True

            if response_lower in ["a", "all", "always"]:
                if config:
                    config.auto_confirm = True
                    print("  ✓ Auto-confirm enabled (dangerous actions will still prompt)")
                return True

            return False
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False


def confirm_action(message, config=None):
    """Ask user to confirm an action."""
    if config and config.auto_confirm:
        return True

    try:
        response = input(f"\n{message} [y/n/all]: ").strip()

        # Check for emergency stop commands
        if response.lower() in STOP_COMMANDS:
            _emergency_stop()

        # Handle Shift+Tab (\x1b[Z)
        if "\x1b[Z" in response:
            response = "all"

        response = response.lower()

        if response in ["y", "yes"]:
            return True

        if response in ["a", "all", "always"]:
            if config:
                config.auto_confirm = True
                print("  ✓ Auto-confirm enabled (dangerous actions will still prompt)")
            return True

        return False
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False
