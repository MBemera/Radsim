"""Secure Access Control - RadSim Principle: Defense in Depth.

Access code security:
1. Never logged to any file or database
2. Never printed to console (uses getpass)
3. Never committed to version control
4. Loaded from environment variable only
5. Uses constant-time comparison (prevents timing attacks)
"""

import hmac
import os


def _secure_compare(provided: str, stored: str) -> bool:
    """Compare strings in constant time to prevent timing attacks.

    RadSim Principle: Security by Default
    Timing attacks can reveal password length/characters by measuring
    comparison time. HMAC compare_digest prevents this.
    """
    return hmac.compare_digest(provided.encode("utf-8"), stored.encode("utf-8"))


def get_access_code_from_env() -> str | None:
    """Load access code from environment (never log this value)."""
    # Check ~/.radsim/.env first, then system env
    from .config import load_env_file

    env_config = load_env_file()

    # Look for RADSIM_ACCESS_CODE in .env keys
    if "keys" in env_config and "RADSIM_ACCESS_CODE" in env_config["keys"]:
        return env_config["keys"]["RADSIM_ACCESS_CODE"]

    # Fall back to system environment
    return os.getenv("RADSIM_ACCESS_CODE")


def is_access_protected() -> bool:
    """Check if access code protection is enabled."""
    code = get_access_code_from_env()
    return bool(code and code.strip())


def verify_access_code(user_input: str) -> bool:
    """Verify access code without logging.

    SECURITY: This function never logs the input or stored code.
    Returns True if code matches, False otherwise.
    """
    stored_code = get_access_code_from_env()

    if not stored_code:
        return True  # No code configured = no protection

    return _secure_compare(user_input.strip(), stored_code.strip())


def prompt_for_access() -> bool:
    """Prompt user for access code in interactive mode.

    Uses getpass to hide input from terminal.
    Never logs or prints the entered code.
    """
    if not is_access_protected():
        return True

    import getpass

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            code = getpass.getpass("🔐 Enter access code: ")
            if verify_access_code(code):
                return True
            remaining = max_attempts - attempt - 1
            if remaining > 0:
                print(f"  ❌ Invalid code. {remaining} attempts remaining.")
        except (KeyboardInterrupt, EOFError):
            print("\n  Access cancelled.")
            return False

    print("  ❌ Access denied.")
    return False


def check_access_on_startup() -> bool:
    """Verify access code on startup if protection is enabled.

    Call this from CLI before starting the agent.
    """
    return prompt_for_access()
