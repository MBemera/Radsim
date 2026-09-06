"""Verify session ownership, permission boundaries and streamed turn lifecycle."""

from collections import deque

import pytest

from radsim.codex_approvals import CodexApprovals, workspace_path
from radsim.codex_connection import PERMISSION_PROFILE
from radsim.codex_runtime import CodexRuntime, load_session
from radsim.codex_transport import CodexError


class RuntimeConnection:
    def __init__(self, workspace):
        self.workspace = workspace
        self.requests, self.sent, self.rejected = [], [], []
        self.events = deque()
        self.closed = False
        self.mismatch = {}
        self.status = {"type": "idle"}
        self.fail_turn = False

    def request(self, method, params, **kwargs):
        self.requests.append((method, params))
        if method == "account/read":
            return {"account": {"type": "chatgpt"}}
        if method == "model/list":
            return {"data": [{"model": "test-model", "isDefault": True}, {"model": "second-model"}]}
        if method == "thread/read":
            return {"thread": {"cwd": str(self.workspace), "status": self.status}}
        if method in ("thread/start", "thread/resume"):
            return {
                "thread": {"id": "thread-1"},
                "model": params["model"],
                "modelProvider": "openai",
                "cwd": str(self.workspace),
                "runtimeWorkspaceRoots": [str(self.workspace)],
                "approvalPolicy": "on-request",
                "approvalsReviewer": "user",
                "activePermissionProfile": {"id": PERMISSION_PROFILE},
                **self.mismatch,
            }
        if method == "turn/start":
            if self.fail_turn:
                raise CodexError("Authentication expired")
            kwargs["on_event"](event("turn/started", turn={"id": "turn-1"}))
            return {"turn": {"id": "turn-1", "status": "inProgress"}}
        if method == "turn/interrupt":
            return {}
        raise AssertionError(method)

    def receive(self, _):
        message = self.events.popleft()
        if isinstance(message, BaseException):
            raise message
        return message

    def send(self, message):
        self.sent.append(message)

    def reject(self, message):
        self.rejected.append(message)

    def close(self):
        self.closed = True


def event(method, **params):
    return {"method": method, "params": {"threadId": "thread-1", "turnId": "turn-1", **params}}


@pytest.fixture
def runtime(tmp_path):
    connection = RuntimeConnection(tmp_path)
    output = []
    instance = CodexRuntime(
        connection, tmp_path, ask=lambda _: "no", emit=output.append, stream=output.append
    )
    instance.start()
    instance.test_output = output
    return instance


def test_thread_selection_persists_no_auth_material(runtime):
    saved = load_session(runtime.workspace)
    assert saved == {
        "runtime": "codex",
        "authMode": "chatgpt",
        "cwd": str(runtime.workspace),
        "threadId": "thread-1",
        "model": "test-model",
    }
    request = runtime.connection.requests[-1]
    assert request[0] == "thread/start"
    assert request[1]["allowProviderModelFallback"] is False
    assert request[1]["permissions"] == PERMISSION_PROFILE


@pytest.mark.parametrize(
    "mismatch",
    [
        {"approvalPolicy": "never"},
        {"approvalsReviewer": "auto_review"},
        {"modelProvider": "other"},
        {"model": "other-model"},
        {"activePermissionProfile": None},
        {"runtimeWorkspaceRoots": ["/"]},
    ],
)
def test_mismatched_server_security_settings_are_rejected(runtime, mismatch):
    runtime.connection.mismatch = mismatch
    with pytest.raises(CodexError):
        runtime.start()
    assert not any(method == "turn/start" for method, _ in runtime.connection.requests)


def test_model_not_in_account_catalog_is_rejected(runtime):
    before = len(runtime.connection.requests)
    with pytest.raises(CodexError, match="unavailable"):
        runtime.start("unknown-model")
    assert not any(method == "thread/start" for method, _ in runtime.connection.requests[before:])


def test_resume_preserves_history_without_replaying_a_turn(runtime):
    runtime.start(resume="last")
    methods = [method for method, _ in runtime.connection.requests]
    assert "thread/read" in methods
    assert "thread/resume" in methods
    assert "turn/start" not in methods


def test_resume_rejects_an_active_conversation(runtime):
    runtime.connection.status = {"type": "active"}
    with pytest.raises(CodexError, match="active turn"):
        runtime.start(resume="last")


def test_resume_rejects_other_workspace(runtime, tmp_path):
    runtime.connection.workspace = tmp_path / "other"
    with pytest.raises(CodexError, match="another directory"):
        runtime.start(resume="thread-1")


def test_streaming_does_not_duplicate_final_item(runtime):
    runtime.connection.events.extend(
        [
            event("item/agentMessage/delta", itemId="message-1", delta="Hello"),
            event(
                "item/completed", item={"id": "message-1", "type": "agentMessage", "text": "Hello"}
            ),
            event("thread/tokenUsage/updated", tokenUsage={"total": {"totalTokens": 12}}),
            event("turn/completed", turn={"id": "turn-1", "status": "completed"}),
        ]
    )
    assert runtime.run_turn("Synthetic task") == "completed"
    assert runtime.test_output == ["Hello"]
    assert runtime.usage == {"totalTokens": 12}


def test_final_item_is_shown_without_streamed_deltas(runtime):
    runtime.connection.events.extend(
        [
            event(
                "item/completed", item={"id": "message-1", "type": "agentMessage", "text": "Hello"}
            ),
            event("turn/completed", turn={"id": "turn-1", "status": "completed"}),
        ]
    )
    runtime.run_turn("Synthetic task")
    assert runtime.test_output == ["Hello"]


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), CodexError("timeout")])
def test_interruption_stops_turn_and_closes_process(runtime, failure):
    runtime.connection.events.append(failure)
    with pytest.raises(type(failure)):
        runtime.run_turn("Synthetic task")
    assert runtime.connection.requests[-1] == (
        "turn/interrupt",
        {"threadId": "thread-1", "turnId": "turn-1"},
    )
    assert runtime.connection.closed


def test_quota_failure_never_retries_or_falls_back(runtime):
    runtime.connection.events.append(
        event(
            "turn/completed",
            turn={
                "id": "turn-1",
                "status": "failed",
                "error": {"message": "usage limit private-marker"},
            },
        )
    )
    with pytest.raises(CodexError, match="fallback is disabled") as error:
        runtime.run_turn("Synthetic task")
    assert "private-marker" not in str(error.value)
    assert sum(method == "turn/start" for method, _ in runtime.connection.requests) == 1
    assert runtime.connection.closed


def test_approval_from_other_turn_is_rejected(runtime):
    request = event(
        "item/commandExecution/requestApproval", turnId="another-turn", command="touch test"
    )
    request["id"] = "approval-1"
    runtime.connection.events.extend(
        [request, event("turn/completed", turn={"id": "turn-1", "status": "completed"})]
    )
    runtime.run_turn("Synthetic task")
    assert runtime.connection.rejected == [request]


def test_unknown_tool_request_fails_closed(runtime):
    request = event("item/tool/call", tool="unknown", arguments={})
    request["id"] = "tool-1"
    runtime.connection.events.extend(
        [request, event("turn/completed", turn={"id": "turn-1", "status": "completed"})]
    )
    runtime.run_turn("Synthetic task")
    assert runtime.connection.rejected == [request]


def test_output_limit_interrupts_the_turn(runtime, monkeypatch):
    monkeypatch.setattr("radsim.codex_runtime.MAX_OUTPUT_CHARS", 3)
    runtime.connection.events.append(
        event("item/agentMessage/delta", itemId="message-1", delta="oversize")
    )
    with pytest.raises(CodexError, match="display limit"):
        runtime.run_turn("Synthetic task")
    assert runtime.connection.closed


@pytest.mark.parametrize("answer", ["", "y", "YES", "no"])
def test_command_approval_requires_explicit_yes(tmp_path, answer):
    policy = CodexApprovals(tmp_path, ask=lambda _: answer, emit=lambda _: None)
    assert policy.decide(
        "item/commandExecution/requestApproval",
        {
            "command": "touch demo.txt",
            "cwd": str(tmp_path),
        },
    ) == {"decision": "decline"}


def test_command_approval_shows_exact_action_and_grants_once(tmp_path):
    output = []
    policy = CodexApprovals(tmp_path, ask=lambda _: "yes", emit=output.append)
    decision = policy.decide(
        "item/commandExecution/requestApproval",
        {
            "command": "touch demo.txt",
            "cwd": str(tmp_path),
            "availableDecisions": ["accept", "decline"],
        },
    )
    assert decision == {"decision": "accept"}
    assert "touch demo.txt" in output[0]
    assert "outside the sandbox" in output[0]


@pytest.mark.parametrize(
    "path", ["../escape", ".env", "sub/.env.local", ".git/config", "key.pem", "auth.json"]
)
def test_protected_and_outside_paths_are_denied(tmp_path, path):
    assert workspace_path(path, tmp_path) is None


def test_symlink_escape_is_denied(tmp_path):
    (tmp_path / "escape").symlink_to(tmp_path.parent)
    assert workspace_path("escape/secret", tmp_path) is None


def test_file_approval_requires_a_complete_safe_patch(tmp_path):
    output = []
    policy = CodexApprovals(tmp_path, ask=lambda _: "yes", emit=output.append)
    params = {"itemId": "file-1"}
    assert policy.decide("item/fileChange/requestApproval", params) == {"decision": "decline"}
    policy.remember(
        {
            "id": "file-1",
            "type": "fileChange",
            "changes": [
                {"path": "demo.txt", "kind": {"type": "add"}, "diff": "+hello"},
            ],
        }
    )
    assert policy.decide("item/fileChange/requestApproval", params) == {"decision": "accept"}
    assert "+hello" in output[0]
    assert policy.decide("item/fileChange/requestApproval", params) == {"decision": "decline"}


@pytest.mark.parametrize("item_id", [None, {"unhashable": True}, ["file-1"], 7])
def test_file_approval_rejects_an_invalid_item_identifier(tmp_path, item_id):
    """A malformed identifier must decline, never raise out of the turn loop."""
    policy = CodexApprovals(
        tmp_path, ask=lambda _: pytest.fail("must not ask"), emit=lambda _: None
    )
    assert policy.decide("item/fileChange/requestApproval", {"itemId": item_id}) == {
        "decision": "decline"
    }


def test_session_wide_permission_grants_are_declined(tmp_path):
    policy = CodexApprovals(
        tmp_path, ask=lambda _: pytest.fail("must not ask"), emit=lambda _: None
    )
    assert policy.decide(
        "item/permissions/requestApproval", {"permissions": {"network": {"enabled": True}}}
    ) == {
        "permissions": {},
        "scope": "turn",
    }
