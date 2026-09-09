"""Bounded stdio transport for the versioned Codex app-server protocol."""

import json
import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

from .version import get_radsim_version

MAX_FRAME_BYTES = 1024 * 1024
MAX_PENDING_MESSAGES = 32
REQUEST_TIMEOUT = 30.0


class CodexError(RuntimeError):
    """A safe, user-facing failure without raw provider output."""


def describe_failure(error: Any) -> str:
    """Classify provider errors without echoing credentials or request content."""
    text = str(error).lower()
    if any(word in text for word in ("usage limit", "usagelimit", "quota", "rate limit", "429")):
        return (
            "ChatGPT usage limit reached. Wait for your quota to reset; API fallback is disabled."
        )
    if any(word in text for word in ("401", "unauthorized", "expired", "revoked", "auth")):
        return "ChatGPT sign-in is required. Run: radsim login chatgpt"
    return "Codex rejected the request. Check sign-in, model access and CLI compatibility."


class CodexTransport:
    """Own one subprocess and serialize requests while dispatching server events."""

    def __init__(self, command: list[str], *, cwd: str, env: dict[str, str]):
        self.command = command
        self.cwd = cwd
        self.env = env
        self.process: subprocess.Popen | None = None
        self.messages: queue.Queue = queue.Queue(MAX_PENDING_MESSAGES)
        self.failure: CodexError | None = None
        self.reader: threading.Thread | None = None
        self.request_id = 0

    def __enter__(self):
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                env=self.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name == "posix",
            )
            self.reader = threading.Thread(target=self._read_messages, daemon=True)
            self.reader.start()
            self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "radsim",
                        "title": "RadSim",
                        "version": get_radsim_version(),
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.send({"method": "initialized", "params": {}})
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_):
        self.close()

    def _read_messages(self) -> None:
        try:
            while self.process is not None:
                frame = self.process.stdout.readline(MAX_FRAME_BYTES + 1)
                if not frame:
                    self.messages.put(
                        CodexError("Codex exited before completing the request."), timeout=1
                    )
                    return
                self.messages.put(self._decode_frame(frame), timeout=1)
        except (ValueError, OSError, AttributeError, queue.Full, CodexError, RecursionError):
            self.failure = CodexError(
                "Codex sent invalid or excessive protocol output; connection closed."
            )
            if self.process is not None:
                try:
                    self.process.terminate()
                except OSError:
                    pass

    @staticmethod
    def _decode_frame(frame: bytes) -> dict:
        if len(frame) > MAX_FRAME_BYTES or not frame.endswith(b"\n"):
            raise CodexError("Codex message exceeds the protocol limit.")
        message = json.loads(frame)
        if not isinstance(message, dict):
            raise CodexError("Invalid Codex message.")
        if "method" in message and not isinstance(message["method"], str):
            raise CodexError("Invalid Codex method.")
        if "params" in message and not isinstance(message["params"], dict):
            raise CodexError("Invalid Codex parameters.")
        return message

    def receive(self, deadline: float) -> dict:
        while time.monotonic() < deadline:
            if self.failure:
                raise self.failure
            try:
                message = self.messages.get(
                    timeout=min(0.1, max(0.001, deadline - time.monotonic()))
                )
            except queue.Empty:
                continue
            if isinstance(message, CodexError):
                raise message
            return message
        raise CodexError("Codex request timed out; no retry was sent.")

    def send(self, message: dict) -> None:
        frame = json.dumps(message, allow_nan=False).encode("utf-8") + b"\n"
        if len(frame) > MAX_FRAME_BYTES:
            raise CodexError("Request is too large for Codex.")
        if self.process is None or self.process.poll() is not None:
            raise CodexError("Codex connection is closed.")
        completed = threading.Event()
        failures: list[Exception] = []
        writer = threading.Thread(
            target=self._write_frame, args=(frame, completed, failures), daemon=True
        )
        writer.start()
        if not completed.wait(5):
            self.close()
            raise CodexError("Codex stopped accepting requests.")
        if failures:
            raise CodexError("Could not send a request to Codex.") from None

    def _write_frame(self, frame: bytes, completed: threading.Event, failures: list) -> None:
        try:
            self.process.stdin.write(frame)
            self.process.stdin.flush()
        except (OSError, ValueError, AttributeError) as error:
            failures.append(error)
        finally:
            completed.set()

    def request(
        self,
        method: str,
        params: dict,
        *,
        on_event: Callable | None = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> dict:
        self.request_id += 1
        request_id = self.request_id
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            message = self.receive(deadline)
            if "method" in message:
                self.dispatch(message, on_event)
                continue
            if message.get("id") != request_id:
                raise CodexError("Unexpected Codex response identifier.")
            if "error" in message:
                raise CodexError(describe_failure(message["error"]))
            if not isinstance(message.get("result"), dict):
                raise CodexError("Invalid Codex response.")
            return message["result"]

    def dispatch(self, message: dict, handler: Callable | None = None) -> None:
        if handler is not None:
            handler(message)
        elif "id" in message:
            self.reject(message)

    def reject(self, message: dict) -> None:
        self.send(
            {
                "id": message["id"],
                "error": {
                    "code": -32601,
                    "message": "This request is not supported by RadSim.",
                },
            }
        )

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        self._signal_process(process, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._signal_process(process, signal.SIGKILL)
            process.wait(timeout=2)
        self._signal_process(process, signal.SIGKILL)
        for stream in (process.stdin, process.stdout):
            stream.close()
        if self.reader is not None:
            self.reader.join(timeout=2)
        self.process = None

    @staticmethod
    def _signal_process(process: subprocess.Popen, sig: int) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass
        except PermissionError:
            if process.poll() is None:
                process.kill()
