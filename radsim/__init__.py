# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""RadSim Agent Framework - Radically Simple Code Generation."""

__version__ = "1.2.0"
__author__ = "Emera Digital Tools"

# Core exports
from .health import (
    HealthChecker,
    HealthStatus,
    SecretExpirationMonitor,
    check_health,
    check_secret_expirations,
    get_expiration_monitor,
    get_health_checker,
    validate_startup,
)
from .hooks import (
    HookContext,
    HooksManager,
    HookType,
    get_hooks_manager,
    on_error,
    post_api,
    post_tool,
    pre_api,
    pre_tool,
)
from .model_router import (
    ModelRouter,
    TaskComplexity,
    get_router,
    select_model_for_task,
)
from .skill_registry import (
    SkillRegistry,
    get_skill_registry,
    load_skill,
    load_skill_for_tool,
)
from .sub_agent import (
    SubAgentResult,
    SubAgentTask,
    delegate_task,
    execute_subagent_task,
    list_available_models,
    quick_task,
    resolve_model_name,
)
from .task_logger import (
    TaskLogger,
    get_logger,
    log_api,
    log_error,
    log_tool,
)
from .tool_result import ToolResult, wrap_tool_call
from .vector_memory import (
    VectorMemory,
    get_context,
    get_memory_backend,
    is_vector_memory_available,
    recall,
    remember,
)

__all__ = [
    # Version
    "__version__",
    "__author__",
    # Tool Results
    "ToolResult",
    "wrap_tool_call",
    # Skill Registry
    "SkillRegistry",
    "get_skill_registry",
    "load_skill",
    "load_skill_for_tool",
    # Hooks
    "HookType",
    "HookContext",
    "HooksManager",
    "get_hooks_manager",
    "pre_tool",
    "post_tool",
    "pre_api",
    "post_api",
    "on_error",
    # Logging
    "TaskLogger",
    "get_logger",
    "log_tool",
    "log_api",
    "log_error",
    # Model Routing
    "ModelRouter",
    "TaskComplexity",
    "get_router",
    "select_model_for_task",
    # Vector Memory
    "VectorMemory",
    "remember",
    "recall",
    "get_context",
    "is_vector_memory_available",
    "get_memory_backend",
    # Sub-Agent Delegation
    "SubAgentTask",
    "SubAgentResult",
    "delegate_task",
    "quick_task",
    "execute_subagent_task",
    "list_available_models",
    "resolve_model_name",
    # Health Checks
    "HealthChecker",
    "HealthStatus",
    "SecretExpirationMonitor",
    "check_health",
    "check_secret_expirations",
    "get_expiration_monitor",
    "get_health_checker",
    "validate_startup",
]
