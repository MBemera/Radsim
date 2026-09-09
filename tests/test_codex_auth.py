"""Subscription authentication never routes through API-key configuration."""

from collections import deque

import pytest

from radsim import codex_auth
from radsim.codex_transport import CodexError


class AuthConnection:
    def __init__(self, account=None):
        self.account = account
        self.requests = []
        self.events = deque()
        self.pages = deque()
        self.early = False
        self.cancelled = False

    def request(self, method, params, **kwargs):
        self.requests.append((method, params))
        if method == "account/read":
            return {"account": self.account}
        if method == "account/login/start":
            if self.early:
                kwargs["on_event"](self.events.popleft())
            return {
                "loginId": "login-1",
                "authUrl": "https://auth.openai.com/oauth/authorize",
                "verificationUrl": "https://auth.openai.com/codex/device",
                "userCode": "TEST-1234",
            }
        if method == "account/login/cancel":
            self.cancelled = True
            return {}
        if method == "model/list":
            return self.pages.popleft()
        if method == "account/rateLimits/read":
            return {"rateLimits": {"primary": {"usedPercent": 25, "resetsAt": 1800000000}}}
        raise AssertionError(method)

    def receive(self, _):
        if not self.events:
            raise CodexError("Login timed out")
        return self.events.popleft()

    def reject(self, _):
        pass


def completion(success=True):
    return {
        "method": "account/login/completed",
        "params": {"loginId": "login-1", "success": success},
    }


@pytest.mark.parametrize(
    "account", [None, {"type": "apiKey"}, {"type": "amazonBedrock"}, "invalid"]
)
def test_missing_or_wrong_auth_type_fails_closed(account):
    connection = AuthConnection(account)
    with pytest.raises(CodexError, match="sign-in is required"):
        codex_auth.require_subscription(connection)
    assert connection.requests == [("account/read", {"refreshToken": False})]


@pytest.mark.parametrize("early", [False, True])
def test_browser_login_waits_for_matching_completion(monkeypatch, early):
    connection = AuthConnection({"type": "chatgpt", "planType": "plus"})
    connection.early = early
    connection.events.append(completion())
    opened, output = [], []
    monkeypatch.setattr(codex_auth.webbrowser, "open", lambda url: opened.append(url) or True)
    codex_auth.login(connection, emit=output.append)
    assert opened == ["https://auth.openai.com/oauth/authorize"]
    assert output[-1] == "Signed in with ChatGPT (plus)."
    assert not connection.cancelled


@pytest.mark.parametrize("params", [{"success": True}, {"loginId": None, "success": True}])
def test_completion_without_a_login_id_still_completes(monkeypatch, params):
    """The server may omit loginId; only a different login must be ignored."""
    connection = AuthConnection({"type": "chatgpt", "planType": "plus"})
    connection.events.append({"method": "account/login/completed", "params": params})
    monkeypatch.setattr(codex_auth.webbrowser, "open", lambda _: True)
    output = []
    codex_auth.login(connection, emit=output.append)
    assert output[-1] == "Signed in with ChatGPT (plus)."
    assert not connection.cancelled


def test_completion_for_another_login_is_ignored(monkeypatch):
    connection = AuthConnection({"type": "chatgpt", "planType": "plus"})
    connection.events.append(
        {"method": "account/login/completed", "params": {"loginId": "other", "success": True}}
    )
    monkeypatch.setattr(codex_auth.webbrowser, "open", lambda _: True)
    with pytest.raises(CodexError):
        codex_auth.login(connection, emit=lambda _: None)
    assert connection.cancelled


def test_device_login_does_not_open_browser(monkeypatch):
    connection = AuthConnection({"type": "chatgpt", "planType": "plus"})
    connection.events.append(completion())
    monkeypatch.setattr(
        codex_auth.webbrowser, "open", lambda _: pytest.fail("browser must not open")
    )
    output = []
    codex_auth.login(connection, device_code=True, emit=output.append)
    assert "TEST-1234" in output[1]
    assert connection.requests[0][1] == {"type": "chatgptDeviceCode"}


@pytest.mark.parametrize("events", [[], [completion(False)]])
def test_login_failure_cancels_pending_flow(monkeypatch, events):
    connection = AuthConnection()
    connection.events.extend(events)
    monkeypatch.setattr(codex_auth.webbrowser, "open", lambda _: True)
    with pytest.raises(CodexError):
        codex_auth.login(connection, emit=lambda _: None)
    assert connection.cancelled


@pytest.mark.parametrize(
    "url",
    [
        "http://auth.openai.com/a",
        "https://auth.openai.com.evil.test/a",
        "https://auth.openai.com@evil.test/a",
        "https://auth.openai.com:443/a",
        "file:///tmp/a",
        "https://auth.openai.com/a\n",
        None,
        "https://[invalid/",
    ],
)
def test_login_url_rejects_untrusted_destinations(url):
    with pytest.raises(CodexError):
        codex_auth.trusted_login_url(url)


def test_model_discovery_handles_pagination_and_hidden_models():
    connection = AuthConnection({"type": "chatgpt"})
    connection.pages.extend(
        [
            {"data": [{"model": "test-model"}], "nextCursor": "next"},
            {"data": [{"model": "hidden-model", "hidden": True}], "nextCursor": None},
        ]
    )
    assert codex_auth.list_models(connection) == [{"model": "test-model"}]


@pytest.mark.parametrize("data", [[None], [{"model": "invalid\nmodel"}], "bad"])
def test_invalid_model_catalog_is_rejected(data):
    connection = AuthConnection({"type": "chatgpt"})
    connection.pages.append({"data": data})
    with pytest.raises(CodexError):
        codex_auth.list_models(connection)


def test_repeated_model_cursor_is_bounded():
    connection = AuthConnection({"type": "chatgpt"})
    connection.pages.extend([{"data": [], "nextCursor": "same"}] * 2)
    with pytest.raises(CodexError, match="pagination limit"):
        codex_auth.list_models(connection)


def test_status_does_not_expose_account_identity():
    connection = AuthConnection({"type": "chatgpt", "planType": "plus", "email": "private-marker"})
    output = []
    codex_auth.show_status(connection, output.append)
    assert "25%" in " ".join(output)
    assert "private-marker" not in " ".join(output)
