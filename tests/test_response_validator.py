"""Tests for response validation module."""


from radsim.response_validator import (
    check_for_corruption_patterns,
    sanitize_tool_input,
    validate_content_for_write,
    validate_response_structure,
    validate_tool_use_block,
)


class TestValidateResponseStructure:
    """Tests for validate_response_structure."""

    def test_valid_response_passes(self):
        """Valid response with text should pass."""
        response = {
            "content": [{"type": "text", "text": "Hello world"}],
            "stop_reason": "end_turn",
        }
        valid, error = validate_response_structure(response)
        assert valid
        assert error == ""

    def test_valid_tool_use_passes(self):
        """Valid response with tool use should pass."""
        response = {
            "content": [
                {"type": "tool_use", "id": "123", "name": "read_file", "input": {"path": "/test"}}
            ],
        }
        valid, error = validate_response_structure(response)
        assert valid

    def test_missing_content_fails(self):
        """Response without content key should fail."""
        response = {"stop_reason": "end_turn"}
        valid, error = validate_response_structure(response)
        assert not valid
        assert "content" in error.lower()

    def test_non_dict_response_fails(self):
        """Non-dict response should fail."""
        response = "not a dict"
        valid, error = validate_response_structure(response)
        assert not valid

    def test_non_list_content_fails(self):
        """Content that's not a list should fail."""
        response = {"content": "string content"}
        valid, error = validate_response_structure(response)
        assert not valid
        assert "not a list" in error

    def test_block_without_type_fails(self):
        """Content block without type should fail."""
        response = {"content": [{"text": "hello"}]}
        valid, error = validate_response_structure(response)
        assert not valid
        assert "type" in error.lower()


class TestValidateToolUseBlock:
    """Tests for validate_tool_use_block."""

    def test_valid_tool_use_passes(self):
        """Valid tool use block should pass."""
        block = {"id": "123", "name": "write_file", "input": {"path": "/test"}}
        valid, error = validate_tool_use_block(block)
        assert valid

    def test_missing_id_fails(self):
        """Missing id should fail."""
        block = {"name": "write_file", "input": {}}
        valid, error = validate_tool_use_block(block)
        assert not valid
        assert "id" in error

    def test_missing_name_fails(self):
        """Missing name should fail."""
        block = {"id": "123", "input": {}}
        valid, error = validate_tool_use_block(block)
        assert not valid
        assert "name" in error

    def test_non_dict_input_fails(self):
        """Non-dict input should fail."""
        block = {"id": "123", "name": "test", "input": "string input"}
        valid, error = validate_tool_use_block(block)
        assert not valid
        assert "not dict" in error

    def test_parse_error_marker_fails(self):
        """Input with parse error marker should fail."""
        block = {"id": "123", "name": "test", "input": {"__parse_error__": "JSON error"}}
        valid, error = validate_tool_use_block(block)
        assert not valid
        assert "parse error" in error.lower()


class TestValidateContentForWrite:
    """Tests for validate_content_for_write."""

    def test_valid_python_passes(self):
        """Valid Python code should pass."""
        content = '''#!/usr/bin/env python3
"""Test module."""

def hello():
    print("world")
'''
        valid, error = validate_content_for_write(content, ".py")
        assert valid

    def test_json_array_for_python_fails(self):
        """JSON array content for .py file should fail."""
        content = '[[1, 2], [3, 4]]'
        valid, error = validate_content_for_write(content, ".py")
        assert not valid
        assert "json array" in error.lower()

    def test_json_object_array_for_python_fails(self):
        """JSON object array for .py file should fail."""
        content = '[{"key": "value"}, {"key2": "value2"}]'
        valid, error = validate_content_for_write(content, ".py")
        assert not valid
        assert "json" in error.lower()

    def test_short_content_for_code_file_fails(self):
        """Very short content for code file should fail."""
        content = "x=1"
        valid, error = validate_content_for_write(content, ".py")
        assert not valid
        assert "short" in error.lower()

    def test_json_file_accepts_json(self):
        """JSON file should accept JSON content."""
        content = '{"key": "value"}'
        valid, error = validate_content_for_write(content, ".json")
        assert valid

    def test_python_without_structure_fails(self):
        """Python file without recognizable structure should fail."""
        content = "this is just plain text without any python structure"
        valid, error = validate_content_for_write(content, ".py")
        assert not valid
        assert "structure" in error.lower()


class TestSanitizeToolInput:
    """Tests for sanitize_tool_input."""

    def test_removes_error_markers(self):
        """Should remove __prefixed keys."""
        tool_input = {"path": "/test", "__parse_error__": "error", "__raw__": "data"}
        cleaned = sanitize_tool_input(tool_input)
        assert cleaned == {"path": "/test"}

    def test_handles_non_dict(self):
        """Should return empty dict for non-dict input."""
        cleaned = sanitize_tool_input("not a dict")
        assert cleaned == {}


class TestCheckForCorruptionPatterns:
    """Tests for check_for_corruption_patterns."""

    def test_detects_nested_json_arrays(self):
        """Should detect multiple nested JSON arrays."""
        text = "[[a, b], [[c, d]], [[e]], [[f]]]"
        issues = check_for_corruption_patterns(text)
        assert len(issues) > 0
        assert any("json" in issue.lower() for issue in issues)

    def test_clean_text_no_issues(self):
        """Clean text should have no issues."""
        text = "def hello():\n    print('world')\n"
        issues = check_for_corruption_patterns(text)
        assert len(issues) == 0
