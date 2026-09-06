"""Translate scoped Codex requests into explicit, single-action user decisions."""

import json
from collections.abc import Callable
from pathlib import Path

from .terminal import escape_terminal_controls

MAX_PREVIEW_CHARS = 32000


def workspace_path(value: str, workspace: Path) -> Path | None:
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    path = (workspace / value).resolve()
    if not path.is_relative_to(workspace):
        return None
    for part in path.relative_to(workspace).parts:
        if part in {".git", ".codex", ".radsim", ".ssh"} or part.startswith(
            (".env", "credentials")
        ):
            return None
        if part.endswith((".pem", ".key")) or part == "auth.json":
            return None
    return path


class CodexApprovals:
    def __init__(self, workspace: Path, *, ask: Callable[[str], str], emit: Callable[[str], None]):
        self.workspace = workspace
        self.ask = ask
        self.emit = emit
        self.file_changes: dict[str, list] = {}

    def remember(self, item: dict) -> None:
        if item.get("type") != "fileChange":
            return
        if len(self.file_changes) >= 128:
            self.file_changes.clear()
        if isinstance(item.get("id"), str) and isinstance(item.get("changes"), list):
            self.file_changes[item["id"]] = item["changes"]

    def decide(self, method: str, params: dict) -> dict | None:
        if method == "item/permissions/requestApproval":
            self.emit(
                "Declined a request for broader permissions; approve individual actions instead."
            )
            return {"permissions": {}, "scope": "turn"}
        if method == "item/commandExecution/requestApproval":
            return {"decision": self._command_decision(params)}
        if method == "item/fileChange/requestApproval":
            return {"decision": self._file_decision(params)}
        if method == "item/tool/requestUserInput":
            return self._answer_questions(params)
        return None

    def _confirm(self, preview: str) -> str:
        if not preview or len(preview) > MAX_PREVIEW_CHARS:
            self.emit("Declined: action preview is missing or exceeds the review limit.")
            return "decline"
        self.emit(escape_terminal_controls(preview, preserve_layout=True))
        try:
            return (
                "accept"
                if self.ask("Approve this action once? Type yes: ").strip() == "yes"
                else "decline"
            )
        except (EOFError, KeyboardInterrupt):
            return "decline"

    def _command_decision(self, params: dict) -> str:
        command = params.get("command")
        cwd = workspace_path(params.get("cwd"), self.workspace)
        if not isinstance(command, str) or not command or cwd is None:
            return "decline"
        decisions = params.get("availableDecisions")
        if decisions is not None and (not isinstance(decisions, list) or "accept" not in decisions):
            return "decline"
        details = {
            key: params[key]
            for key in ("reason", "networkApprovalContext", "additionalPermissions")
            if params.get(key) is not None
        }
        preview = f"Command approval (may run outside the sandbox)\nDirectory: {cwd}\n{command}"
        if details:
            preview += "\nRequested access: " + json.dumps(details, ensure_ascii=True)
        return self._confirm(preview)

    def _file_decision(self, params: dict) -> str:
        item_id = params.get("itemId")
        if not isinstance(item_id, str):
            return "decline"
        changes = self.file_changes.pop(item_id, None)
        if not changes or params.get("grantRoot"):
            return "decline"
        previews = []
        for change in changes:
            if (
                not isinstance(change, dict)
                or workspace_path(change.get("path"), self.workspace) is None
            ):
                return "decline"
            moved = change.get("kind", {})
            if isinstance(moved, dict) and moved.get("move_path"):
                if workspace_path(moved["move_path"], self.workspace) is None:
                    return "decline"
            if not isinstance(change.get("diff"), str) or not change["diff"]:
                return "decline"
            previews.append(json.dumps(change, ensure_ascii=True))
        return self._confirm("Proposed file changes:\n" + "\n".join(previews))

    def _answer_questions(self, params: dict) -> dict:
        questions = params.get("questions")
        if not isinstance(questions, list) or len(questions) > 3:
            return {"answers": {}}
        answers = {}
        for question in questions:
            if not isinstance(question, dict) or not isinstance(question.get("id"), str):
                return {"answers": {}}
            if question.get("isSecret"):
                self.emit("Secret input is not supported through model questions.")
                return {"answers": {}}
            self.emit(escape_terminal_controls(json.dumps(question), preserve_layout=True))
            try:
                answer = self.ask("Your answer: ")
            except (EOFError, KeyboardInterrupt):
                answer = ""
            answers[question["id"]] = {"answers": [answer[:4000]] if answer else []}
        return {"answers": answers}
