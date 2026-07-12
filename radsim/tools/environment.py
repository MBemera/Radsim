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
    "AUTH",
    "BEARER",
    "COOKIE",
    "JWT",
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
    # Connection strings embed credentials even though the name has no marker.
    "DATABASE_URL",
    "REDIS_URL",
    "MONGODB_URI",
    "SENTRY_DSN",
    # Shell and runtime startup hooks can execute code before the validated
    # command starts.
    "BASH_ENV",
    "ENV",
    "PROMPT_COMMAND",
    "PS4",
    "SHELLOPTS",
    "BASHOPTS",
    "CDPATH",
    "GLOBIGNORE",
    "ZDOTDIR",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "NODE_OPTIONS",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "RUBYOPT",
    "PERL5OPT",
    "JAVA_TOOL_OPTIONS",
    "_JAVA_OPTIONS",
    # Credential brokers and config paths grant subprocesses indirect access.
    "SSH_AUTH_SOCK",
    "GPG_AGENT_INFO",
    "GIT_ASKPASS",
    "GIT_ASKPASS_REQUIRE",
    "GIT_DIFF_OPTS",
    "GIT_DIR",
    "GIT_EXEC_PATH",
    "GIT_EXTERNAL_DIFF",
    "GIT_WORK_TREE",
    "SSH_ASKPASS",
    "SUDO_ASKPASS",
    "KUBECONFIG",
    "DOCKER_CONFIG",
    "NETRC",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "AZURE_CONFIG_DIR",
    "CLOUDSDK_CONFIG",
    # Package-source and proxy overrides are a supply-chain boundary.
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_TRUSTED_HOST",
    "PIP_CONFIG_FILE",
    "UV_INDEX",
    "UV_EXTRA_INDEX_URL",
    "NPM_CONFIG_REGISTRY",
    "YARN_NPM_REGISTRY_SERVER",
    "BUN_INSTALL_REGISTRY",
    "GOPROXY",
    "GONOSUMDB",
    "GOINSECURE",
    "CARGO_REGISTRIES_CRATES_IO_INDEX",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
}

SECRET_NAME_PREFIXES = (
    "BASH_FUNC_",
    "DYLD_",
    "GIT_CONFIG",
    "GIT_SSH",
    "GIT_TRACE",
)


def is_secret_variable(name):
    """True if an environment variable name looks secret-bearing."""
    upper = name.upper()
    if upper in SECRET_NAME_EXACT:
        return True
    if upper.startswith(SECRET_NAME_PREFIXES):
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
