"""Sub-Agent Task Delegation for RadSim.

RadSim Principle: Explicit Over Implicit
Sub-agents execute specific tasks with selected models while
context stays in the main conversation.
"""

import logging
from collections.abc import Generator
from dataclasses import dataclass

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


# Available sub-agent models (OpenRouter models that share the same API key)
SUBAGENT_MODELS = {
    # Free models
    "qwen-coder": "qwen/qwen3-coder:free",
    "arcee-trinity": "arcee-ai/trinity-large-preview:free",
    # Paid models
    "kimi": "moonshotai/kimi-k2.5",
    "glm-4": "z-ai/glm-4.7",
    "minimax": "minimax/minimax-m2.1",
    # Claude/OpenAI via OpenRouter
    "claude-opus": "anthropic/claude-opus-4.6",
    "claude-sonnet": "anthropic/claude-sonnet-4.6",
    "codex": "openai/gpt-5.2-codex",
}

# Model aliases for easier selection
MODEL_ALIASES = {
    "free": "qwen/qwen3-coder:free",
    "fast": "qwen/qwen3-coder:free",
    "smart": "z-ai/glm-4.7",
    "glm": "z-ai/glm-4.7",
    "mini": "minimax/minimax-m2.1",
    "minimax": "minimax/minimax-m2.1",
    "kimi": "moonshotai/kimi-k2.5",
    "qwen": "qwen/qwen3-coder:free",
    "arcee": "arcee-ai/trinity-large-preview:free",
    "opus": "anthropic/claude-opus-4.6",
    "sonnet": "anthropic/claude-sonnet-4.6",
    "codex": "openai/gpt-5.2-codex",
}


def resolve_model_name(model_name: str) -> str:
    """Resolve a model alias to its full OpenRouter model ID.

    Args:
        model_name: Model alias or full model ID

    Returns:
        Full OpenRouter model ID
    """
    # Check if it's an alias
    if model_name.lower() in MODEL_ALIASES:
        return MODEL_ALIASES[model_name.lower()]

    # Check if it's a short name in SUBAGENT_MODELS
    if model_name.lower() in SUBAGENT_MODELS:
        return SUBAGENT_MODELS[model_name.lower()]

    # Assume it's already a full model ID
    return model_name


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
    """List all available sub-agent models.

    Returns:
        Dict mapping short names to full model IDs
    """
    return {**SUBAGENT_MODELS, **MODEL_ALIASES}


def execute_subagent_task(task: SubAgentTask) -> SubAgentResult:
    """Execute a task using a sub-agent with specified model.

    The sub-agent runs independently but results are returned
    to the main context for integration.

    Args:
        task: SubAgentTask containing task details and model selection

    Returns:
        SubAgentResult with execution results
    """
    # Resolve model name
    model_id = resolve_model_name(task.model)
    provider = task.provider

    # Use provided API key first, fall back to OpenRouter key
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
        # Create client for sub-agent
        client = create_client(provider, api_key, model_id)

        # Build messages
        messages = [{"role": "user", "content": task.task_description}]

        # Execute request
        response = client.chat(
            messages=messages,
            system_prompt=task.system_prompt or "You are a helpful assistant. Complete the task directly and concisely.",
        )

        # Extract content
        content_parts = []
        for block in response.get("content", []):
            if block.get("type") == "text":
                content_parts.append(block.get("text", ""))

        content = "\n".join(content_parts)

        usage = response.get("usage", {})

        return SubAgentResult(
            success=True,
            content=content,
            model_used=model_id,
            provider_used=provider,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
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

    Yields text deltas as they arrive, returns final result.

    Args:
        task: SubAgentTask containing task details

    Yields:
        {"type": "text_delta", "text": str} for each chunk

    Returns:
        SubAgentResult with full execution results
    """
    # Resolve model name
    model_id = resolve_model_name(task.model)
    provider = task.provider

    # Use provided API key first, fall back to OpenRouter key
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
        # Create client for sub-agent
        client = create_client(provider, api_key, model_id)

        # Build messages
        messages = [{"role": "user", "content": task.task_description}]

        # Stream request
        full_content = ""
        final_response = None

        for chunk in client.stream_chat(
            messages=messages,
            system_prompt=task.system_prompt or "You are a helpful assistant. Complete the task directly and concisely.",
        ):
            if chunk.get("type") == "text_delta":
                full_content += chunk.get("text", "")
                yield chunk
            elif chunk.get("type") == "final_response":
                final_response = chunk.get("response", {})

        usage = final_response.get("usage", {}) if final_response else {}

        return SubAgentResult(
            success=True,
            content=full_content,
            model_used=model_id,
            provider_used=provider,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
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
    model: str = "free",
    provider: str = "openrouter",
    api_key: str = "",
    system_prompt: str = "",
) -> SubAgentResult:
    """Delegate a task to a sub-agent with specified model.

    This is the main convenience function for sub-agent delegation.
    Context stays in the main conversation - only the task result
    is returned.

    When provider and api_key are supplied, the sub-agent uses the
    same provider as the main agent instead of defaulting to OpenRouter.

    Args:
        task_description: What the sub-agent should do
        model: Model to use (alias like "free", "glm", "minimax" or full ID)
        provider: Provider to use (defaults to "openrouter")
        api_key: API key for the provider (falls back to OpenRouter key)
        system_prompt: Optional system prompt for the sub-agent

    Returns:
        SubAgentResult with task outcome

    Example:
        >>> result = delegate_task(
        ...     "Summarize this code: def hello(): print('world')",
        ...     model="glm"
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
    )
    return execute_subagent_task(task)


def quick_task(task_description: str) -> str:
    """Execute a quick task with the free model.

    Simplest way to delegate a task - uses free model,
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
    result = delegate_task(task_description, model="free")

    if result.success:
        return result.content

    return f"Error: {result.error}"
