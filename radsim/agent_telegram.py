"""Telegram runtime helpers for the main agent."""

import logging
import threading
import time

from .output import print_info
from .prompts import get_system_prompt

logger = logging.getLogger(__name__)


def _telegram_confirm(prompt_message):
    """Send confirmation prompt to Telegram and wait for a reply."""
    from .telegram import check_incoming, send_telegram_message

    send_telegram_message(f"Confirm: {prompt_message}\n\nReply 'y' or 'n'")

    deadline = time.time() + 60
    while time.time() < deadline:
        reply = check_incoming()
        if reply:
            answer = reply.get("text", "").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            send_telegram_message("Please reply 'y' or 'n'")
        time.sleep(0.5)

    send_telegram_message("Confirmation timed out — action skipped.")
    return False


def _format_telegram_help(commands):
    """Format help text for Telegram mobile clients."""
    lines = ["*Available Commands*\n"]
    lines.append("Commands you can run from Telegram:\n")

    for command_info in commands[:20]:
        name = command_info["command"]
        description = command_info["description"]
        lines.append(f"`/{name}` - {description}")

    lines.append("\nOther commands require the RadSim terminal.")
    return "\n".join(lines)


def _process_telegram_message(message, registry, agent, set_telegram_confirm):
    """Handle one incoming Telegram text message or slash command."""
    from .telegram import send_telegram_message

    sender = message.get("sender", "Telegram")
    text = message.get("text", "")
    print_info(f"\n[Telegram from {sender}]: {text}")

    if message.get("is_command"):
        command = message["command"]

        if command in ["/help", "/h", "/?"]:
            commands = registry.get_telegram_command_list()
            help_text = _format_telegram_help(commands)
            send_telegram_message(help_text)
            return

        if not registry.is_telegram_safe(command):
            send_telegram_message(
                f"warning: *'{command}' requires terminal interaction*\n\n"
                f"This command needs direct access to your terminal. "
                f"Please run it in the RadSim terminal session.\n\n"
                f"Use /help to see commands available from Telegram.",
                parse_mode="Markdown",
            )
            return

        with agent._processing_lock:
            if registry.handle_input(text, agent):
                send_telegram_message(f"Command executed: {text}")
                agent.system_prompt = get_system_prompt()
                return

    set_telegram_confirm(_telegram_confirm)
    agent._telegram_mode = True
    try:
        with agent._processing_lock:
            response = agent.process_message(f"[via Telegram from {sender}]: {text}")
    finally:
        agent._telegram_mode = False
        set_telegram_confirm(None)

    if response:
        reply = response if len(response) <= 4000 else response[:3997] + "..."
        result = send_telegram_message(reply)
        if result["success"]:
            print_info("[Reply sent to Telegram]")
        else:
            print_info(f"[Telegram reply failed: {result['error']}]")


def _process_callback_query(callback, registry, agent, set_telegram_confirm):
    """Handle one Telegram inline keyboard callback."""
    from .telegram import (
        answer_callback_query,
        handle_callback_query,
        send_telegram_message,
    )

    action = handle_callback_query(callback)
    answer_callback_query(
        callback["callback_query"]["id"],
        text=action.get("response_text"),
    )

    if action["action"] == "execute_command":
        command = action["command"]
        args = action["args"]
        command_string = f"{command} {' '.join(args)}".strip()

        print_info(f"\n[Telegram Button]: {command_string}")

        if not registry.is_telegram_safe(command):
            send_telegram_message(
                f"warning: '{command}' requires terminal interaction. "
                f"Run it in the RadSim terminal session."
            )
            return

        if command in ["/help", "/h", "/?"]:
            _process_telegram_message(
                {
                    "is_command": True,
                    "command": command,
                    "args": args,
                    "text": command_string,
                    "sender": "Button",
                },
                registry,
                agent,
                set_telegram_confirm,
            )
            return

        with agent._processing_lock:
            if registry.handle_input(command_string, agent):
                send_telegram_message(f"Executed: {command_string}")
                agent.system_prompt = get_system_prompt()
    elif action["action"] == "show_help":
        send_telegram_message(action["response_text"])


def start_telegram_processor(agent):
    """Start the background Telegram processor for an agent instance."""
    try:
        from . import telegram as telegram_module  # noqa: F401

        del telegram_module
    except ImportError:
        return

    def telegram_loop():
        from .commands import CommandRegistry
        from .output import print_status_bar
        from .safety import set_telegram_confirm
        from .telegram import (
            check_incoming,
            check_incoming_callback,
            is_listening,
        )

        registry = CommandRegistry()

        while True:
            time.sleep(0.5)
            try:
                if not is_listening():
                    continue

                message = check_incoming()
                if message:
                    _process_telegram_message(message, registry, agent, set_telegram_confirm)

                callback = check_incoming_callback()
                if callback:
                    _process_callback_query(callback, registry, agent, set_telegram_confirm)

                if message or callback:
                    print_status_bar(
                        agent.config.model,
                        agent.usage_stats["input_tokens"],
                        agent.usage_stats["output_tokens"],
                    )
            except Exception as error:
                logger.debug("Telegram processor error: %s", error)

    thread = threading.Thread(target=telegram_loop, daemon=True, name="telegram-processor")
    thread.start()
