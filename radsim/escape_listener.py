# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Escape key listener for cancelling agent operations.

Monitors stdin for Escape key presses during agent processing.
When Escape is detected, sets the agent's interrupt flag (same as Ctrl+C soft cancel).
"""

import logging
import select
import sys
import termios
import threading
import tty

logger = logging.getLogger(__name__)

ESCAPE_BYTE = b"\x1b"


class EscapeListener:
    """Background listener that detects Escape key presses."""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._agent = None

    def start(self, agent):
        """Start listening for Escape key presses.

        Args:
            agent: The RadSimAgent instance (must have _interrupted and _is_processing)
        """
        if self._thread and self._thread.is_alive():
            return

        self._agent = agent
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop listening."""
        self._stop_event.set()
        self._agent = None

    def _listen(self):
        """Monitor stdin for Escape key in raw mode."""
        if not sys.stdin.isatty():
            return

        fd = sys.stdin.fileno()

        try:
            old_settings = termios.tcgetattr(fd)
        except termios.error:
            return

        try:
            tty.setcbreak(fd)

            while not self._stop_event.is_set():
                # Check if a key is available (100ms timeout)
                ready, _, _ = select.select([fd], [], [], 0.1)
                if not ready:
                    continue

                byte = sys.stdin.buffer.read(1)
                if byte == ESCAPE_BYTE:
                    # Consume any remaining escape sequence bytes (arrow keys etc.)
                    # Arrow keys send \x1b[A etc. — we drain the buffer so they
                    # don't get confused with a standalone Escape press.
                    while select.select([fd], [], [], 0.05)[0]:
                        extra = sys.stdin.buffer.read(1)
                        if extra:
                            # This was part of an escape sequence, not a bare Escape
                            byte = None
                            break

                    if byte == ESCAPE_BYTE and self._agent:
                        if self._agent._is_processing.is_set():
                            self._agent._interrupted.set()
                            sys.stdout.write(
                                "\n\n  \x1b[33m⚠ Cancelling... (Esc pressed)\x1b[0m\n"
                            )
                            sys.stdout.flush()
                            return
        except Exception as e:
            logger.debug(f"Escape listener error: {e}")
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except termios.error:
                pass


# Singleton
_listener = EscapeListener()


def start_escape_listener(agent):
    """Start the Escape key listener for the given agent."""
    _listener.start(agent)


def stop_escape_listener():
    """Stop the Escape key listener."""
    _listener.stop()
