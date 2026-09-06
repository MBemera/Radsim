"""A Codex-owned conversation, separate from RadSim's API-provider agent loop."""

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path

from .codex_approvals import CodexApprovals
from .codex_auth import list_models, require_subscription
from .codex_connection import PERMISSION_PROFILE, subscription_directory
from .codex_transport import CodexError, CodexTransport, describe_failure
from .persistence import atomic_write_json

TURN_TIMEOUT = 900.0
MAX_OUTPUT_CHARS = 4 * 1024 * 1024
MAX_TURN_ITEMS = 1024


def valid_identifier(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None


def session_file(workspace: Path) -> Path:
    digest = hashlib.sha256(str(workspace).encode()).hexdigest()
    return subscription_directory() / "sessions" / f"{digest}.json"


def load_session(workspace: Path) -> dict:
    path = session_file(workspace)
    if not path.exists():
        raise CodexError("No saved ChatGPT conversation for this directory.")
    if path.is_symlink() or path.stat().st_size > 4096:
        raise CodexError("Invalid ChatGPT session metadata.")
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        raise CodexError("Could not read ChatGPT session metadata.") from None
    if (
        not isinstance(data, dict)
        or data.get("cwd") != str(workspace)
        or not valid_identifier(data.get("threadId"))
    ):
        raise CodexError("ChatGPT session does not belong to this directory.")
    return data


class CodexRuntime:
    def __init__(
        self,
        connection: CodexTransport,
        workspace: Path,
        *,
        ask: Callable[[str], str],
        emit: Callable[[str], None],
        stream: Callable[[str], None],
    ):
        self.connection = connection
        self.workspace = workspace.resolve()
        self.emit = emit
        self.stream = stream
        self.approvals = CodexApprovals(self.workspace, ask=ask, emit=emit)
        self.thread_id: str | None = None
        self.turn_id: str | None = None
        self.model: str | None = None
        self.completed: dict | None = None
        self.output_chars = 0
        self.streamed_items: set[str] = set()
        self.usage: dict = {}

    def start(self, model: str | None = None, resume: str | None = None) -> None:
        models = list_models(self.connection)
        if resume == "last":
            saved = load_session(self.workspace)
            resume, model = saved["threadId"], model or saved.get("model")
        self.model = self._select_model(models, model)
        params = self._thread_settings()
        method = "thread/start"
        if resume:
            if not valid_identifier(resume):
                raise CodexError("Invalid ChatGPT conversation identifier.")
            self._check_resume(resume)
            method = "thread/resume"
            params.update(threadId=resume, excludeTurns=True)
        else:
            params.update(allowProviderModelFallback=False, ephemeral=False)
        result = self.connection.request(method, params)
        self._verify_thread(result)
        self.thread_id = result["thread"]["id"]
        self._save_session()

    @staticmethod
    def _select_model(models: list[dict], selected: str | None) -> str:
        available = {model["model"] for model in models}
        if selected:
            if selected not in available:
                raise CodexError("Selected model is unavailable. Run: radsim models chatgpt")
            return selected
        defaults = [model["model"] for model in models if model.get("isDefault") is True]
        if not defaults:
            raise CodexError("No default subscription model found. Select one with --model.")
        return defaults[0]

    def _thread_settings(self) -> dict:
        return {
            "model": self.model,
            "modelProvider": "openai",
            "cwd": str(self.workspace),
            "runtimeWorkspaceRoots": [str(self.workspace)],
            "permissions": PERMISSION_PROFILE,
            "approvalPolicy": "on-request",
            "approvalsReviewer": "user",
            "developerInstructions": (
                "You are working inside RadSim with the Codex runtime. Follow the workspace's "
                "AGENTS.md and RadSim clarity principles. Keep functions small and explicit. "
                "Read and update uptodate.md for project work. Never read or disclose credentials. "
                "Preserve unrelated edits. Ask before writes, shell mutations or external actions. "
                "Do not spawn agents unless explicitly requested."
            ),
        }

    def _check_resume(self, thread_id: str) -> None:
        result = self.connection.request(
            "thread/read", {"threadId": thread_id, "includeTurns": False}
        )
        thread = result.get("thread", {})
        if thread.get("cwd") != str(self.workspace):
            raise CodexError(
                "Conversation belongs to another directory; open that directory to resume."
            )
        if thread.get("status", {}).get("type") == "active":
            raise CodexError(
                "Conversation has an active turn. Wait for it to stop before resuming."
            )

    def _verify_thread(self, result: dict) -> None:
        expected = {
            "modelProvider": "openai",
            "model": self.model,
            "cwd": str(self.workspace),
            "approvalPolicy": "on-request",
            "approvalsReviewer": "user",
        }
        if any(result.get(key) != value for key, value in expected.items()):
            raise CodexError("Codex did not apply the requested model or security settings.")
        if (result.get("activePermissionProfile") or {}).get("id") != PERMISSION_PROFILE:
            raise CodexError("Codex did not apply RadSim's permission profile.")
        if result.get("runtimeWorkspaceRoots") != [str(self.workspace)]:
            raise CodexError("Codex returned unexpected workspace access.")
        if not valid_identifier(result.get("thread", {}).get("id")):
            raise CodexError("Codex returned an invalid conversation identifier.")

    def _save_session(self) -> None:
        atomic_write_json(
            session_file(self.workspace),
            {
                "runtime": "codex",
                "authMode": "chatgpt",
                "cwd": str(self.workspace),
                "threadId": self.thread_id,
                "model": self.model,
            },
            secure=True,
        )

    def run_turn(self, prompt: str) -> str:
        if not prompt.strip() or len(prompt) > 128000:
            raise CodexError("Enter a task of 1 to 128000 characters.")
        require_subscription(self.connection)
        self.completed, self.turn_id, self.output_chars = None, None, 0
        self.streamed_items.clear()
        self.approvals.file_changes.clear()
        deadline = time.monotonic() + TURN_TIMEOUT
        try:
            result = self.connection.request(
                "turn/start",
                {
                    "threadId": self.thread_id,
                    "input": [{"type": "text", "text": prompt}],
                    "permissions": PERMISSION_PROFILE,
                    "approvalPolicy": "on-request",
                    "approvalsReviewer": "user",
                    "model": self.model,
                },
                on_event=self._handle_event,
            )
            self._set_turn(result.get("turn", {}))
            while self.completed is None:
                self._handle_event(self.connection.receive(deadline))
            return self._finish_turn()
        except BaseException:
            self.interrupt()
            raise

    def _set_turn(self, turn: dict) -> None:
        identifier = turn.get("id")
        if not valid_identifier(identifier) or self.turn_id not in (None, identifier):
            raise CodexError("Codex returned an unexpected turn identifier.")
        self.turn_id = identifier

    def _handle_event(self, message: dict) -> None:
        params = message.get("params", {})
        method = message.get("method")
        if params.get("threadId") != self.thread_id:
            if "id" in message:
                self.connection.reject(message)
            return
        if method == "turn/started":
            self._set_turn(params.get("turn", {}))
            return
        turn_id = params.get("turnId") or (params.get("turn") or {}).get("id")
        if self.turn_id is None or turn_id != self.turn_id:
            if "id" in message:
                self.connection.reject(message)
            return
        self._handle_scoped_event(message)

    def _handle_scoped_event(self, message: dict) -> None:
        method, params = message["method"], message["params"]
        if "id" in message:
            decision = self.approvals.decide(method, params)
            if decision is None:
                self.connection.reject(message)
            else:
                self.connection.send({"id": message["id"], "result": decision})
        elif method == "item/agentMessage/delta":
            self._write_delta(params.get("itemId"), params.get("delta"))
        elif method in ("item/started", "item/completed"):
            self._handle_item(method, params.get("item", {}))
        elif method == "turn/completed":
            self.completed = params["turn"]
        elif method == "thread/tokenUsage/updated":
            self.usage = params.get("tokenUsage", {}).get("total", {})

    def _write_delta(self, item_id, delta) -> None:
        if not valid_identifier(item_id) or not isinstance(delta, str):
            raise CodexError("Invalid Codex streaming event.")
        self.output_chars += len(delta)
        self.streamed_items.add(item_id)
        if self.output_chars > MAX_OUTPUT_CHARS or len(self.streamed_items) > MAX_TURN_ITEMS:
            raise CodexError("Codex output exceeded the session display limit.")
        self.stream(delta)

    def _handle_item(self, method: str, item: dict) -> None:
        if not isinstance(item, dict):
            raise CodexError("Invalid Codex item.")
        if method == "item/started":
            self.approvals.remember(item)
            if item.get("type") in ("commandExecution", "fileChange"):
                self.emit(f"Codex: {item['type']}")
        elif item.get("type") == "agentMessage" and item.get("id") not in self.streamed_items:
            self._write_delta(item.get("id"), item.get("text", ""))

    def _finish_turn(self) -> str:
        status = self.completed.get("status")
        if status == "failed":
            raise CodexError(describe_failure(self.completed.get("error")))
        if status not in ("completed", "interrupted"):
            raise CodexError("Codex returned an unknown completion status.")
        return status

    def interrupt(self) -> None:
        if self.turn_id and self.completed is None:
            try:
                self.connection.request(
                    "turn/interrupt",
                    {
                        "threadId": self.thread_id,
                        "turnId": self.turn_id,
                    },
                    timeout=3,
                )
            except CodexError:
                pass
        self.connection.close()
