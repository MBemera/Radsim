# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Main agent loop for RadSim."""

import logging
import threading

from .agent_api import AgentApiMixin
from .agent_constants import (  # noqa: F401 - re-exported for compatibility
    CONFIRMATION_TOOLS,
    LIGHT_CONFIRM_TOOLS,
    READ_ONLY_TOOLS,
)
from .agent_conversation import AgentConversationMixin
from .agent_policy import AgentPolicyMixin
from .agent_subagents import AgentSubAgentMixin
from .agent_tool_handlers import AgentToolHandlersMixin
from .api_client import create_client
from .performance import PerformanceTelemetry
from .prompts import get_system_prompt
from .rate_limiter import (
    ProtectionManager,
)
from .usage import empty_usage_totals

logger = logging.getLogger(__name__)


class RadSimAgent(
    AgentConversationMixin,
    AgentApiMixin,
    AgentPolicyMixin,
    AgentSubAgentMixin,
    AgentToolHandlersMixin,
):
    """The RadSim coding agent.

    Conversation lifecycle, API orchestration, tool policy, sub-agent
    delegation, and the per-tool confirmation handlers live in the mixins
    above. This class holds construction.
    """

    def __init__(self, config, context_file=None):
        self.config = config
        self.client = create_client(
            config.provider,
            config.api_key,
            config.model,
            reasoning_effort=getattr(config, "reasoning_effort", None),
        )
        self.messages = []
        self.system_prompt = get_system_prompt()
        self.usage_stats = empty_usage_totals()
        self.performance_telemetry = PerformanceTelemetry.from_environment()
        self._performance_request_index = 0

        # Tool-schema routing: None means every registered schema is sent.
        self._routed_tool_names = None

        # Learning system attributes
        self._last_response = ""  # For feedback commands (/good, /improve)
        self._current_task_start = None  # For task timing
        self._current_task_tools = []  # Tools used in current task
        self._task_outcome_tracker = None  # Evidence collected for this turn

        # Track rejected writes so the AI can't retry after user says "n"
        self._rejected_writes = set()  # File paths rejected this turn

        # Interrupt flags for soft cancel (Ctrl+C)
        self._interrupted = threading.Event()
        self._is_processing = threading.Event()

        # Lock for serializing message processing (used by Telegram processor)
        self._processing_lock = threading.Lock()

        # Flag: True when processing a Telegram-originated message
        self._telegram_mode = False
        self._telegram_processor_started = False

        # Teach mode: track if we've already asked the model to retry with annotations
        self._teach_retry_attempted = False

        # Sub-agent provider/model live in agent_config.json, not in session
        # state, so they survive /clear, restarts, and primary model switches.
        self._session_approve_shell = False
        self._pending_user_context = []
        self._memory_evicted_messages = 0
        self._memory_released_media_blocks = 0

        # Background job manager — completion notifications and result tracking
        self._injected_job_ids = set()
        from .background import get_job_manager
        get_job_manager().set_completion_callback(self._on_background_job_complete)

        # Initialize protection manager with config settings
        from .rate_limiter import BudgetGuard, CircuitBreaker, RateLimiter

        self.protection = ProtectionManager(
            rate_limiter=RateLimiter(
                max_calls_per_turn=config.max_api_calls_per_turn,
                cooldown_ms=config.rate_limit_cooldown_ms,
            ),
            circuit_breaker=CircuitBreaker(
                threshold=config.circuit_breaker_threshold,
            ),
            budget_guard=BudgetGuard(
                max_input_tokens=config.max_session_input_tokens,
                max_output_tokens=config.max_session_output_tokens,
            ),
        )

        # MCP client manager (optional — requires `pip install radsimcli[mcp]`)
        self._mcp_manager = None
        try:
            from .mcp_client import get_mcp_manager, is_mcp_sdk_installed

            if is_mcp_sdk_installed():
                self._mcp_manager = get_mcp_manager()
                connected = self._mcp_manager.connect_auto_servers()
                if connected:
                    from .output import print_info as _mcp_info

                    _mcp_info(f"MCP: auto-connected to {', '.join(connected)}")
            else:
                logger.debug("MCP SDK not installed — MCP features disabled")
        except Exception as exc:
            logger.warning("MCP auto-connect failed: %s", exc)

        if context_file:
            self.load_initial_context(context_file)

    def start_telegram_processor(self):
        """Start a background thread that auto-processes incoming Telegram messages.

        Started when the listener is turned on rather than at boot, so a
        session that never uses Telegram never runs the polling thread.
        """
        if self._telegram_processor_started:
            return

        from .agent_telegram import start_telegram_processor

        start_telegram_processor(self)
        self._telegram_processor_started = True


def run_single_shot(config, prompt, context_file=None):
    """Run a single-shot command and return the result."""
    from .agent_runtime import run_single_shot as run_single_shot_runtime

    return run_single_shot_runtime(config, prompt, context_file)


def run_interactive(config, context_file=None):
    """Run the interactive conversation loop."""
    from .agent_runtime import run_interactive as run_interactive_runtime

    return run_interactive_runtime(config, context_file)


def print_tools_list():
    """Print list of available tools."""
    from .agent_runtime import print_tools_list as print_tools_list_runtime

    return print_tools_list_runtime()
