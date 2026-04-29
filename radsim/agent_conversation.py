"""Conversation lifecycle helpers for the main agent."""

import logging
import time
from pathlib import Path

from .api_client import create_client
from .learning import get_reflection_engine, get_tool_optimizer
from .output import print_error, print_info, print_success, print_warning

logger = logging.getLogger(__name__)


class AgentConversationMixin:
    """Conversation state and lifecycle methods for the main agent."""

    def load_initial_context(self, file_path):
        """Load initial context from a file."""
        path = Path(file_path)
        if path.exists():
            try:
                content = path.read_text()
                self.messages.append(
                    {"role": "user", "content": f"Context loaded from {file_path}:\n\n{content}"}
                )
                self.messages.append(
                    {
                        "role": "assistant",
                        "content": f"I have loaded the context from {file_path}. How can I help you?",
                    }
                )
                print_info(f"Loaded context from {file_path}")
            except Exception as error:
                print_error(f"Failed to load context file: {error}")
        else:
            print_warning(f"Context file not found: {file_path}")

    def update_config(self, provider, api_key, model):
        """Update agent configuration and client."""
        self.config.provider = provider
        self.config.api_key = api_key
        self.config.model = model
        self.client = create_client(provider, api_key, model)
        print_success(f"Switched to {provider} ({model})")

    def reset(self):
        """Clear conversation history."""
        self.messages = []
        self._last_response = ""
        self._current_task_start = None
        self._current_task_tools = []
        self._injected_job_ids = set()

    def estimate_tokens(self, text):
        """Estimate token count for text (rough approximation)."""
        return len(text) // 4

    def get_context_usage(self):
        """Get current context usage as percentage."""
        from .config import CONTEXT_LIMITS

        max_tokens = CONTEXT_LIMITS.get(self.config.model, 100000)
        current_tokens = sum(self.estimate_tokens(str(message.get("content", ""))) for message in self.messages)
        percentage = (current_tokens / max_tokens) * 100 if max_tokens > 0 else 0
        return current_tokens, max_tokens, percentage

    def prune_session(self, target_percentage=70):
        """Prune old messages to reduce context size."""
        current, max_tokens, percentage = self.get_context_usage()

        if percentage <= target_percentage:
            return 0

        pruned = 0
        target_tokens = int(max_tokens * (target_percentage / 100))

        while current > target_tokens and len(self.messages) > 4:
            self.messages.pop(2)
            if len(self.messages) > 2:
                self.messages.pop(2)
            pruned += 2
            current, _, _ = self.get_context_usage()

        if pruned > 0:
            print_info(f"Session pruned: removed {pruned} old messages")

        return pruned

    def check_and_prune(self, threshold=80):
        """Check context usage and prune if over threshold."""
        _, _, percentage = self.get_context_usage()
        if percentage > threshold:
            self.prune_session(target_percentage=70)

    def process_message(self, user_input):
        """Process a user message and return the response."""
        self._interrupted.clear()
        self._is_processing.set()

        from .escape_listener import start_escape_listener, stop_escape_listener

        start_escape_listener(self)
        try:
            return self._process_message_inner(user_input)
        finally:
            stop_escape_listener()
            self._is_processing.clear()

    def _process_message_inner(self, user_input):
        """Inner message processing (wrapped by process_message for interrupt tracking)."""
        self.protection.on_user_input()
        self._rejected_writes.clear()
        self._current_task_start = time.time()
        self._current_task_tools = []
        self._refresh_session_activity()

        background_results = self._collect_finished_background_results()
        if background_results:
            self.messages.append(
                {
                    "role": "user",
                    "content": f"[SYSTEM: Background sub-agent results arrived]\n{background_results}",
                }
            )
            self.messages.append(
                {
                    "role": "assistant",
                    "content": "I have the background job results. Let me incorporate them.",
                }
            )

        self.messages.append({"role": "user", "content": user_input})
        self.check_and_prune(threshold=80)

        try:
            from .agent_config import get_agent_config_manager

            config_manager = get_agent_config_manager()
            if config_manager.is_learning_module_enabled("tool_optimization"):
                from .learning.tool_optimizer import suggest_tool_chain

                suggested_chain = suggest_tool_chain(user_input[:200])
                if suggested_chain:
                    chain_hint = ", ".join(suggested_chain[:5])
                    self.messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"[System hint: Based on past success, consider this tool sequence: {chain_hint}]",
                                }
                            ],
                        }
                    )
        except Exception:
            logger.debug("Learning suggestion failed, continuing main flow")

        response = self._call_api()
        result = self._handle_response(response)

        try:
            from .agent_config import get_agent_config_manager

            config_manager = get_agent_config_manager()

            if config_manager.is_learning_module_enabled("reflection"):
                task_duration = time.time() - self._current_task_start if self._current_task_start else 0
                reflection_engine = get_reflection_engine()
                reflection_engine.reflect_on_completion(
                    task_description=user_input[:200],
                    approach_taken=f"Used tools: {', '.join(self._current_task_tools[:10])}",
                    result=str(result)[:200] if result else "completed",
                    success=True,
                    tools_used=self._current_task_tools,
                    duration_seconds=task_duration,
                )

            if config_manager.is_learning_module_enabled("tool_optimization"):
                tool_optimizer = get_tool_optimizer()
                tool_optimizer.complete_task_chain(user_input[:200], success=True)

            if config_manager.get("self_improvement.enabled", False) and config_manager.get(
                "self_improvement.auto_propose", True
            ):
                from .learning.self_improver import get_self_improver

                improver = get_self_improver()
                new_reflections = improver.get_reflection_count_since_last_analysis()
                if new_reflections >= 10:
                    new_proposals = improver.analyze_and_propose()
                    if new_proposals:
                        print_info(
                            f"Self-improvement: {len(new_proposals)} new proposal(s). "
                            "Use /evolve to review."
                        )
        except Exception:
            logger.debug("Learning completion tracking failed, continuing main flow")

        return result

    def _refresh_session_activity(self):
        """Mark the current session active for memory expiry."""
        try:
            from .runtime_context import get_runtime_context

            get_runtime_context().get_memory().session_mem.update_activity()
        except Exception:
            logger.debug("Session memory activity update failed", exc_info=True)
