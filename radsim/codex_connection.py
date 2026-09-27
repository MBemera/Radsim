"""Create an isolated, subscription-only Codex process with explicit permissions."""

import json
import os
import re
import subprocess
from pathlib import Path

from .codex_transport import CodexError, CodexTransport

CODEX_VERSION_OUTPUT = re.compile(r"codex-cli \d+\.\d+\.\d+\S*")
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


def codex_candidates(path: str) -> list[Path]:
    """List possible Codex executables on PATH, skipping workspace-relative entries.

    Only absolute PATH directories are searched, so a repository cannot supply
    its own `codex` through `.` or a relative entry. Unlike `shutil.which`, the
    current directory is never searched implicitly on Windows.
    """
    names = ["codex"]
    if os.name == "nt":
        extensions = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
        names = [f"codex{extension.lower()}" for extension in extensions if extension]
    candidates = []
    for directory in path.split(os.pathsep):
        if not directory or not os.path.isabs(directory):
            continue
        for name in names:
            candidate = Path(directory) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                candidates.append(candidate)
    return candidates


def find_codex(home: Path, environment: dict[str, str]) -> str:
    candidates = codex_candidates(environment.get("PATH", ""))
    if not candidates:
        raise CodexError(
            "Codex CLI is missing. Install it using https://learn.chatgpt.com/docs/cli"
        )
    executable = str(candidates[0].resolve())
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
    if not CODEX_VERSION_OUTPUT.fullmatch(result.stdout.decode("utf-8", errors="replace").strip()):
        raise CodexError("The `codex` found on PATH did not report a Codex CLI version.")
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
