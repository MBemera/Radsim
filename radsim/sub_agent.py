"""Sub-Agent Task Delegation for RadSim.

RadSim Principle: Explicit Over Implicit
Sub-agents execute specific tasks with selected models while
context stays in the main conversation.
"""

import json
import logging
from collections.abc import Generator
from dataclasses import dataclass, field

from .api_client import create_client
from .config import load_env_file

logger = logging.getLogger(__name__)


@dataclass
class SubAgentTask:
    """A task to be executed by a sub-agent."""

    task_description: str
    model: str
    provider: str = "openrouter"
    api_key: str = ""
    system_prompt: str = ""
    max_tokens: int = 4096
    tools: list = field(default_factory=list)  # Tool definitions for API (empty = text-only)
    max_iterations: int = 10  # Safety limit for agentic loop


@dataclass
class SubAgentResult:
    """Result from a sub-agent task execution."""

    success: bool
    content: str
    model_used: str
    provider_used: str
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


# Haiku model ID — used for fast/quick tasks (web fetch, summarization, etc.)
HAIKU_MODEL = "anthropic/claude-haiku-4.5"


def get_available_models() -> list[tuple[str, str]]:
    """Get available sub-agent models from OpenRouter config.

    Returns only models listed in PROVIDER_MODELS["openrouter"]
    from config.py — no alternatives outside the config list.

    Returns:
        List of (model_id, description) tuples
    """
    from .config import PROVIDER_MODELS

    return list(PROVIDER_MODELS.get("openrouter", []))


def _build_model_aliases() -> dict[str, str]:
    """Build model aliases from the OpenRouter config list.

    Maps short names (derived from model IDs) to full model IDs.
    Only includes models from PROVIDER_MODELS["openrouter"].
    """
    aliases = {}
    for model_id, _desc in get_available_models():
        # "moonshotai/kimi-k2.5" -> "kimi-k2.5" and "kimi"
        short_name = model_id.split("/")[-1] if "/" in model_id else model_id
        aliases[short_name.lower()] = model_id

        # Also add a shorter alias (first part before dash/dot)
        base_name = short_name.split("-")[0].split(".")[0]
        if base_name.lower() not in aliases:
            aliases[base_name.lower()] = model_id

    # Always include haiku for fast tier (may not be in config list)
    aliases["haiku"] = HAIKU_MODEL
    aliases["fast"] = HAIKU_MODEL

    return aliases

# Tool subsets for tiered access
TOOL_SUBSETS = {
    "read_only": [
        "read_file",
        "read_many_files",
        "list_directory",
        "glob_files",
        "grep_search",
        "search_files",
        "find_definition",
        "find_references",
        "get_project_info",
        "git_status",
        "git_diff",
        "git_log",
        "analyze_code",
        "repo_map",
        "web_fetch",
        "todo_read",
        "submit_completion",
    ],
    "full": None,  # All tools available
}

# Model tiers for task-appropriate routing
MODEL_TIERS = {
    "fast": {
        "description": "Quick, cheap tasks: summarization, exploration, simple Q&A",
        "default_model": "anthropic/claude-haiku-4.5",
        "max_tokens": 2048,
        "tool_subset": "read_only",
    },
    "capable": {
        "description": "Complex tasks: refactoring, multi-file edits, code generation",
        "default_model": "z-ai/glm-4.7",
        "max_tokens": 4096,
        "tool_subset": "full",
    },
    "review": {
        "description": "Code review, security audit, quality checks",
        "default_model": "anthropic/claude-haiku-4.5",
        "max_tokens": 3072,
        "tool_subset": "read_only",
    },
}


def resolve_model_name(model_name: str) -> str:
    """Resolve a model alias to its full OpenRouter model ID.

    Only resolves to models in PROVIDER_MODELS["openrouter"] or Haiku.

    Args:
        model_name: Model alias or full model ID

    Returns:
        Full OpenRouter model ID
    """
    aliases = _build_model_aliases()

    if model_name.lower() in aliases:
        return aliases[model_name.lower()]

    # Check if it's already a full model ID listed in config
    config_model_ids = {mid for mid, _desc in get_available_models()}
    config_model_ids.add(HAIKU_MODEL)
    if model_name in config_model_ids:
        return model_name

    # Unknown model — fall back to Haiku for safety
    logger.warning(f"Unknown sub-agent model '{model_name}', falling back to Haiku")
    return HAIKU_MODEL


def get_openrouter_api_key() -> str | None:
    """Get the OpenRouter API key from environment.

    Returns:
        API key string or None if not found
    """
    import os

    # Check environment variable first
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        return api_key

    # Check .env file
    env_config = load_env_file()
    api_key = env_config.get("keys", {}).get("OPENROUTER_API_KEY")

    return api_key


def list_available_models() -> dict[str, str]:
    """List all available sub-agent models from OpenRouter config.

    Returns:
        Dict mapping model IDs to descriptions
    """
    models = {}
    for model_id, description in get_available_models():
        models[model_id] = description

    # Always include Haiku for fast tasks
    if HAIKU_MODEL not in models:
        models[HAIKU_MODEL] = "Claude Haiku 4.5 (Fast)"

    return models


def get_tools_for_tier(tier_name):
    """Return filtered tool definitions for a sub-agent tier.

    Args:
        tier_name: One of 'fast', 'capable', 'review'.

    Returns:
        List of tool definition dicts for the tier.
    """
    from .tools.definitions import TOOL_DEFINITIONS

    tier = MODEL_TIERS.get(tier_name, MODEL_TIERS["capable"])
    subset_name = tier["tool_subset"]

    if subset_name is None or TOOL_SUBSETS.get(subset_name) is None:
        return TOOL_DEFINITIONS  # Full access

    allowed_tools = set(TOOL_SUBSETS[subset_name])
    return [t for t in TOOL_DEFINITIONS if t["name"] in allowed_tools]


def resolve_task_config(task_description, tier="capable", model=None):
    """Resolve tier and model into final execution config.

    Args:
        task_description: Description of the sub-agent task.
        tier: Model tier ('fast', 'capable', 'review').
        model: Optional model override (alias or full ID).

    Returns:
        dict with 'model', 'max_tokens', 'tools'.
    """
    tier_config = MODEL_TIERS.get(tier, MODEL_TIERS["capable"])

    resolved_model = model if model else tier_config["default_model"]
    resolved_model = resolve_model_name(resolved_model)

    return {
        "model": resolved_model,
        "max_tokens": tier_config["max_tokens"],
        "tools": get_tools_for_tier(tier),
    }


def _execute_tool_calls(tool_use_blocks):
    """Execute tool_use blocks and return tool_result messages.

    Args:
        tool_use_blocks: List of tool_use content blocks from API response

    Returns:
        List of tool_result content blocks for the next API call
    """
    from .tools import execute_tool

    results = []
    for block in tool_use_blocks:
        tool_name = block.get("name", "")
        tool_input = block.get("input", {})
        tool_use_id = block.get("id", "")

        logger.debug(f"Sub-agent calling tool: {tool_name}")
        try:
            result = execute_tool(tool_name, tool_input)
            results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(result),
            })
        except Exception as e:
            logger.error(f"Sub-agent tool {tool_name} failed: {e}")
            results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps({"success": False, "error": str(e)}),
                "is_error": True,
            })

    return results


def _extract_text_from_response(response):
    """Extract text content from an API response.

    Args:
        response: API response dict with "content" blocks

    Returns:
        Concatenated text from all text blocks
    """
    parts = []
    for block in response.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _response_has_tool_use(response):
    """Check if an API response contains tool_use blocks.

    Args:
        response: API response dict

    Returns:
        True if any content block is type tool_use
    """
    for block in response.get("content", []):
        if block.get("type") == "tool_use":
            return True
    return False


def _get_tool_use_blocks(response):
    """Extract tool_use blocks from an API response.

    Args:
        response: API response dict

    Returns:
        List of tool_use content blocks
    """
    return [b for b in response.get("content", []) if b.get("type") == "tool_use"]


def execute_subagent_task(task: SubAgentTask) -> SubAgentResult:
    """Execute a task using a sub-agent with specified model.

    Supports an agentic loop: if tools are provided and the model
    returns tool_use blocks, tools are executed and results fed back
    until the model returns a text-only response or max_iterations is hit.

    Args:
        task: SubAgentTask containing task details and model selection

    Returns:
        SubAgentResult with execution results
    """
    model_id = resolve_model_name(task.model)
    provider = task.provider

    api_key = task.api_key or get_openrouter_api_key()
    if not api_key:
        return SubAgentResult(
            success=False,
            content="",
            model_used=model_id,
            provider_used=provider,
            error="No API key found for sub-agent. Check your provider configuration.",
        )

    try:
        client = create_client(provider, api_key, model_id)
        messages = [{"role": "user", "content": task.task_description}]
        system_prompt = task.system_prompt or "You are a helpful assistant. Complete the task directly and concisely."
        tools = task.tools if task.tools else None

        total_input_tokens = 0
        total_output_tokens = 0

        for _iteration in range(task.max_iterations):
            response = client.chat(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
            )

            usage = response.get("usage", {})
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)

            # If no tools provided or no tool_use in response, we're done
            if not tools or not _response_has_tool_use(response):
                content = _extract_text_from_response(response)
                return SubAgentResult(
                    success=True,
                    content=content,
                    model_used=model_id,
                    provider_used=provider,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            # Execute tool calls and continue the loop
            tool_use_blocks = _get_tool_use_blocks(response)
            tool_results = _execute_tool_calls(tool_use_blocks)

            # Append assistant response and tool results to conversation
            messages.append({"role": "assistant", "content": response.get("content", [])})
            messages.append({"role": "user", "content": tool_results})

        # Hit max iterations — return what we have with a warning
        content = _extract_text_from_response(response)
        warning = f"\n\n[WARNING: Sub-agent hit max iterations ({task.max_iterations}). Response may be incomplete.]"
        return SubAgentResult(
            success=True,
            content=content + warning,
            model_used=model_id,
            provider_used=provider,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

    except Exception as error:
        logger.error(f"Sub-agent task failed: {error}")
        return SubAgentResult(
            success=False,
            content="",
            model_used=model_id,
            provider_used=provider,
            error=str(error),
        )


def stream_subagent_task(task: SubAgentTask) -> Generator[dict, None, SubAgentResult]:
    """Execute a sub-agent task with streaming output.

    Yields text deltas as they arrive. When tools are invoked,
    yields tool_status messages and loops for the next streaming call.

    Args:
        task: SubAgentTask containing task details

    Yields:
        {"type": "text_delta", "text": str} for each text chunk
        {"type": "tool_status", "text": str} when tools are being executed

    Returns:
        SubAgentResult with full execution results
    """
    model_id = resolve_model_name(task.model)
    provider = task.provider

    api_key = task.api_key or get_openrouter_api_key()
    if not api_key:
        return SubAgentResult(
            success=False,
            content="",
            model_used=model_id,
            provider_used=provider,
            error="No API key found for sub-agent. Check your provider configuration.",
        )

    try:
        client = create_client(provider, api_key, model_id)
        messages = [{"role": "user", "content": task.task_description}]
        system_prompt = task.system_prompt or "You are a helpful assistant. Complete the task directly and concisely."
        tools = task.tools if task.tools else None

        full_content = ""
        total_input_tokens = 0
        total_output_tokens = 0

        for _iteration in range(task.max_iterations):
            final_response = None

            for chunk in client.stream_chat(
                messages=messages,
                system_prompt=system_prompt,
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

            # Check if the final response has tool_use blocks
            if not tools or not final_response or not _response_has_tool_use(final_response):
                return SubAgentResult(
                    success=True,
                    content=full_content,
                    model_used=model_id,
                    provider_used=provider,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            # Execute tools silently, yield status updates
            tool_use_blocks = _get_tool_use_blocks(final_response)
            tool_names = [b.get("name", "?") for b in tool_use_blocks]
            yield {"type": "tool_status", "text": f"Running tools: {', '.join(tool_names)}"}

            tool_results = _execute_tool_calls(tool_use_blocks)

            # Append to conversation for next iteration
            messages.append({"role": "assistant", "content": final_response.get("content", [])})
            messages.append({"role": "user", "content": tool_results})

        # Hit max iterations
        warning = f"\n\n[WARNING: Sub-agent hit max iterations ({task.max_iterations}). Response may be incomplete.]"
        full_content += warning
        return SubAgentResult(
            success=True,
            content=full_content,
            model_used=model_id,
            provider_used=provider,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

    except Exception as error:
        logger.error(f"Sub-agent streaming task failed: {error}")
        return SubAgentResult(
            success=False,
            content="",
            model_used=model_id,
            provider_used=provider,
            error=str(error),
        )


# =============================================================================
# Convenience Functions
# =============================================================================


def delegate_task(
    task_description: str,
    model: str = "haiku",
    provider: str = "openrouter",
    api_key: str = "",
    system_prompt: str = "",
    tools: list | None = None,
    max_iterations: int = 10,
) -> SubAgentResult:
    """Delegate a task to a sub-agent with specified model.

    This is the main convenience function for sub-agent delegation.
    Context stays in the main conversation - only the task result
    is returned.

    When provider and api_key are supplied, the sub-agent uses the
    same provider as the main agent instead of defaulting to OpenRouter.

    Args:
        task_description: What the sub-agent should do
        model: Model to use (alias or full OpenRouter model ID from config)
        provider: Provider to use (defaults to "openrouter")
        api_key: API key for the provider (falls back to OpenRouter key)
        system_prompt: Optional system prompt for the sub-agent
        tools: Tool definitions for the sub-agent (None = text-only)
        max_iterations: Safety limit for tool-use agentic loop

    Returns:
        SubAgentResult with task outcome

    Example:
        >>> result = delegate_task(
        ...     "Summarize this code: def hello(): print('world')",
        ...     model="moonshotai/kimi-k2.5"
        ... )
        >>> print(result.content)
        "This function prints 'world' when called."
    """
    task = SubAgentTask(
        task_description=task_description,
        model=model,
        provider=provider,
        api_key=api_key,
        system_prompt=system_prompt,
        tools=tools or [],
        max_iterations=max_iterations,
    )
    return execute_subagent_task(task)


def quick_task(task_description: str) -> str:
    """Execute a quick task with Haiku (fast + cheap).

    Simplest way to delegate a task — uses Haiku for speed,
    returns just the content string.

    Args:
        task_description: What to do

    Returns:
        Response content as string, or error message

    Example:
        >>> response = quick_task("What is 2 + 2?")
        >>> print(response)
        "4"
    """
    result = delegate_task(task_description, model="haiku")

    if result.success:
        return result.content

    return f"Error: {result.error}"
