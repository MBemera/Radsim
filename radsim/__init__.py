# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""RadSim Agent Framework - Radically Simple Code Generation."""

from importlib import import_module

from .version import __version__, get_radsim_version

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
        "SubAgentModelError",
        "SubAgentResult",
        "SubAgentTask",
        "delegate_task",
        "execute_subagent_task",
        "get_available_models",
        "resolve_subagent_model",
    ],
    ".sub_agent_policy": [
        "SubAgentPolicyBroker",
    ],
    ".sub_agent_profiles": [
        "CAPABILITY_PROFILES",
        "ProfileError",
        "compose_subagent_prompt",
        "get_tools_for_profile",
        "resolve_profile_name",
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
    "get_radsim_version",
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
