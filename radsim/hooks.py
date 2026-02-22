"""Event Hooks System - Predictable extension points.

RadSim Principle: Predictable Extension Points
If code needs extensibility, use explicit lifecycle hooks.

Hooks allow code execution before or after specific agent actions:
- pre_tool: Before a tool executes
- post_tool: After a tool completes
- pre_api: Before an API call
- post_api: After an API response
- on_error: When an error occurs
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class HookType(Enum):
    """Types of hooks available in the system."""

    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    PRE_API = "pre_api"
    POST_API = "post_api"
    ON_ERROR = "on_error"
    PRE_MESSAGE = "pre_message"
    POST_MESSAGE = "post_message"


@dataclass
class HookContext:
    """Context passed to hook functions.

    Contains all relevant information about the current operation.
    """

    hook_type: HookType
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_result: dict = field(default_factory=dict)
    message: str = ""
    error: Exception | None = None
    metadata: dict = field(default_factory=dict)

    # Control flags - hooks can modify these
    should_proceed: bool = True  # Set to False to cancel operation
    modified_input: dict | None = None  # Replace tool input
    modified_message: str | None = None  # Replace message


# Type alias for hook functions
HookFunction = Callable[[HookContext], HookContext | None]


class HooksManager:
    """Manages lifecycle hooks for the agent.

    Hooks are executed in registration order.
    Each hook receives a HookContext and can:
    - Modify the context (e.g., change tool input)
    - Cancel the operation (set should_proceed=False)
    - Log/audit the operation
    - Trigger side effects (notifications, etc.)
    """

    def __init__(self):
        self._hooks: dict[HookType, list[HookFunction]] = {hook_type: [] for hook_type in HookType}

    def register(self, hook_type: HookType, hook_func: HookFunction):
        """Register a hook function.

        Args:
            hook_type: When to execute the hook
            hook_func: Function that receives HookContext
        """
        self._hooks[hook_type].append(hook_func)

    def unregister(self, hook_type: HookType, hook_func: HookFunction):
        """Unregister a hook function."""
        if hook_func in self._hooks[hook_type]:
            self._hooks[hook_type].remove(hook_func)

    def execute(self, hook_type: HookType, context: HookContext) -> HookContext:
        """Execute all hooks of a given type.

        Hooks are executed in order. Each hook receives the context
        (potentially modified by previous hooks).

        Returns the final context after all hooks have run.
        """
        for hook_func in self._hooks[hook_type]:
            try:
                result = hook_func(context)
                if result is not None:
                    context = result

                # Check if operation should be cancelled
                if not context.should_proceed:
                    break

            except Exception as e:
                # Hook errors should not crash the system
                context.metadata["hook_error"] = str(e)

        return context

    def clear(self, hook_type: HookType = None):
        """Clear hooks. If hook_type is None, clears all."""
        if hook_type is None:
            for ht in HookType:
                self._hooks[ht] = []
        else:
            self._hooks[hook_type] = []


# Global hooks manager with thread-safe initialization
_hooks_manager: HooksManager | None = None
_hooks_manager_lock = threading.Lock()


def get_hooks_manager() -> HooksManager:
    """Get the global hooks manager instance (thread-safe singleton)."""
    global _hooks_manager
    if _hooks_manager is None:
        with _hooks_manager_lock:
            # Double-check locking pattern
            if _hooks_manager is None:
                _hooks_manager = HooksManager()
    return _hooks_manager


# Convenience decorators for registering hooks


def pre_tool(func: HookFunction) -> HookFunction:
    """Decorator to register a pre-tool hook."""
    get_hooks_manager().register(HookType.PRE_TOOL, func)
    return func


def post_tool(func: HookFunction) -> HookFunction:
    """Decorator to register a post-tool hook."""
    get_hooks_manager().register(HookType.POST_TOOL, func)
    return func


def pre_api(func: HookFunction) -> HookFunction:
    """Decorator to register a pre-API hook."""
    get_hooks_manager().register(HookType.PRE_API, func)
    return func


def post_api(func: HookFunction) -> HookFunction:
    """Decorator to register a post-API hook."""
    get_hooks_manager().register(HookType.POST_API, func)
    return func


def on_error(func: HookFunction) -> HookFunction:
    """Decorator to register an error hook."""
    get_hooks_manager().register(HookType.ON_ERROR, func)
    return func


# Built-in hooks for common use cases


def create_validation_hook(validator: Callable[[dict], tuple[bool, str]]) -> HookFunction:
    """Create a pre-tool hook that validates input.

    Args:
        validator: Function that takes tool_input and returns (is_valid, error_message)
    """

    def validation_hook(context: HookContext) -> HookContext:
        is_valid, error_msg = validator(context.tool_input)
        if not is_valid:
            context.should_proceed = False
            context.metadata["validation_error"] = error_msg
        return context

    return validation_hook


def create_budget_hook(max_cost: float, cost_tracker: dict) -> HookFunction:
    """Create a pre-API hook that enforces a budget limit.

    Args:
        max_cost: Maximum allowed cost in USD
        cost_tracker: Dict with 'current_cost' key (mutable for tracking)
    """

    def budget_hook(context: HookContext) -> HookContext:
        if cost_tracker.get("current_cost", 0) >= max_cost:
            context.should_proceed = False
            context.metadata["budget_exceeded"] = True
            context.metadata["current_cost"] = cost_tracker["current_cost"]
            context.metadata["max_cost"] = max_cost
        return context

    return budget_hook


def create_notification_hook(notify_func: Callable[[str], None]) -> HookFunction:
    """Create a post-tool hook that sends notifications.

    Args:
        notify_func: Function to call with notification message
    """

    def notification_hook(context: HookContext) -> HookContext:
        tool_name = context.tool_name
        success = context.tool_result.get("success", False)

        if success:
            notify_func(f"✓ {tool_name} completed successfully")
        else:
            error = context.tool_result.get("error", "Unknown error")
            notify_func(f"✗ {tool_name} failed: {error}")

        return context

    return notification_hook
