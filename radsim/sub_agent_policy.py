"""Enforcement layer for every subagent tool call.

The subagent runner must never reach ``execute_tool`` directly. Each requested
call goes through :class:`SubAgentPolicyBroker`, which re-checks what the model
was offered against what policy still allows, and fails closed on anything it
cannot positively approve.

The checks run in this order, cheapest and most absolute first:

1. Cancellation — a cancelled job stops issuing work immediately.
2. Call budget — a bounded number of tool calls per task.
3. Profile allowlist — the tool must be one this profile offered.
4. Never-delegated set — recursion, credentials, self-extension, and outbound
   messaging are refused for every profile.
5. Agent settings — a tool the user disabled stays disabled for subagents.
6. Background limits — a background job may not mutate or execute code.
7. Path validation — reads and writes stay inside the project, with protected
   secrets refused outright.
"""

import json
import logging
import time

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOOL_CALLS = 40

# Wall-clock ceiling for one delegated task. A background job that never
# returns would otherwise hold a thread and keep spending tokens with nobody
# watching it.
DEFAULT_TASK_TIMEOUT_SECONDS = 600

# Refused for every profile, including future ones. These are the capabilities
# whose blast radius reaches outside the delegated task: another agent, the
# credential store, RadSim's own extension surface, or a third party.
NEVER_DELEGATED_TOOLS = frozenset(
    {
        "delegate_task",
        "add_tool",
        "remove_tool",
        "list_custom_tools",
        "deploy",
        "send_telegram",
        "schedule_task",
        "list_schedules",
        "save_memory",
        "forget_memory",
        "load_memory",
        "save_context",
        "add_skill",
        "remove_skill",
        "install_system_tool",
        "run_shell_command",
        "run_docker",
        "database_query",
        "delete_file",
        "rename_file",
        "git_add",
        "git_commit",
        "git_checkout",
        "git_stash",
        "npm_install",
        "pip_install",
        "add_dependency",
        "remove_dependency",
        "http_request",
        "screen_capture",
    }
)

# Tools that change project state. A background job may not call these.
MUTATING_TOOLS = frozenset(
    {
        "write_file",
        "replace_in_file",
        "multi_edit",
        "apply_patch",
        "batch_replace",
        "create_directory",
        "refactor_code",
        "format_code",
        "init_project",
    }
)

# Tools that execute project code. A background job may not call these either.
EXECUTING_TOOLS = frozenset({"run_tests", "lint_code", "type_check", "generate_tests"})

# Tool arguments that name a filesystem path, so the broker can canonicalise
# and check them the same way the main agent does.
PATH_ARGUMENT_KEYS = (
    "file_path",
    "file_paths",
    "directory_path",
    "path",
    "test_path",
    "target_path",
)


class SubAgentPolicyDenial(Exception):
    """Raised internally when a tool call fails a policy check."""


class SubAgentPolicyBroker:
    """Approves and runs one subagent's tool calls.

    Args:
        profile_name: Canonical capability profile the subagent runs under.
        background: True when running as a background job.
        cancel_event: Optional ``threading.Event`` signalling cancellation.
        max_tool_calls: Hard ceiling on tool calls for the whole task.
        timeout_seconds: Wall-clock ceiling for the whole task.
        executor: Callable used to run an approved tool. Defaults to the tool
            registry's ``execute_tool``; the agent passes its own
            permission-checked dispatcher for foreground mutation.
    """

    def __init__(
        self,
        profile_name,
        *,
        background=False,
        cancel_event=None,
        max_tool_calls=DEFAULT_MAX_TOOL_CALLS,
        timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS,
        executor=None,
    ):
        from .sub_agent_profiles import get_profile, resolve_profile_name

        self.profile_name = resolve_profile_name(profile_name)
        self.profile = get_profile(self.profile_name)
        self.background = background
        self.cancel_event = cancel_event
        self.max_tool_calls = max_tool_calls
        self.deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
        self._executor = executor
        self.call_count = 0
        self.decisions = []

    # -- public API --------------------------------------------------------

    def is_cancelled(self):
        """Return True when the owning job has been cancelled."""
        return bool(self.cancel_event and self.cancel_event.is_set())

    def is_expired(self):
        """Return True once the task has run past its wall-clock deadline."""
        return self.deadline is not None and time.monotonic() >= self.deadline

    def should_stop(self):
        """Return True when the task must stop for any bounded-work reason."""
        return self.is_cancelled() or self.is_expired()

    def check(self, tool_name, tool_input):
        """Decide whether one tool call may proceed.

        Returns:
            (allowed: bool, reason: str) — reason is empty when allowed.
        """
        try:
            self._run_checks(tool_name, tool_input or {})
        except SubAgentPolicyDenial as denial:
            return False, str(denial)
        return True, ""

    def execute(self, tool_name, tool_input):
        """Check and run one tool call, recording the decision.

        Returns a tool-result dict in the same shape the registry returns, so
        a denial and a failure are indistinguishable to the subagent: neither
        is an invitation to try another route.
        """
        tool_input = tool_input or {}
        allowed, reason = self.check(tool_name, tool_input)
        if not allowed:
            self._record(tool_name, allowed=False, reason=reason)
            logger.info("Subagent tool '%s' denied: %s", tool_name, reason)
            return {"success": False, "error": f"BLOCKED by subagent policy: {reason}"}

        self.call_count += 1
        self._record(tool_name, allowed=True, reason="")

        try:
            return self._run(tool_name, tool_input)
        except Exception as error:
            logger.error("Subagent tool '%s' failed: %s", tool_name, error)
            return {"success": False, "error": str(error)}

    def execute_blocks(self, tool_use_blocks):
        """Run a response's tool_use blocks and return tool_result blocks."""
        results = []
        for block in tool_use_blocks:
            tool_use_id = block.get("id", "")
            result = self.execute(block.get("name", ""), block.get("input", {}))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(result),
                    **({"is_error": True} if not result.get("success") else {}),
                }
            )
        return results

    def summary(self):
        """Return a non-sensitive record of what this subagent attempted.

        Tool names and decisions only — arguments may carry file contents or
        user data, so they are never logged here.
        """
        return {
            "profile": self.profile_name,
            "tool_calls": self.call_count,
            "denied": [entry["tool"] for entry in self.decisions if not entry["allowed"]],
        }

    # -- checks ------------------------------------------------------------

    def _run_checks(self, tool_name, tool_input):
        """Apply every policy check, raising SubAgentPolicyDenial on failure."""
        if self.is_cancelled():
            raise SubAgentPolicyDenial("task was cancelled")

        if self.is_expired():
            raise SubAgentPolicyDenial("task exceeded its time limit")

        if self.call_count >= self.max_tool_calls:
            raise SubAgentPolicyDenial(f"tool call limit reached ({self.max_tool_calls})")

        if not tool_name or not isinstance(tool_name, str):
            raise SubAgentPolicyDenial("no tool name supplied")

        if tool_name in NEVER_DELEGATED_TOOLS:
            raise SubAgentPolicyDenial(f"'{tool_name}' is never available to a subagent")

        if tool_name not in self.profile["tools"]:
            raise SubAgentPolicyDenial(
                f"'{tool_name}' is outside the '{self.profile_name}' profile"
            )

        self._check_tool_enabled(tool_name)
        self._check_background_limits(tool_name)
        self._check_paths(tool_name, tool_input)

    def _check_tool_enabled(self, tool_name):
        """Honour the user's own tool switches from agent settings."""
        try:
            from .agent_config import get_agent_config_manager

            enabled = get_agent_config_manager().is_tool_enabled(tool_name)
        except Exception:
            logger.warning("Agent tool policy unavailable; blocking subagent call", exc_info=True)
            raise SubAgentPolicyDenial("tool policy could not be evaluated") from None

        if not enabled:
            raise SubAgentPolicyDenial(f"'{tool_name}' is disabled in agent settings")

    def _check_background_limits(self, tool_name):
        """A background job may not change state or run project code.

        Nothing is watching a background job, so there is no one to confirm a
        mutation. The profile gate blocks this too; this check stops a
        background job that was started under a mutating profile.
        """
        if not self.background:
            return

        if not self.profile["allows_background"]:
            raise SubAgentPolicyDenial(
                f"profile '{self.profile_name}' cannot run as a background job"
            )
        if tool_name in MUTATING_TOOLS:
            raise SubAgentPolicyDenial("background jobs cannot modify files")
        if tool_name in EXECUTING_TOOLS:
            raise SubAgentPolicyDenial("background jobs cannot execute project code")

    def _check_paths(self, tool_name, tool_input):
        """Canonicalise every path argument and refuse secrets or escapes."""
        from .tools.validation import is_secret_read_path, validate_path

        for candidate in _collect_paths(tool_input):
            is_safe, resolved, error = validate_path(candidate)
            if not is_safe:
                raise SubAgentPolicyDenial(error or f"path '{candidate}' is outside the project")

            resolved_str = str(resolved) if resolved is not None else None
            is_secret, secret_reason = is_secret_read_path(candidate, resolved_str)
            if is_secret:
                raise SubAgentPolicyDenial(
                    f"'{tool_name}' targets protected credentials ({secret_reason}); "
                    "a subagent may never read secrets"
                )

    # -- execution ---------------------------------------------------------

    def _run(self, tool_name, tool_input):
        """Run an approved tool through the configured executor."""
        if self._executor is not None:
            return self._executor(tool_name, tool_input)

        from .tools import execute_tool

        return execute_tool(tool_name, tool_input)

    def _record(self, tool_name, allowed, reason):
        """Record one decision without capturing arguments or payloads."""
        self.decisions.append({"tool": tool_name, "allowed": allowed, "reason": reason})


def _collect_paths(tool_input):
    """Yield every filesystem path named in a tool's arguments."""
    paths = []
    for key in PATH_ARGUMENT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(item for item in value if isinstance(item, str) and item)

    for edit in tool_input.get("edits", []) or []:
        if isinstance(edit, dict):
            candidate = edit.get("file_path")
            if isinstance(candidate, str) and candidate:
                paths.append(candidate)

    return paths
