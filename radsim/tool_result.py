"""Standardized Tool Result - Universal response format for all tools.

RadSim Principle: Standardized Interfaces Over Custom Protocols
All tools return the same predictable shape - no surprises for humans or agents.
"""

from dataclasses import dataclass, field


@dataclass
class ToolResult:
    """Universal result format for all tool executions.

    Every tool in RadSim returns this exact structure.
    This makes it predictable for:
    - Human developers reading output
    - AI agents parsing responses
    - Logging systems recording events
    - Error handling catching failures
    """

    success: bool
    data: dict = field(default_factory=dict)
    error: str | None = None

    # Optional metadata for observability
    tool_name: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "success": self.success,
            "data": self.data,
        }
        if self.error:
            result["error"] = self.error
        if self.tool_name:
            result["tool_name"] = self.tool_name
        if self.duration_ms > 0:
            result["duration_ms"] = self.duration_ms
        return result

    @classmethod
    def ok(cls, data: dict = None, **kwargs) -> "ToolResult":
        """Create a successful result."""
        return cls(success=True, data=data or kwargs)

    @classmethod
    def fail(cls, error: str, data: dict = None) -> "ToolResult":
        """Create a failed result."""
        return cls(success=False, error=error, data=data or {})

    @classmethod
    def from_legacy(cls, legacy_dict: dict) -> "ToolResult":
        """Convert legacy tool response to ToolResult.

        Bridges old-style dicts to new standardized format.
        """
        success = legacy_dict.get("success", False)
        error = legacy_dict.get("error")

        # Extract data (everything except success/error)
        data = {k: v for k, v in legacy_dict.items() if k not in ("success", "error")}

        return cls(success=success, data=data, error=error)


def wrap_tool_call(tool_func, tool_name: str = ""):
    """Decorator to wrap tool functions with standardized result handling.

    Usage:
        @wrap_tool_call
        def my_tool(arg1, arg2):
            return {"content": "result"}
    """
    import time
    from functools import wraps

    @wraps(tool_func)
    def wrapper(*args, **kwargs):
        start_time = time.time()

        try:
            result = tool_func(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000

            # If already a ToolResult, just add timing
            if isinstance(result, ToolResult):
                result.duration_ms = duration_ms
                result.tool_name = tool_name or tool_func.__name__
                return result

            # Convert legacy dict to ToolResult
            if isinstance(result, dict):
                tool_result = ToolResult.from_legacy(result)
                tool_result.duration_ms = duration_ms
                tool_result.tool_name = tool_name or tool_func.__name__
                return tool_result

            # Unknown return type - wrap as data
            return ToolResult.ok(
                data={"result": result},
                tool_name=tool_name or tool_func.__name__,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ToolResult.fail(
                error=str(e),
                data={"tool_name": tool_name or tool_func.__name__, "duration_ms": duration_ms},
            )

    return wrapper
