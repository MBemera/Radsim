"""Create an isolated, subscription-only Codex process with explicit permissions."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from .codex_transport import CodexError, CodexTransport

SUPPORTED_CODEX_VERSION = "0.153.4"
PERMISSION_PROFILE = "radsim-subscription"
SAFE_ENVIRONMENT = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "WINDIR",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
)


def private_directory(path: Path) -> Path:
    """Create private state without following a symlink at the destination."""
    if path.is_symlink():
        raise CodexError("ChatGPT state directory must not be a symbolic link.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        path.chmod(0o700)
    return path.resolve()


def subscription_directory() -> Path:
    from .config import CONFIG_DIR

    return private_directory(private_directory(Path(CONFIG_DIR)) / "chatgpt")


def codex_environment(home: Path) -> dict[str, str]:
    environment = {key: os.environ[key] for key in SAFE_ENVIRONMENT if key in os.environ}
    environment["CODEX_HOME"] = str(home)
    return environment


def permission_settings(home: Path) -> dict:
    """Default to workspace reads; all elevation requires a fresh user decision."""
    protected = {".": "read", ".git": "read", ".codex": "deny", ".agents": "read"}
    for pattern in ("**/.env*", "**/*.pem", "**/*.key", "**/credentials*", "**/auth.json"):
        protected[pattern] = "deny"
    return {
        "forced_login_method": "chatgpt",
        "cli_auth_credentials_store": "file",
        "model_provider": "openai",
        "approval_policy": "on-request",
        "approvals_reviewer": "user",
        "default_permissions": PERMISSION_PROFILE,
        f"permissions.{PERMISSION_PROFILE}.filesystem": {
            ":root": "deny",
            ":minimal": "read",
            ":workspace_roots": protected,
            str(home): "deny",
            "glob_scan_max_depth": 12,
        },
        f"permissions.{PERMISSION_PROFILE}.network.enabled": False,
        "shell_environment_policy.inherit": "none",
        "features.multi_agent": False,
        "features.apps": False,
    }


def _toml_value(value) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(f"{json.dumps(key)}={_toml_value(item)}" for key, item in value.items())
            + "}"
        )
    return json.dumps(value)


def find_codex(home: Path, environment: dict[str, str]) -> str:
    executable = shutil.which("codex", path=environment.get("PATH", ""))
    if not executable:
        raise CodexError(
            "Codex CLI is missing. Install it using https://learn.chatgpt.com/docs/cli"
        )
    executable = str(Path(executable).resolve())
    if Path(executable).is_relative_to(Path.cwd().resolve()):
        raise CodexError("Refusing to run a Codex executable from the current workspace.")
    try:
        result = subprocess.run(
            [executable, "--version"],
            cwd=home,
            env=environment,
            capture_output=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise CodexError("Could not check the installed Codex CLI version.") from None
    if (
        result.stdout.decode("utf-8", errors="replace").strip()
        != f"codex-cli {SUPPORTED_CODEX_VERSION}"
    ):
        raise CodexError(f"This integration requires tested Codex CLI {SUPPORTED_CODEX_VERSION}.")
    return executable


def open_connection() -> CodexTransport:
    home = private_directory(subscription_directory() / "codex")
    environment = codex_environment(home)
    executable = find_codex(home, environment)
    command = [executable]
    for key, value in permission_settings(home).items():
        command.extend(["--config", f"{key}={_toml_value(value)}"])
    command.extend(["app-server", "--listen", "stdio://"])
    return CodexTransport(command, cwd=str(home), env=environment)
