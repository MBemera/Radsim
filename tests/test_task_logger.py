"""Tests for the Task Logger audit trail."""


from radsim.task_logger import LogEntry, _sanitize_for_logging


class TestSanitizeLogging:
    """Test that sensitive data is redacted."""

    def test_redacts_api_key(self):
        data = 'api_key="sk-ant-abc123"'
        result = _sanitize_for_logging(data)
        assert "sk-ant-abc123" not in result
        assert "[REDACTED]" in result

    def test_redacts_password(self):
        data = 'password: "hunter2"'
        result = _sanitize_for_logging(data)
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_redacts_token(self):
        data = 'token="eyJhbGciOiJIUzI1NiJ9"'
        result = _sanitize_for_logging(data)
        assert "eyJhbGciOiJIUzI1NiJ9" not in result

    def test_redacts_secret(self):
        data = 'secret: my-secret-value'
        result = _sanitize_for_logging(data)
        assert "my-secret-value" not in result

    def test_redacts_access_code(self):
        data = 'access_code="abc123"'
        result = _sanitize_for_logging(data)
        assert "abc123" not in result

    def test_preserves_safe_data(self):
        data = 'file_path="/src/main.py"'
        result = _sanitize_for_logging(data)
        assert result == data

    def test_empty_string(self):
        assert _sanitize_for_logging("") == ""

    def test_none_passthrough(self):
        assert _sanitize_for_logging(None) is None

    def test_case_insensitive(self):
        data = 'API_KEY="sk-123"'
        result = _sanitize_for_logging(data)
        assert "sk-123" not in result


class TestLogEntry:
    """Test LogEntry dataclass."""

    def test_create_log_entry(self):
        entry = LogEntry(
            timestamp="2026-02-15T10:00:00",
            event_type="tool_execution",
            session_id="sess-123",
            tool_name="read_file",
        )
        assert entry.tool_name == "read_file"
        assert entry.event_type == "tool_execution"

    def test_default_values(self):
        entry = LogEntry(
            timestamp="2026-02-15T10:00:00",
            event_type="api_call",
            session_id="sess-123",
        )
        assert entry.tool_name == ""
        assert entry.input_tokens == 0
        assert entry.output_tokens == 0
        assert entry.api_duration_ms == 0.0
