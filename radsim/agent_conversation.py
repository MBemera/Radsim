"""Conversation lifecycle helpers for the main agent."""

import logging
import time
from pathlib import Path

from .api_client import create_client
from .learning import flush_tool_optimizer, get_reflection_engine, get_tool_optimizer
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
        """Update agent configuration, client, and persist provider/model.

        A None model (e.g. from /login, which only changes credentials)
        keeps the current model rather than nulling the live client.
        """
        if not model:
            from .config import DEFAULT_MODELS

            model = self.config.model or DEFAULT_MODELS.get(provider)

        self.config.provider = provider
        self.config.api_key = api_key
        self.config.model = model
        self.client = create_client(provider, api_key, model)

        try:
            from .config import save_config

            save_config(api_key, provider, model)
        except Exception as error:
            logger.debug("Failed to persist provider/model: %s", error)
            print_warning(f"Switched in this session, but could not save preference: {error}")

        print_success(f"Switched to {provider} ({model})")

    def reset(self):
        """Clear conversation history."""
        self.messages = []
        self._last_response = ""
        self._current_task_start = None
        self._current_task_tools = []
        self._injected_job_ids = set()
        self._session_approve_shell = False
        self._pending_user_context = []

    def estimate_tokens(self, text):
        """Estimate token count for text (rough approximation)."""
        return len(text) // 4

    def get_context_usage(self):
        """Get current context usage as percentage."""
        from .config import get_context_limit

        max_tokens = get_context_limit(self.config.model)
        current_tokens = sum(self.estimate_tokens(str(message.get("content", ""))) for message in self.messages)
        percentage = (current_tokens / max_tokens) * 100 if max_tokens > 0 else 0
        return current_tokens, max_tokens, percentage

    def prune_session(self, target_percentage=70):
        """Prune old messages to reduce context size."""
        from .config import get_context_limit

        max_tokens = get_context_limit(self.config.model)
        message_weights = [
            self.estimate_tokens(str(message.get("content", "")))
            for message in self.messages
        ]
        current_tokens = sum(message_weights)
        target_tokens = int(max_tokens * (target_percentage / 100))

        if current_tokens <= target_tokens:
            return 0

        cut_index = self._find_prune_cut(message_weights, current_tokens, target_tokens)
        cut_index = self._skip_orphaned_results(cut_index)
        pruned = cut_index - 2

        if pruned > 0:
            del self.messages[2:cut_index]
            self.get_context_usage()
            print_info(f"Session pruned: removed {pruned} old messages")

        return pruned

    def _find_prune_cut(self, message_weights, current_tokens, target_tokens):
        """Find the end of the contiguous prunable prefix."""
        cut_index = 2
        removed_tokens = 0

        while current_tokens - removed_tokens > target_tokens:
            remaining_messages = 2 + len(self.messages) - cut_index
            if remaining_messages <= 4:
                break
            unit_end = self._pruning_unit_end(cut_index)
            removed_tokens += sum(message_weights[cut_index:unit_end])
            cut_index = unit_end

        return cut_index

    def _pruning_unit_end(self, start_index):
        """Return the boundary after one legacy pair or tool exchange."""
        next_index = start_index + 1
        if next_index >= len(self.messages):
            return next_index

        message = self.messages[start_index]
        next_message = self.messages[next_index]
        if self._is_tool_exchange(message, next_message):
            return next_index + 1

        following_index = next_index + 1
        if following_index < len(self.messages):
            following_message = self.messages[following_index]
            if self._is_tool_exchange(next_message, following_message):
                return next_index

        return next_index + 1

    def _skip_orphaned_results(self, cut_index):
        """Move a prune boundary beyond malformed orphan tool results."""
        while cut_index < len(self.messages):
            message = self.messages[cut_index]
            if not self._contains_block_type(message, "tool_result"):
                break
            cut_index += 1
        return cut_index

    def _is_tool_exchange(self, message, next_message):
        """Return whether two messages are an indivisible tool exchange."""
        return (
            message.get("role") == "assistant"
            and next_message.get("role") == "user"
            and self._contains_block_type(message, "tool_use")
            and self._contains_block_type(next_message, "tool_result")
        )

    def _contains_block_type(self, message, block_type):
        """Return whether a message contains a structured block type."""
        content = message.get("content")
        if not isinstance(content, list):
            return False
        return any(
            isinstance(block, dict) and block.get("type") == block_type
            for block in content
        )

    def _drop_orphaned_tool_messages(self, start_index=2):
        """Remove tool_result messages orphaned by pruning.

        After pruning, the message at start_index must not be a
        tool_result whose tool_use was deleted.

        Returns:
            int: Number of messages removed.
        """

        removed = 0
        while len(self.messages) > start_index:
            boundary_message = self.messages[start_index]
            is_orphan_result = boundary_message.get(
                "role"
            ) == "user" and self._contains_block_type(boundary_message, "tool_result")
            if not is_orphan_result:
                break
            self.messages.pop(start_index)
            removed += 1
        return removed

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
            try:
                flush_tool_optimizer()
            except Exception:
                logger.debug("Tool optimizer flush failed at turn boundary", exc_info=True)
            stop_escape_listener()
            self._is_processing.clear()

    def _process_message_inner(self, user_input):
        """Inner message processing (wrapped by process_message for interrupt tracking)."""
        self.protection.on_user_input()
        self._rejected_writes.clear()
        self._current_task_start = time.time()
        self._current_task_tools = []
        self._refresh_session_activity(active_task=user_input)

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

        pending_context = getattr(self, "_pending_user_context", None)
        if pending_context:
            user_input = "\n\n".join([*pending_context, user_input])
            pending_context.clear()

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

    def _refresh_session_activity(self, active_task=None):
        """Mark the current session active for memory expiry.

        Also records what we're working on so an interrupted session can
        resume with "Active Task: ..." context.
        """
        try:
            from .runtime_context import get_runtime_context

            session_memory = get_runtime_context().get_memory().session_mem
            if active_task:
                session_memory.set_active_task(active_task.strip()[:100])
            else:
                session_memory.update_activity()
        except Exception:
            logger.debug("Session memory activity update failed", exc_info=True)
