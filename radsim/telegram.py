"""Telegram Bot integration for RadSim.

Sends and receives messages via the Telegram Bot API using urllib (no extra deps).
Token is stored securely in ~/.radsim/.env as TELEGRAM_BOT_TOKEN.

Listener uses long-polling (getUpdates) in a background thread.
Incoming messages are queued and injected into the agent's input loop.
"""

import json
import logging
import queue
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"
POLL_TIMEOUT = 30  # Long-poll timeout in seconds
POLL_INTERVAL = 2  # Seconds between poll cycles on error


def load_telegram_config():
    """Load Telegram bot token and chat ID from environment.

    Returns:
        Tuple of (token, chat_id) — either may be None
    """
    from .config import load_env_file

    env_config = load_env_file()
    keys = env_config.get("keys", {})
    token = keys.get("TELEGRAM_BOT_TOKEN")
    chat_id = keys.get("TELEGRAM_CHAT_ID")
    return token, chat_id


def save_telegram_config(token, chat_id):
    """Save Telegram config to ~/.radsim/.env (upsert).

    Updates existing keys in-place or appends new ones.
    File is chmod 600 for security.

    Raises:
        ValueError: If token or chat_id fail basic validation.
    """
    from .config import CONFIG_DIR, ENV_FILE

    # --- Validate inputs ---
    if not token or not token.strip():
        raise ValueError("Bot token cannot be empty.")
    if not chat_id or not chat_id.strip():
        raise ValueError("Chat ID cannot be empty.")

    token = token.strip()
    chat_id = chat_id.strip()

    # Basic format checks
    if len(token) < 20:
        raise ValueError("Bot token looks too short. Expected format from @BotFather.")
    if not chat_id.lstrip("-").isdigit():
        raise ValueError("Chat ID must be numeric (may start with '-' for groups).")

    # --- Upsert into .env ---
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    existing_lines = []
    if ENV_FILE.exists():
        existing_lines = ENV_FILE.read_text().splitlines()

    token_key = "TELEGRAM_BOT_TOKEN"
    chat_key = "TELEGRAM_CHAT_ID"
    token_found = False
    chat_found = False
    clean_lines = []

    for line in existing_lines:
        stripped = line.strip()
        if stripped.startswith(f"{token_key}="):
            clean_lines.append(f'{token_key}="{token}"')
            token_found = True
        elif stripped.startswith(f"{chat_key}="):
            clean_lines.append(f'{chat_key}="{chat_id}"')
            chat_found = True
        else:
            clean_lines.append(line)

    # Append any keys that weren't already present
    if not token_found or not chat_found:
        # Remove trailing blanks before appending section
        while clean_lines and clean_lines[-1].strip() == "":
            clean_lines.pop()
        clean_lines.append("")
        clean_lines.append("# Telegram Bot")
        if not token_found:
            clean_lines.append(f'{token_key}="{token}"')
        if not chat_found:
            clean_lines.append(f'{chat_key}="{chat_id}"')

    new_content = "\n".join(clean_lines) + "\n"
    ENV_FILE.write_text(new_content)
    ENV_FILE.chmod(0o600)


def send_telegram_message(message, token=None, chat_id=None):
    """Send a message via Telegram Bot API.

    Args:
        message: Text message to send
        token: Bot token (loads from config if None)
        chat_id: Chat ID to send to (loads from config if None)

    Returns:
        Dict with success status and optional error
    """
    if not token or not chat_id:
        saved_token, saved_chat_id = load_telegram_config()
        token = token or saved_token
        chat_id = chat_id or saved_chat_id

    if not token or not str(token).strip():
        return {"success": False, "error": "No TELEGRAM_BOT_TOKEN configured. Run /telegram setup."}
    if not chat_id or not str(chat_id).strip():
        return {"success": False, "error": "No TELEGRAM_CHAT_ID configured. Run /telegram setup."}

    url = f"{TELEGRAM_API_BASE}{token}/sendMessage"

    def _send(text, parse_mode=None):
        """Send with optional parse_mode. Returns (ok, result_or_error)."""
        body = {"chat_id": chat_id, "text": text}
        if parse_mode:
            body["parse_mode"] = parse_mode
        data = json.dumps(body).encode("utf-8")
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        resp = urlopen(req, timeout=10)
        return json.loads(resp.read().decode("utf-8"))

    try:
        # Try Markdown first, fall back to plain text on parse failure
        try:
            result = _send(message, parse_mode="Markdown")
        except HTTPError as md_err:
            if md_err.code == 400:
                # Markdown parse failure — retry without formatting
                result = _send(message)
            else:
                raise

        if result.get("ok"):
            return {"success": True, "message_id": result["result"]["message_id"]}
        return {"success": False, "error": result.get("description", "Unknown error")}
    except HTTPError as error:
        hints = {
            401: "Invalid bot token. Check it with @BotFather.",
            400: "Bad request — likely an invalid chat_id.",
            403: "Bot was blocked by the user or can't initiate chats.",
            409: "Conflict — another bot instance may be polling.",
        }
        hint = hints.get(error.code, "")
        detail = f"HTTP {error.code}"
        if hint:
            detail += f" — {hint}"
        return {"success": False, "error": detail}
    except URLError as error:
        return {"success": False, "error": f"Network error: {error}"}
    except Exception as error:
        return {"success": False, "error": str(error)}


# =============================================================================
# Telegram Listener (receive messages via long-polling)
# =============================================================================


class TelegramListener:
    """Background listener that polls for incoming Telegram messages.

    Uses getUpdates long-polling in a daemon thread.
    Incoming messages are placed in a queue for the agent to consume.
    """

    def __init__(self):
        self._thread = None
        self._running = False
        self._last_update_id = 0
        self.incoming_messages = queue.Queue()

    @property
    def is_running(self):
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self):
        """Start listening for incoming messages."""
        if self.is_running:
            return

        token, chat_id = load_telegram_config()
        if not token:
            raise ValueError("No TELEGRAM_BOT_TOKEN configured. Run /telegram setup.")
        if not chat_id:
            raise ValueError(
                "No TELEGRAM_CHAT_ID configured. Run /telegram setup. "
                "A chat_id is required for security — the listener will not "
                "start without one."
            )

        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(token, chat_id),
            daemon=True,
            name="telegram-listener",
        )
        self._thread.start()

    def stop(self):
        """Stop listening."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=POLL_TIMEOUT + 5)
            self._thread = None

    def get_message(self):
        """Get next incoming message, or None if queue is empty."""
        try:
            return self.incoming_messages.get_nowait()
        except queue.Empty:
            return None

    def _poll_loop(self, token, allowed_chat_id):
        """Background loop that polls Telegram for new messages."""
        while self._running:
            try:
                updates = self._get_updates(token)
                for update in updates:
                    self._process_update(update, allowed_chat_id)
            except Exception as error:
                logger.debug(f"Telegram poll error: {error}")
                # Wait before retrying on error
                for _ in range(int(POLL_INTERVAL * 10)):
                    if not self._running:
                        return
                    time.sleep(0.1)

    def _get_updates(self, token):
        """Call getUpdates with long-polling."""
        url = f"{TELEGRAM_API_BASE}{token}/getUpdates"
        params = {
            "timeout": POLL_TIMEOUT,
            "allowed_updates": ["message"],
        }
        if self._last_update_id > 0:
            params["offset"] = self._last_update_id + 1

        payload = json.dumps(params).encode("utf-8")
        request = Request(url, data=payload, headers={"Content-Type": "application/json"})
        response = urlopen(request, timeout=POLL_TIMEOUT + 10)
        result = json.loads(response.read().decode("utf-8"))

        if result.get("ok"):
            return result.get("result", [])
        return []

    def _process_update(self, update, allowed_chat_id):
        """Process a single update from Telegram."""
        update_id = update.get("update_id", 0)
        if update_id > self._last_update_id:
            self._last_update_id = update_id

        message = update.get("message", {})
        text = message.get("text", "")
        chat_id = str(message.get("chat", {}).get("id", ""))
        sender = message.get("from", {}).get("first_name", "Unknown")

        if not text:
            return

        # Security: fail-closed — reject ALL messages if no chat_id configured
        if not allowed_chat_id:
            logger.warning(f"Rejected message from chat {chat_id}: no TELEGRAM_CHAT_ID configured")
            return

        # Reject messages from wrong chat ID
        if chat_id != str(allowed_chat_id):
            logger.warning(f"Rejected message from unauthorized chat: {chat_id}")
            return

        self.incoming_messages.put({
            "text": text,
            "sender": sender,
            "chat_id": chat_id,
            "timestamp": message.get("date", 0),
        })


# =============================================================================
# Singleton listener instance
# =============================================================================

_listener = None


def get_listener():
    """Get the singleton TelegramListener instance."""
    global _listener
    if _listener is None:
        _listener = TelegramListener()
    return _listener


def start_listening():
    """Start the Telegram listener.

    Returns:
        Dict with success status
    """
    # Pre-check both token and chat_id before starting
    token, chat_id = load_telegram_config()
    if not token:
        return {"success": False, "error": "No TELEGRAM_BOT_TOKEN configured. Run /telegram setup."}
    if not chat_id:
        return {
            "success": False,
            "error": "No TELEGRAM_CHAT_ID configured. Run /telegram setup. "
            "A chat_id is required for security.",
        }

    try:
        listener = get_listener()
        if listener.is_running:
            return {"success": True, "message": "Already listening"}
        listener.start()
        return {"success": True, "message": "Telegram listener started"}
    except ValueError as error:
        return {"success": False, "error": str(error)}
    except Exception as error:
        return {"success": False, "error": str(error)}


def stop_listening():
    """Stop the Telegram listener.

    Returns:
        Dict with success status
    """
    listener = get_listener()
    if not listener.is_running:
        return {"success": True, "message": "Listener was not running"}
    listener.stop()
    return {"success": True, "message": "Telegram listener stopped"}


def is_listening():
    """Check if the Telegram listener is active."""
    return get_listener().is_running


def check_incoming():
    """Check for incoming Telegram messages.

    Returns:
        Message dict or None
    """
    return get_listener().get_message()
