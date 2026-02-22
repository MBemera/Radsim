"""Tests for the ToolResult universal response format."""


from radsim.tool_result import ToolResult, wrap_tool_call


class TestToolResult:
    """Test ToolResult dataclass."""

    def test_ok_creates_success(self):
        result = ToolResult.ok(content="hello", path="/test.py")
        assert result.success is True
        assert result.data["content"] == "hello"
        assert result.data["path"] == "/test.py"
        assert result.error is None

    def test_ok_with_dict(self):
        result = ToolResult.ok(data={"key": "value"})
        assert result.success is True
        assert result.data["key"] == "value"

    def test_ok_empty(self):
        result = ToolResult.ok()
        assert result.success is True
        assert result.data == {}

    def test_fail_creates_failure(self):
        result = ToolResult.fail(error="File not found")
        assert result.success is False
        assert result.error == "File not found"
        assert result.data == {}

    def test_fail_with_data(self):
        result = ToolResult.fail(error="timeout", data={"attempt": 3})
        assert result.success is False
        assert result.error == "timeout"
        assert result.data["attempt"] == 3

    def test_to_dict_success(self):
        result = ToolResult.ok(content="test")
        d = result.to_dict()
        assert d["success"] is True
        assert "error" not in d
        assert d["data"]["content"] == "test"

    def test_to_dict_failure(self):
        result = ToolResult.fail(error="broken")
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "broken"

    def test_to_dict_with_metadata(self):
        result = ToolResult(
            success=True,
            data={"x": 1},
            tool_name="read_file",
            duration_ms=42.5,
        )
        d = result.to_dict()
        assert d["tool_name"] == "read_file"
        assert d["duration_ms"] == 42.5

    def test_to_dict_omits_zero_duration(self):
        result = ToolResult.ok(content="test")
        d = result.to_dict()
        assert "duration_ms" not in d

    def test_to_dict_omits_empty_tool_name(self):
        result = ToolResult.ok(content="test")
        d = result.to_dict()
        assert "tool_name" not in d

    def test_from_legacy_success(self):
        legacy = {"success": True, "stdout": "hello", "returncode": 0}
        result = ToolResult.from_legacy(legacy)
        assert result.success is True
        assert result.data["stdout"] == "hello"
        assert result.data["returncode"] == 0
        assert result.error is None

    def test_from_legacy_failure(self):
        legacy = {"success": False, "error": "command not found"}
        result = ToolResult.from_legacy(legacy)
        assert result.success is False
        assert result.error == "command not found"

    def test_from_legacy_missing_success(self):
        legacy = {"data": "something"}
        result = ToolResult.from_legacy(legacy)
        assert result.success is False


class TestWrapToolCall:
    """Test the wrap_tool_call decorator."""

    def test_wraps_dict_return(self):
        def my_tool():
            return {"success": True, "content": "hello"}

        wrapped = wrap_tool_call(my_tool, "my_tool")
        result = wrapped()
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.tool_name == "my_tool"
        assert result.duration_ms > 0

    def test_wraps_tool_result_return(self):
        def my_tool():
            return ToolResult.ok(content="hello")

        wrapped = wrap_tool_call(my_tool, "my_tool")
        result = wrapped()
        assert isinstance(result, ToolResult)
        assert result.success is True

    def test_wraps_exception(self):
        def broken_tool():
            raise ValueError("kaboom")

        wrapped = wrap_tool_call(broken_tool, "broken")
        result = wrapped()
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "kaboom" in result.error

    def test_wraps_arbitrary_return(self):
        def string_tool():
            return "just a string"

        wrapped = wrap_tool_call(string_tool, "string_tool")
        result = wrapped()
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data["result"] == "just a string"

    def test_preserves_function_name(self):
        def my_cool_function():
            return {"success": True}

        wrapped = wrap_tool_call(my_cool_function)
        assert wrapped.__name__ == "my_cool_function"
