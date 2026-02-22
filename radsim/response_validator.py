"""Response validation for RadSim API responses.

Validates API response structure and content before processing.
Prevents corrupted tool calls and garbage file writes.
"""

import logging
import re

logger = logging.getLogger(__name__)


def validate_response_structure(response: dict) -> tuple[bool, str]:
    """Check response has required keys and valid content blocks.

    Args:
        response: API response dict

    Returns:
        (is_valid, error_message) tuple
    """
    if not isinstance(response, dict):
        return False, f"Response is not a dict: {type(response)}"

    if "content" not in response:
        return False, "Response missing 'content' key"

    content = response["content"]
    if not isinstance(content, list):
        return False, f"Response content is not a list: {type(content)}"

    for i, block in enumerate(content):
        if not isinstance(block, dict):
            return False, f"Content block {i} is not a dict: {type(block)}"

        if "type" not in block:
            return False, f"Content block {i} missing 'type' key"

        block_type = block["type"]

        if block_type == "text":
            if "text" not in block:
                return False, f"Text block {i} missing 'text' key"
            if not isinstance(block["text"], str):
                return False, f"Text block {i} 'text' is not string: {type(block['text'])}"

        elif block_type == "tool_use":
            valid, error = validate_tool_use_block(block)
            if not valid:
                return False, f"Tool block {i}: {error}"

    return True, ""


def validate_tool_use_block(block: dict) -> tuple[bool, str]:
    """Validate tool_use block has required fields and valid input.

    Args:
        block: Tool use block dict

    Returns:
        (is_valid, error_message) tuple
    """
    required = ["id", "name", "input"]
    for key in required:
        if key not in block:
            return False, f"Missing required key: {key}"

    if not isinstance(block["name"], str):
        return False, f"Tool name is not string: {type(block['name'])}"

    if not block["name"]:
        return False, "Tool name is empty"

    tool_input = block["input"]

    # Check for parse error marker
    if isinstance(tool_input, dict) and "__parse_error__" in tool_input:
        return False, f"Tool input had parse error: {tool_input.get('__parse_error__')}"

    # Input must be a dict
    if not isinstance(tool_input, dict):
        return False, f"Tool input is not dict: {type(tool_input)}"

    return True, ""


def validate_content_for_write(content: str, file_ext: str) -> tuple[bool, str]:
    """Validate file content before writing.

    Checks for common corruption patterns like JSON arrays
    being written as code files.

    Args:
        content: File content to validate
        file_ext: File extension (e.g., ".py", ".js")

    Returns:
        (is_valid, error_message) tuple
    """
    if not isinstance(content, str):
        return False, f"Content is not a string: {type(content)}"

    # Empty content is suspicious for code files
    code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".c", ".cpp", ".h"}
    if file_ext in code_exts and len(content.strip()) < 10:
        return False, "Content too short for code file"

    # Check for JSON array pattern (common corruption)
    stripped = content.strip()
    if stripped.startswith("[[") and stripped.endswith("]]"):
        return False, "Content looks like JSON array, not source code"

    if stripped.startswith("[{") and stripped.endswith("}]"):
        # Could be valid JSON file, but suspicious for code
        if file_ext in code_exts:
            return False, "Content looks like JSON, not source code"

    # For Python files, check for basic structure
    if file_ext == ".py":
        # Should have at least one of: import, def, class, or variable assignment
        has_structure = any([
            "import " in content,
            "from " in content,
            "def " in content,
            "class " in content,
            re.search(r"^\w+\s*=", content, re.MULTILINE),  # variable assignment
            content.strip().startswith("#"),  # comment/shebang
            content.strip().startswith('"""'),  # docstring
            content.strip().startswith("'''"),  # docstring
        ])
        if not has_structure:
            return False, "Python file lacks recognizable code structure"

    return True, ""


def sanitize_tool_input(tool_input: dict) -> dict:
    """Clean up tool input, handling any parse error markers.

    Args:
        tool_input: Tool input dict, possibly with error markers

    Returns:
        Cleaned input dict (may be empty if corrupted)
    """
    if not isinstance(tool_input, dict):
        logger.warning(f"Tool input is not dict: {type(tool_input)}")
        return {}

    # Remove error markers
    cleaned = {k: v for k, v in tool_input.items() if not k.startswith("__")}

    return cleaned


def check_for_corruption_patterns(text: str) -> list[str]:
    """Identify potential corruption patterns in text.

    Args:
        text: Text to analyze

    Returns:
        List of detected issues (empty if clean)
    """
    issues = []

    # JSON-like structure markers
    if text.count("[[") > 2 and text.count("]]") > 2:
        issues.append("Multiple nested JSON arrays detected")

    # Escaped newlines in code
    if "\\n" in text and text.count("\\n") > text.count("\n"):
        issues.append("Excessive escaped newlines (should be actual newlines)")

    # Quoted dict keys without proper JSON structure
    if re.search(r'"\w+":\s*"\w+"', text) and not text.strip().startswith("{"):
        issues.append("JSON-like key:value pairs outside JSON structure")

    return issues
