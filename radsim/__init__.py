# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""RadSim Agent Framework - Radically Simple Code Generation."""

from importlib import import_module

__version__ = "1.2.2"
__author__ = "Emera Digital Tools"

_MODULE_EXPORTS = {
    ".health": [
        "HealthChecker",
        "HealthStatus",
        "SecretExpirationMonitor",
        "check_health",
        "check_secret_expirations",
        "get_expiration_monitor",
        "get_health_checker",
        "validate_startup",
    ],
    ".hooks": [
        "HookContext",
        "HooksManager",
        "HookType",
        "get_hooks_manager",
        "on_error",
        "post_api",
        "post_tool",
        "pre_api",
        "pre_tool",
    ],
    ".model_router": [
        "ModelRouter",
        "TaskComplexity",
        "get_router",
        "select_model_for_task",
    ],
    ".skill_registry": [
        "SkillRegistry",
        "get_skill_registry",
        "load_skill",
        "load_skill_for_tool",
    ],
    ".sub_agent": [
        "SubAgentResult",
        "SubAgentTask",
        "delegate_task",
        "execute_subagent_task",
        "list_available_models",
        "quick_task",
        "resolve_model_name",
    ],
    ".task_logger": [
        "TaskLogger",
        "get_logger",
        "log_api",
        "log_error",
        "log_tool",
    ],
    ".tool_result": [
        "ToolResult",
        "wrap_tool_call",
    ],
    ".vector_memory": [
        "VectorMemory",
        "get_context",
        "get_memory_backend",
        "is_vector_memory_available",
        "recall",
        "remember",
    ],
}

_LAZY_EXPORTS = {
    export_name: module_path
    for module_path, export_names in _MODULE_EXPORTS.items()
    for export_name in export_names
}

__all__ = [
    "__version__",
    "__author__",
    *_LAZY_EXPORTS.keys(),
]


def __getattr__(name):
    """Load public exports only when callers access them."""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_path, package=__name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    """Return lazily available exports for interactive discovery."""
    return sorted(__all__)
