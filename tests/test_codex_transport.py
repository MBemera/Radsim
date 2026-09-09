"""Exercise framing, lifecycle and bounded failure behavior over real pipes."""

import os
import sys
import time

import pytest

from radsim.codex_transport import MAX_FRAME_BYTES, CodexError, CodexTransport

SERVER = """
import json, sys, time
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if "id" not in request:
        continue
    result = {"id": request["id"], "result": {}}
    if method == "echo":
        print(json.dumps({"method": "event", "params": {"value": 1}}), flush=True)
        result["result"] = request["params"]
    elif method == "error":
        result = {"id": request["id"], "error": {"message": "quota private-marker"}}
    elif method == "bad":
        print("not json", flush=True)
        continue
    elif method == "oversize":
        print("x" * (1024 * 1024 + 1), flush=True)
        continue
    elif method == "exit":
        sys.exit(2)
    elif method == "stall":
        time.sleep(10)
    elif method == "request":
        print(json.dumps({"id": "server-1", "method": "unsupported", "params": {}}), flush=True)
        reply = json.loads(sys.stdin.readline())
        result["result"] = {"denied": reply.get("error", {}).get("code") == -32601}
    print(json.dumps(result), flush=True)
"""


@pytest.fixture
def connection(tmp_path):
    server = tmp_path / "server.py"
    server.write_text(SERVER)
    transport = CodexTransport(
        [sys.executable, "-u", str(server)], cwd=str(tmp_path), env=dict(os.environ)
    )
    with transport:
        yield transport
    assert transport.process is None
    assert not transport.reader.is_alive()


def test_handshake_request_and_interleaved_event(connection):
    events = []
    result = connection.request("echo", {"hello": "world"}, on_event=events.append)
    assert result == {"hello": "world"}
    assert events == [{"method": "event", "params": {"value": 1}}]


def test_unknown_server_request_is_rejected(connection):
    assert connection.request("request", {}) == {"denied": True}


def test_error_does_not_echo_raw_provider_details(connection):
    with pytest.raises(CodexError, match="usage limit") as error:
        connection.request("error", {})
    assert "private-marker" not in str(error.value)
    assert "fallback is disabled" in str(error.value)


@pytest.mark.parametrize("method", ["bad", "oversize", "exit"])
def test_invalid_output_or_child_exit_fails_closed(connection, method):
    with pytest.raises(CodexError):
        connection.request(method, {}, timeout=2)


def test_timeout_is_bounded_and_does_not_retry(connection):
    before = connection.request_id
    start = time.monotonic()
    with pytest.raises(CodexError, match="timed out"):
        connection.request("stall", {}, timeout=0.05)
    assert time.monotonic() - start < 1
    assert connection.request_id == before + 1


@pytest.mark.parametrize("frame", [b"[]\n", b'{"method":2}\n', b'{"params":[]}\n', b"{}"])
def test_malformed_frames_are_rejected(frame):
    with pytest.raises(CodexError):
        CodexTransport._decode_frame(frame)


def test_outgoing_frame_limit(connection):
    with pytest.raises(CodexError, match="too large"):
        connection.send({"text": "x" * MAX_FRAME_BYTES})


def test_close_is_idempotent(connection):
    process = connection.process
    connection.close()
    connection.close()
    assert process.poll() is not None


def test_missing_binary_does_not_leave_a_process(tmp_path):
    transport = CodexTransport([str(tmp_path / "missing")], cwd=str(tmp_path), env={})
    with pytest.raises(OSError), transport:
        pass
    assert transport.process is None
