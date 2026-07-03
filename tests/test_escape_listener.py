"""Tests for the Escape listener pause/resume handshake.

The handshake is what prevents the listener from stealing keystrokes
meant for y/n confirmation prompts (which locked the chat).
"""

import threading
import time

from radsim.escape_listener import EscapeListener


class TestPauseHandshake:
    def test_pause_without_thread_returns_immediately(self):
        listener = EscapeListener()

        started = time.monotonic()
        listener.pause()
        elapsed = time.monotonic() - started

        assert elapsed < 0.1

    def test_pause_waits_for_listener_acknowledgement(self):
        """pause() must not return until the listener has released stdin."""
        listener = EscapeListener()
        ack_delay = 0.15

        def fake_listener():
            # Mimic the listener loop: acknowledge the pause after a delay,
            # then wait for resume or stop.
            while not listener._stop_event.is_set():
                if listener._paused.is_set():
                    time.sleep(ack_delay)
                    listener._pause_ready.set()
                    listener._resumed.wait(timeout=1.0)
                    return
                time.sleep(0.01)

        listener._thread = threading.Thread(target=fake_listener, daemon=True)
        listener._thread.start()

        started = time.monotonic()
        listener.pause()
        elapsed = time.monotonic() - started

        assert listener._pause_ready.is_set()
        assert elapsed >= ack_delay
        listener.stop()

    def test_pause_is_idempotent(self):
        """A second pause() while already paused must not hang."""
        listener = EscapeListener()

        def fake_listener():
            listener._paused.wait(timeout=1.0)
            listener._pause_ready.set()
            listener._resumed.wait(timeout=1.0)

        listener._thread = threading.Thread(target=fake_listener, daemon=True)
        listener._thread.start()

        listener.pause()
        started = time.monotonic()
        listener.pause()  # Already paused — must return immediately
        elapsed = time.monotonic() - started

        assert elapsed < 0.1
        listener.stop()

    def test_pause_times_out_on_wedged_listener(self):
        """A listener that never acknowledges must not hang the prompt."""
        listener = EscapeListener()

        def wedged_listener():
            time.sleep(5)

        listener._thread = threading.Thread(target=wedged_listener, daemon=True)
        listener._thread.start()

        started = time.monotonic()
        listener.pause()
        elapsed = time.monotonic() - started

        # Bounded by PAUSE_ACK_TIMEOUT (1s), not the thread's 5s sleep
        assert elapsed < 2.0

    def test_stop_joins_listener_thread(self):
        """stop() must wait for the thread so the terminal is restored
        before the next prompt is shown."""
        listener = EscapeListener()

        def fake_listener():
            listener._stop_event.wait(timeout=2.0)

        listener._thread = threading.Thread(target=fake_listener, daemon=True)
        listener._thread.start()

        listener.stop()

        assert not listener._thread.is_alive()


class TestSafeInputPausesListener:
    def test_safe_input_pauses_and_resumes(self, monkeypatch):
        """Menus can appear mid-processing — safe_input must pause the
        listener so it cannot consume the user's answer."""
        import radsim.escape_listener as el
        import radsim.menu as menu

        calls = []
        monkeypatch.setattr(el, "_listener", EscapeListener())
        monkeypatch.setattr(
            el, "pause_escape_listener", lambda: calls.append("pause")
        )
        monkeypatch.setattr(
            el, "resume_escape_listener", lambda: calls.append("resume")
        )
        monkeypatch.setattr(menu, "_flush_stdin", lambda: None)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        result = menu.safe_input("pick: ")

        assert result == "y"
        assert calls == ["pause", "resume"]

    def test_safe_input_resumes_on_cancel(self, monkeypatch):
        import radsim.escape_listener as el
        import radsim.menu as menu

        calls = []
        monkeypatch.setattr(
            el, "pause_escape_listener", lambda: calls.append("pause")
        )
        monkeypatch.setattr(
            el, "resume_escape_listener", lambda: calls.append("resume")
        )
        monkeypatch.setattr(menu, "_flush_stdin", lambda: None)

        def raise_interrupt(prompt=""):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", raise_interrupt)

        result = menu.safe_input("pick: ")

        assert result is None
        assert calls == ["pause", "resume"]
