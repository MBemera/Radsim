"""Sub-agent runtime helpers that extend the main agent."""

from .tools import execute_tool


class TaskCompleted(Exception):
    """Exception raised when a sub-agent completes its task."""

    def __init__(self, result):
        self.result = result


class SubAgentMixin:
    """Mixin that changes submit_completion into a sub-agent exit condition."""

    def _execute_with_permission(self, tool_name, tool_input):
        """Execute tool, intercepting completion."""
        if tool_name == "submit_completion":
            result = execute_tool("submit_completion", tool_input)
            raise TaskCompleted(result)

        return super()._execute_with_permission(tool_name, tool_input)
