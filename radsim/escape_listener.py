# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Escape key listener for cancelling agent operations.

Monitors stdin for Escape key presses during agent processing.
When Escape is detected, sets the agent's interrupt flag (same as Ctrl+C soft cancel).

The listener can be paused/resumed so that interactive prompts (e.g. y/n/all
confirmation dialogs) can use normal line-buffered input() without interference.
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
        self._paused = threading.Event()  # Set when listener should pause
        self._resumed = threading.Event()  # Set when listener may resume
        self._agent = None
        self._old_settings = None
        self._fd = None

    def start(self, agent):
        """Start listening for Escape key presses.

        Args:
            agent: The RadSimAgent instance (must have _interrupted and _is_processing)
        """
        if self._thread and self._thread.is_alive():
            return

        self._agent = agent
        self._stop_event.clear()
        self._paused.clear()
        self._resumed.set()  # Start in resumed state
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop listening."""
        self._stop_event.set()
        # Unblock any pause wait
        self._resumed.set()
        self._agent = None

    def pause(self):
        """Pause listening and restore normal terminal mode.

        Call this before any interactive input() to prevent the listener
        from consuming stdin characters or leaving the terminal in cbreak mode.
        """
        if not self._thread or not self._thread.is_alive():
            return
        self._resumed.clear()
        self._paused.set()

    def resume(self):
        """Resume listening after a pause."""
        self._paused.clear()
        self._resumed.set()

    def _listen(self):
        """Monitor stdin for Escape key in raw mode."""
        if not sys.stdin.isatty():
            return

        self._fd = sys.stdin.fileno()

        try:
            self._old_settings = termios.tcgetattr(self._fd)
        except termios.error:
            return

        try:
            tty.setcbreak(self._fd)

            while not self._stop_event.is_set():
                # If paused, restore terminal and wait until resumed
                if self._paused.is_set():
                    try:
                        termios.tcsetattr(
                            self._fd, termios.TCSADRAIN, self._old_settings
                        )
                    except termios.error:
                        pass

                    # Wait until resumed or stopped
                    while not self._stop_event.is_set():
                        if self._resumed.wait(timeout=0.1):
                            break

                    if self._stop_event.is_set():
                        return

                    # Re-enter cbreak mode
                    try:
                        tty.setcbreak(self._fd)
                    except termios.error:
                        return
                    continue

                # Check if a key is available (100ms timeout)
                ready, _, _ = select.select([self._fd], [], [], 0.1)
                if not ready:
                    continue

                byte = sys.stdin.buffer.read(1)
                if byte == ESCAPE_BYTE:
                    # Consume any remaining escape sequence bytes (arrow keys etc.)
                    # Arrow keys send \x1b[A etc. — we drain the buffer so they
                    # don't get confused with a standalone Escape press.
                    while select.select([self._fd], [], [], 0.05)[0]:
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
                termios.tcsetattr(
                    self._fd, termios.TCSADRAIN, self._old_settings
                )
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


def pause_escape_listener():
    """Pause the Escape key listener and restore normal terminal mode.

    Call before interactive input() prompts (e.g. confirmation dialogs).
    """
    _listener.pause()


def resume_escape_listener():
    """Resume the Escape key listener after a pause.

    Call after interactive input() prompts complete.
    """
    _listener.resume()
