"""ChatGPT sign-in and account status through Codex's managed auth interface."""

import re
import time
import webbrowser
from collections import deque
from collections.abc import Callable
from urllib.parse import urlsplit

from .codex_transport import CodexError, CodexTransport
from .terminal import escape_terminal_controls

LOGIN_TIMEOUT = 300.0


def require_subscription(connection: CodexTransport) -> dict:
    result = connection.request("account/read", {"refreshToken": False})
    account = result.get("account")
    if not isinstance(account, dict) or account.get("type") != "chatgpt":
        raise CodexError("ChatGPT sign-in is required. Run: radsim login chatgpt")
    return account


def trusted_login_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 16384 or any(ord(c) < 33 for c in value):
        raise CodexError("Codex returned an invalid login URL.")
    try:
        url = urlsplit(value)
    except ValueError:
        raise CodexError("Codex returned an invalid login URL.") from None
    if url.scheme != "https" or url.netloc != "auth.openai.com" or url.fragment:
        raise CodexError("Codex returned an unexpected login destination.")
    return value


def _show_login(result: dict, device_code: bool, emit: Callable[[str], None]) -> None:
    key = "verificationUrl" if device_code else "authUrl"
    url = trusted_login_url(result.get(key))
    if device_code:
        code = result.get("userCode", "")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9-]{4,32}", code):
            raise CodexError("Codex returned an invalid device code.")
        emit(f"Open {url} and enter the code: {code}")
        return
    emit("Opening OpenAI sign-in in your browser. Complete it there.")
    if not webbrowser.open(url):
        raise CodexError("Browser could not open. Run: radsim login chatgpt --device-code")


def login(
    connection: CodexTransport, *, device_code: bool = False, emit: Callable[[str], None] = print
) -> None:
    emit("ChatGPT login is stored separately for RadSim; existing Codex sign-in is unchanged.")
    pending = deque()

    def remember(message):
        if "id" in message:
            connection.reject(message)
        elif len(pending) >= 32:
            raise CodexError("Codex sent too many login notifications.")
        else:
            pending.append(message)

    result = connection.request(
        "account/login/start",
        {
            "type": "chatgptDeviceCode" if device_code else "chatgpt",
        },
        on_event=remember,
    )
    login_id = result.get("loginId")
    if not isinstance(login_id, str) or not login_id or len(login_id) > 256:
        raise CodexError("Codex did not return a valid login identifier.")
    try:
        _show_login(result, device_code, emit)
        _wait_for_login(connection, login_id, pending)
        account = require_subscription(connection)
        emit(
            f"Signed in with ChatGPT ({escape_terminal_controls(account.get('planType', 'unknown'))})."
        )
    except BaseException:
        try:
            connection.request("account/login/cancel", {"loginId": login_id}, timeout=3)
        except CodexError:
            pass
        raise


def _wait_for_login(connection: CodexTransport, login_id: str, pending: deque) -> None:
    deadline = time.monotonic() + LOGIN_TIMEOUT
    while True:
        message = pending.popleft() if pending else connection.receive(deadline)
        if "id" in message:
            connection.reject(message)
            continue
        params = message.get("params", {})
        if message.get("method") != "account/login/completed":
            continue
        if params.get("loginId") not in (None, login_id):
            continue
        if params.get("success") is not True:
            raise CodexError("ChatGPT sign-in was cancelled or failed. Try signing in again.")
        return


def list_models(connection: CodexTransport) -> list[dict]:
    require_subscription(connection)
    models = []
    cursor = None
    seen_cursors = set()
    for _ in range(10):
        result = connection.request("model/list", {"cursor": cursor, "limit": 100})
        page = result.get("data")
        if not isinstance(page, list) or len(page) > 100:
            raise CodexError("Codex returned an invalid model catalog.")
        validated = [_validate_model(model) for model in page]
        models.extend(model for model in validated if not model.get("hidden", False))
        cursor = result.get("nextCursor")
        if cursor is None:
            return models
        if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
    raise CodexError("Codex model catalog exceeded its pagination limit.")


def _validate_model(model: dict) -> dict:
    if not isinstance(model, dict) or not isinstance(model.get("model"), str):
        raise CodexError("Codex returned an invalid model entry.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model["model"]):
        raise CodexError("Codex returned an invalid model identifier.")
    return model


def show_status(connection: CodexTransport, emit: Callable[[str], None] = print) -> None:
    account = require_subscription(connection)
    emit(f"ChatGPT subscription: {escape_terminal_controls(account.get('planType', 'unknown'))}")
    result = connection.request("account/rateLimits/read", {})
    limits = result.get("rateLimits") or {}
    if not isinstance(limits, dict):
        raise CodexError("Codex returned invalid quota information.")
    found = False
    for name in ("primary", "secondary"):
        window = limits.get(name)
        if isinstance(window, dict) and isinstance(window.get("usedPercent"), (int, float)):
            found = True
            reset = escape_terminal_controls(window.get("resetsAt", "unknown"))
            emit(
                f"{name.capitalize()} quota: {window['usedPercent']}% used; reset Unix time: {reset}"
            )
    if not found:
        emit("Remaining subscription quota: unknown.")
    emit("Subscription usage is separate from Platform API billing. API fallback is disabled.")
