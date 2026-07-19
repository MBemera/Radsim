"""`radsim login <provider>` — guided API-key wizard."""

import getpass
import webbrowser

from .config import ENV_FILE, load_env_file, save_config

PROVIDERS = {
    "openrouter": {
        "label": "OpenRouter (recommended — free models available)",
        "env_var": "OPENROUTER_API_KEY",
        "url": "https://openrouter.ai/keys",
        "default_model": "z-ai/glm-5.2",
    },
    "openai": {
        "label": "OpenAI",
        "env_var": "OPENAI_API_KEY",
        "url": "https://platform.openai.com/api-keys",
        "default_model": "gpt-5.2",
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "env_var": "ANTHROPIC_API_KEY",
        "url": "https://console.anthropic.com/settings/keys",
        "default_model": "claude-sonnet-4-5",
    },
}


def _open_browser(url: str) -> None:
    print(f"  Opening: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        print("  (Could not open browser automatically — visit the URL manually.)")


def _prompt_key(env_var: str) -> str | None:
    """Prompt for an API key with masked input. Empty input cancels."""
    print()
    print(f"  Paste your {env_var} below (input is hidden).")
    print("  Press Enter on an empty line to cancel.")
    try:
        key = getpass.getpass("  > ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None
    return key or None


def _validate_key(provider: str, key: str) -> tuple[bool, str]:
    """Make a cheap call to confirm the key is accepted. Returns (ok, message)."""
    from .api_client import create_client

    try:
        client = create_client(provider, key)
    except Exception as e:
        return False, f"client init failed: {e}"

    try:
        if provider == "openai" or provider == "openrouter":
            client.client.models.list()
        elif provider == "claude":
            client.client.messages.create(
                model=PROVIDERS[provider]["default_model"],
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
    except Exception as e:
        return False, str(e)

    return True, "ok"


def _write_key(env_var: str, key: str, provider: str) -> None:
    """Merge the new key into ~/.radsim/.env preserving other entries."""
    expected_env_var = PROVIDERS[provider]["env_var"]
    if env_var != expected_env_var:
        raise ValueError(f"Unexpected credential variable for provider '{provider}'")
    save_config(key, provider, None)


def run_login(provider: str) -> int:
    """Top-level entry point. Returns a process exit code."""
    if provider not in PROVIDERS:
        print(f"  error: unknown provider '{provider}'.")
        print(f"  Choices: {', '.join(PROVIDERS)}")
        return 2

    info = PROVIDERS[provider]

    print()
    print(f"  RadSim login — {info['label']}")
    print("  ─────────────────────────────────────────────")
    print(f"  Get a key here: {info['url']}")
    _open_browser(info["url"])

    key = _prompt_key(info["env_var"])
    if not key:
        print("  Cancelled.")
        return 1

    if len(key) < 20:
        print("  warning: that doesn't look like an API key (too short).")
        return 1

    print("  Validating with the provider...")
    ok, msg = _validate_key(provider, key)
    if not ok:
        print(f"  error: validation failed — {msg}")
        return 1

    _write_key(info["env_var"], key, provider)
    print()
    print(f"  ok {info['env_var']} saved to {ENV_FILE} (chmod 600).")
    print(f"  RADSIM_PROVIDER set to '{provider}'.")
    return 0


def run_logout(provider: str) -> int:
    """Wipe the API key for a provider from ~/.radsim/.env."""
    if provider not in PROVIDERS:
        print(f"  error: unknown provider '{provider}'.")
        return 2

    info = PROVIDERS[provider]

    if not ENV_FILE.exists():
        print(f"  Nothing to remove for '{provider}'.")
        return 0

    env_config = load_env_file()
    keys = env_config.get("keys", {})
    if info["env_var"] not in keys:
        print(f"  Nothing to remove for '{provider}'.")
        return 0

    del keys[info["env_var"]]

    current_provider = env_config.get("provider", "")
    current_model = env_config.get("model", "")
    lines = [
        "# RadSim Configuration",
        "# This file is chmod 600 (secure) — managed by `radsim login`.",
        "",
    ]
    if current_provider and current_provider != provider:
        lines.append(f'RADSIM_PROVIDER="{current_provider}"')
        if current_model:
            lines.append(f'RADSIM_MODEL="{current_model}"')
        lines.append("")
    lines.append("# API Keys")
    for name, value in keys.items():
        if value and not value.lower().startswith("paste_your"):
            lines.append(f'{name}="{value}"')
    lines.append("")
    ENV_FILE.write_text("\n".join(lines))
    ENV_FILE.chmod(0o600)

    print(f"  ok Removed {info['env_var']} from .env")
    return 0
