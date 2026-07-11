"""Build a least-privilege environment for child processes.

RadSim Principle: Explicit Over Implicit.

Shell commands run by the agent should not inherit RadSim's own secrets
(API keys, tokens, passwords). This module produces a copy of the current
environment with secret-bearing variables removed, so a subprocess only
sees what it needs.
"""

import os

# Substrings that mark a variable as secret-bearing. Matched case-insensitively
# against the variable name.
SECRET_NAME_MARKERS = (
    "_KEY",
    "KEY_",
    "APIKEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "PASSPHRASE",
    "CREDENTIAL",
    "PRIVATE",
    "WEBHOOK",
    "SESSION_TOKEN",
)

# Exact variable names always removed regardless of marker matching.
SECRET_NAME_EXACT = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "NPM_TOKEN",
}


def is_secret_variable(name):
    """True if an environment variable name looks secret-bearing."""
    upper = name.upper()
    if upper in SECRET_NAME_EXACT:
        return True
    return any(marker in upper for marker in SECRET_NAME_MARKERS)


def build_child_environment(base_env=None):
    """Return a copy of the environment with secret variables removed.

    Args:
        base_env: Environment mapping to filter (defaults to os.environ).

    Returns:
        A new dict safe to pass as a subprocess ``env``.
    """
    source = os.environ if base_env is None else base_env
    return {name: value for name, value in source.items() if not is_secret_variable(name)}
