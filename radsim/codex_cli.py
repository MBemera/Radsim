"""Account commands for the ChatGPT subscription (sign in, quota, models).

Sessions themselves run in RadSim's own agent loop through
`radsim/chatgpt_client.py`; this module only manages the Codex-held sign-in.
"""

import datetime
import sys

from .codex_auth import (
    available_reset_credits,
    consume_reset_credit,
    list_models,
    login,
    show_status,
)
from .codex_connection import open_connection
from .codex_transport import CodexError
from .terminal import escape_terminal_controls


def emit(text: str) -> None:
    print(escape_terminal_controls(text, preserve_layout=True), flush=True)


def ask(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise EOFError
    return input(prompt)


def run_account_command(action: str, *, device_code: bool = False) -> int:
    from .access_control import check_access_on_startup

    if not check_access_on_startup():
        return 1
    try:
        with open_connection() as connection:
            if action == "login":
                login(connection, device_code=device_code, emit=emit)
                _remember_subscription_choice(connection)
            elif action == "logout":
                connection.request("account/logout", {})
                _forget_subscription_choice()
                emit("Signed out of RadSim's ChatGPT account.")
            elif action == "status":
                show_status(connection, emit)
            elif action == "models":
                print_models(connection)
            elif action == "reset":
                redeem_reset_credit(connection)
            else:
                raise CodexError("Unknown ChatGPT account command.")
        return 0
    except KeyboardInterrupt:
        emit("ChatGPT sign-in cancelled.")
        return 130
    except (CodexError, OSError) as error:
        return report_error(error)


def _remember_subscription_choice(connection) -> None:
    """Default later sessions to the subscription, like the API-key logins do."""
    from .config import save_subscription_selection

    try:
        save_subscription_selection(account_default_model(connection))
    except OSError:
        emit("Signed in, but the default provider could not be saved.")
        return
    emit("RadSim will use your ChatGPT subscription by default.")
    emit("Switch back with: radsim --provider openrouter (or openai, claude).")


def _forget_subscription_choice() -> None:
    from .config import clear_subscription_selection

    clear_subscription_selection()


def account_default_model(connection) -> str:
    """Return the account's default model, or "" when it cannot be read."""
    try:
        models = list_models(connection)
    except CodexError:
        return ""
    for model in models:
        if model.get("isDefault"):
            return model["model"]
    return models[0]["model"] if models else ""


def report_error(error: Exception) -> int:
    emit(
        str(error)
        if isinstance(error, CodexError)
        else "Could not access the local ChatGPT runtime or state."
    )
    return 1


def describe_expiry(expires_at) -> str:
    """Say when a credit expires, or nothing when the account omits it."""
    if not isinstance(expires_at, (int, float)):
        return ""
    stamp = datetime.datetime.fromtimestamp(expires_at).strftime("%d %b %Y")
    return f", expires {stamp}"


def redeem_reset_credit(connection) -> None:
    """Spend one banked usage reset, after the user confirms it.

    A reset is single-use and cannot be undone, so it is never spent
    without an explicit yes.
    """
    credits = available_reset_credits(connection)
    if not credits:
        emit("No banked usage reset is available on this account.")
        return

    credit = credits[0]
    emit(f"Banked usage reset: {credit['title']}{describe_expiry(credit['expires_at'])}")
    emit(f"{len(credits)} available. Using one clears your reached limits now.")
    try:
        answer = ask("  Use it now? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        emit("Usage reset cancelled.")
        return
    if answer not in ("y", "yes"):
        emit("Usage reset cancelled. Nothing was spent.")
        return

    emit(consume_reset_credit(connection, credit["id"]))
    show_status(connection, emit)


def print_models(connection) -> None:
    for model in list_models(connection):
        suffix = " (default)" if model.get("isDefault") else ""
        emit(f"{model['model']}{suffix}")
