"""Read the ChatGPT sign-in that Codex stores for RadSim.

RadSim never runs the OAuth flow itself: `radsim login chatgpt` signs in through
Codex, and Codex owns the refresh. This module reads the resulting token store
and asks Codex to refresh it when the access token is close to expiring.
"""

import base64
import json
import time
from pathlib import Path

from .codex_transport import CodexError

REFRESH_MARGIN_SECONDS = 300
SIGN_IN_MESSAGE = "ChatGPT sign-in is required. Run: radsim login chatgpt"


def auth_file() -> Path:
    from .codex_connection import subscription_directory

    return subscription_directory() / "codex" / "auth.json"


def token_expiry(token: str) -> float:
    """Return a JWT's expiry time without verifying it; 0.0 when unreadable."""
    parts = token.split(".")
    if len(parts) != 3:
        return 0.0
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return 0.0
    expiry = claims.get("exp") if isinstance(claims, dict) else None
    return float(expiry) if isinstance(expiry, (int, float)) else 0.0


def read_tokens() -> dict:
    path = auth_file()
    if not path.exists() or path.is_symlink():
        raise CodexError(SIGN_IN_MESSAGE)
    try:
        stored = json.loads(path.read_text())
    except (OSError, ValueError):
        raise CodexError(SIGN_IN_MESSAGE) from None
    tokens = stored.get("tokens") if isinstance(stored, dict) else None
    if not isinstance(tokens, dict):
        raise CodexError(SIGN_IN_MESSAGE)
    return tokens


def refresh_through_codex() -> None:
    """Let Codex refresh its own tokens and rewrite its store."""
    from .codex_connection import open_connection

    with open_connection() as connection:
        connection.request("account/read", {"refreshToken": True})


def load_subscription_credentials() -> tuple[str, str]:
    """Return a usable (access token, account id) for the ChatGPT backend."""
    tokens = read_tokens()
    access_token = tokens.get("access_token", "")
    if not isinstance(access_token, str) or token_expiry(access_token) - time.time() < (
        REFRESH_MARGIN_SECONDS
    ):
        refresh_through_codex()
        tokens = read_tokens()
        access_token = tokens.get("access_token", "")

    account_id = tokens.get("account_id", "")
    if not isinstance(access_token, str) or not access_token:
        raise CodexError(SIGN_IN_MESSAGE)
    if not isinstance(account_id, str) or not account_id:
        raise CodexError("ChatGPT sign-in has no account. Run: radsim login chatgpt")
    return access_token, account_id
