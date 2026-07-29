"""Sub-agent task execution for RadSim.

RadSim Principle: Explicit Over Implicit

A subagent runs one bounded task under three separate, explicit decisions:

- which model, from the user's persistent selection (never chosen here);
- which capability profile, from a locked allowlist (never widened here);
- which tools may actually run, decided per call by the policy broker.

Nothing in this module grants permission. It resolves a validated
provider/model pair, composes an immutable prompt, offers the profile's tool
schemas, and routes every requested call through
:class:`~radsim.sub_agent_policy.SubAgentPolicyBroker`.
"""

import logging
from collections.abc import Generator
from dataclasses import dataclass, field

from .api_client import create_client
from .sub_agent_policy import DEFAULT_TASK_TIMEOUT_SECONDS
from .sub_agent_profiles import (
    DEFAULT_PROFILE,
    ProfileError,
    compose_subagent_prompt,
    get_profile,
    get_tools_for_profile,
    resolve_profile_name,
)

logger = logging.getLogger(__name__)

# A subagent result is evidence for the primary agent, not a document. Cap it
# so a runaway or hostile response cannot flood the conversation or a job store.
MAX_RESULT_CHARS = 20_000

# Per-task context supplied by the primary model, capped for the same reason.
MAX_TASK_CHARS = 20_000


class SubAgentModelError(ValueError):
    """Raised when no valid subagent provider/model pair is available."""


@dataclass
class SubAgentTask:
    """One bounded task for a subagent.

    ``provider`` and ``model`` are the user's persistent selection, passed in
    by the caller. This module never picks them, and never falls back to
    another model when they are missing or invalid.
    """

    task_description: str
    provider: str
    model: str
    profile: str = DEFAULT_PROFILE
    custom_instructions: str = ""
    api_key: str = ""
    max_tokens: int = 0
    max_iterations: int = 10
    timeout_seconds: float = DEFAULT_TASK_TIMEOUT_SECONDS
    background: bool = False
    cancel_event: object = None
    executor: object = None
    tools: list = field(default_factory=list)


@dataclass
class SubAgentResult:
    """Result from a subagent task execution."""

    success: bool
    content: str
    model_used: str
    provider_used: str
    profile_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    denied_tools: list = field(default_factory=list)
    cancelled: bool = False
    error: str = ""


def get_available_models(provider):
    """Return the catalogue entries for one provider.

    Returns:
        List of (model_id, description) tuples. Empty for an unknown provider.
    """
    from .config import PROVIDER_MODELS

    return list(PROVIDER_MODELS.get(provider, []))


def resolve_subagent_model(provider, model):
    """Validate a subagent provider/model pair and resolve its credential.

    Fails closed on every failure path. An unknown model, an unknown provider,
    or a missing credential raises with a specific message so the user can fix
    it, instead of silently running a different model than the one they chose.

    Returns:
        (provider, model, api_key)

    Raises:
        SubAgentModelError: when the pair is unusable.
    """
    from .config import get_provider_api_key, is_supported_provider_model

    supported, reason = is_supported_provider_model(provider, model)
    if not supported:
        raise SubAgentModelError(
            f"{reason}. Run '/subagent model' to choose a subagent provider and model."
        )

    api_key = get_provider_api_key(provider)
    if not api_key:
        raise SubAgentModelError(
            f"No API key configured for provider '{provider}'. "
            f"Run '/login {provider}' to add one. Neither model selection was changed."
        )

    return provider, model, api_key


def _cap(text, limit, label):
    """Trim oversized text and say so, rather than truncating silently."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[{label} truncated at {limit} characters]"


def _extract_text_from_response(response):
    """Extract text content from an API response."""
    parts = []
    for block in response.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _response_has_tool_use(response):
    """Check if an API response contains tool_use blocks."""
    return any(block.get("type") == "tool_use" for block in response.get("content", []))


def _get_tool_use_blocks(response):
    """Extract tool_use blocks from an API response."""
    return [block for block in response.get("content", []) if block.get("type") == "tool_use"]


def _create_subagent_client(provider, api_key, model_id):
    """Create a sub-agent client with the saved reasoning effort."""
    from .config import load_reasoning_effort, resolve_reasoning_effort

    reasoning_effort = resolve_reasoning_effort(
        provider,
        model_id,
        load_reasoning_effort(),
    )
    return create_client(
        provider,
        api_key,
        model_id,
        reasoning_effort=reasoning_effort,
    )


def _prepare_run(task):
    """Resolve model, profile, prompt, tools, and broker for one task.

    Returns:
        (context: dict, error: SubAgentResult or None)
    """
    try:
        profile_name = resolve_profile_name(task.profile)
    except ProfileError as error:
        return None, SubAgentResult(
            success=False,
            content="",
            model_used=task.model or "",
            provider_used=task.provider or "",
            profile_used=str(task.profile or ""),
            error=str(error),
        )

    if task.background and not get_profile(profile_name)["allows_background"]:
        return None, SubAgentResult(
            success=False,
            content="",
            model_used=task.model or "",
            provider_used=task.provider or "",
            profile_used=profile_name,
            error=(
                f"Profile '{profile_name}' changes state or runs project code, so it "
                "cannot run in the background. Run it in the foreground instead."
            ),
        )

    try:
        provider, model_id, api_key = resolve_subagent_model(task.provider, task.model)
    except SubAgentModelError as error:
        return None, SubAgentResult(
            success=False,
            content="",
            model_used=task.model or "",
            provider_used=task.provider or "",
            profile_used=profile_name,
            error=str(error),
        )

    from .sub_agent_policy import SubAgentPolicyBroker

    broker = SubAgentPolicyBroker(
        profile_name,
        background=task.background,
        cancel_event=task.cancel_event,
        timeout_seconds=task.timeout_seconds,
        executor=task.executor,
    )

    return (
        {
            "profile_name": profile_name,
            "provider": provider,
            "model_id": model_id,
            "api_key": task.api_key or api_key,
            "broker": broker,
            "system_prompt": compose_subagent_prompt(profile_name, task.custom_instructions),
            "tools": get_tools_for_profile(profile_name) or None,
            "messages": [
                {"role": "user", "content": _cap(task.task_description, MAX_TASK_CHARS, "task")}
            ],
        },
        None,
    )


def _stopped_result(context, content=""):
    """Build the result returned when a task stops before finishing.

    Covers both bounded-work stops: an explicit cancellation and the
    wall-clock deadline. Whatever text the subagent produced so far is kept,
    but the result is never reported as a success.
    """
    broker = context["broker"]
    expired = broker.is_expired() and not broker.is_cancelled()
    return SubAgentResult(
        success=False,
        content=_cap(content, MAX_RESULT_CHARS, "result"),
        model_used=context["model_id"],
        provider_used=context["provider"],
        profile_used=context["profile_name"],
        tool_calls=broker.call_count,
        denied_tools=broker.summary()["denied"],
        cancelled=True,
        error=(
            "Task stopped at its time limit before completion."
            if expired
            else "Task cancelled before completion."
        ),
    )


def _finished_result(context, content, input_tokens, output_tokens):
    """Build the successful result for a completed task."""
    summary = context["broker"].summary()
    return SubAgentResult(
        success=True,
        content=_cap(content, MAX_RESULT_CHARS, "result"),
        model_used=context["model_id"],
        provider_used=context["provider"],
        profile_used=context["profile_name"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=summary["tool_calls"],
        denied_tools=summary["denied"],
    )


def execute_subagent_task(task: SubAgentTask) -> SubAgentResult:
    """Execute one bounded subagent task.

    Runs an agentic loop: while the model requests tools, each request goes
    through the policy broker and its result is fed back, until the model
    returns text, the iteration limit is reached, or the task is cancelled.
    """
    context, failure = _prepare_run(task)
    if failure is not None:
        return failure

    broker = context["broker"]
    messages = context["messages"]
    tools = context["tools"]

    try:
        client = _create_subagent_client(context["provider"], context["api_key"], context["model_id"])
        total_input_tokens = 0
        total_output_tokens = 0
        response = {}

        for _iteration in range(task.max_iterations):
            if broker.should_stop():
                return _stopped_result(context, _extract_text_from_response(response))

            response = client.chat(
                messages=messages,
                system_prompt=context["system_prompt"],
                tools=tools,
            )

            usage = response.get("usage", {})
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)

            if not tools or not _response_has_tool_use(response):
                return _finished_result(
                    context,
                    _extract_text_from_response(response),
                    total_input_tokens,
                    total_output_tokens,
                )

            if broker.should_stop():
                return _stopped_result(context, _extract_text_from_response(response))

            tool_results = broker.execute_blocks(_get_tool_use_blocks(response))
            messages.append({"role": "assistant", "content": response.get("content", [])})
            messages.append({"role": "user", "content": tool_results})

        content = _extract_text_from_response(response)
        warning = (
            f"\n\n[Sub-agent stopped at the iteration limit ({task.max_iterations}). "
            "The result may be incomplete.]"
        )
        return _finished_result(context, content + warning, total_input_tokens, total_output_tokens)

    except Exception as error:
        logger.error("Sub-agent task failed: %s", error)
        return SubAgentResult(
            success=False,
            content="",
            model_used=context["model_id"],
            provider_used=context["provider"],
            profile_used=context["profile_name"],
            tool_calls=broker.call_count,
            error=str(error),
        )


def stream_subagent_task(task: SubAgentTask) -> Generator[dict, None, SubAgentResult]:
    """Execute a subagent task with streaming output.

    Yields ``{"type": "text_delta", "text": str}`` for each text chunk and
    ``{"type": "tool_status", "text": str}`` while tools run. Returns the same
    :class:`SubAgentResult` the synchronous path produces.
    """
    context, failure = _prepare_run(task)
    if failure is not None:
        return failure

    broker = context["broker"]
    messages = context["messages"]
    tools = context["tools"]

    try:
        client = _create_subagent_client(context["provider"], context["api_key"], context["model_id"])
        full_content = ""
        total_input_tokens = 0
        total_output_tokens = 0

        for _iteration in range(task.max_iterations):
            if broker.should_stop():
                return _stopped_result(context, full_content)

            final_response = None
            for chunk in client.stream_chat(
                messages=messages,
                system_prompt=context["system_prompt"],
                tools=tools,
            ):
                if chunk.get("type") == "text_delta":
                    full_content += chunk.get("text", "")
                    yield chunk
                elif chunk.get("type") == "final_response":
                    final_response = chunk.get("response", {})

            usage = final_response.get("usage", {}) if final_response else {}
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)

            if not tools or not final_response or not _response_has_tool_use(final_response):
                return _finished_result(
                    context, full_content, total_input_tokens, total_output_tokens
                )

            if broker.should_stop():
                return _stopped_result(context, full_content)

            tool_use_blocks = _get_tool_use_blocks(final_response)
            tool_names = [block.get("name", "?") for block in tool_use_blocks]
            yield {"type": "tool_status", "text": f"Running tools: {', '.join(tool_names)}"}

            tool_results = broker.execute_blocks(tool_use_blocks)
            messages.append({"role": "assistant", "content": final_response.get("content", [])})
            messages.append({"role": "user", "content": tool_results})

        warning = (
            f"\n\n[Sub-agent stopped at the iteration limit ({task.max_iterations}). "
            "The result may be incomplete.]"
        )
        return _finished_result(
            context, full_content + warning, total_input_tokens, total_output_tokens
        )

    except Exception as error:
        logger.error("Sub-agent streaming task failed: %s", error)
        return SubAgentResult(
            success=False,
            content="",
            model_used=context["model_id"],
            provider_used=context["provider"],
            profile_used=context["profile_name"],
            tool_calls=broker.call_count,
            error=str(error),
        )


def delegate_task(
    task_description: str,
    provider: str,
    model: str,
    profile: str = DEFAULT_PROFILE,
    custom_instructions: str = "",
    api_key: str = "",
    max_iterations: int = 10,
    background: bool = False,
    cancel_event=None,
    executor=None,
) -> SubAgentResult:
    """Delegate one bounded task to a subagent.

    ``provider`` and ``model`` are required and must be the user's persistent
    selection. This is the low-level developer entry point; the model-facing
    ``delegate_task`` tool never supplies a model of its own.
    """
    task = SubAgentTask(
        task_description=task_description,
        provider=provider,
        model=model,
        profile=profile,
        custom_instructions=custom_instructions,
        api_key=api_key,
        max_iterations=max_iterations,
        background=background,
        cancel_event=cancel_event,
        executor=executor,
    )
    return execute_subagent_task(task)
