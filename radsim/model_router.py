"""Cost-Effective Model Routing - Graceful Degradation.

RadSim Principle: Graceful Degradation
Always define an explicit fallback chain. Never assume services are available.

Features:
- Automatic fallback when a model/provider is unavailable
- Cost-aware routing (prefer cheaper models for simple tasks)
- Provider health checking
- Configurable routing strategies
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .config import DEFAULT_MODELS, FALLBACK_MODELS, MODEL_PRICING


class TaskComplexity(Enum):
    """Task complexity levels for routing decisions."""

    SIMPLE = "simple"  # Quick lookups, simple edits
    MEDIUM = "medium"  # Multi-step tasks, code generation
    COMPLEX = "complex"  # Architecture, complex reasoning


@dataclass
class ModelInfo:
    """Information about a model for routing decisions."""

    model_id: str
    provider: str
    cost_per_1m_input: float
    cost_per_1m_output: float
    is_free: bool = False
    context_window: int = 100000

    @property
    def total_cost_estimate(self) -> float:
        """Estimate cost per typical request (1K input, 500 output)."""
        return (self.cost_per_1m_input * 1 / 1000) + (self.cost_per_1m_output * 0.5 / 1000)


@dataclass
class ProviderStatus:
    """Health status of a provider."""

    provider: str
    is_healthy: bool
    last_check: float  # timestamp
    error_count: int = 0
    last_error: str = ""


class ModelRouter:
    """Intelligent model routing with fallback support.

    Routes requests to the most appropriate model based on:
    - Task complexity
    - Cost constraints
    - Provider availability
    - User preferences
    """

    def __init__(self, primary_provider: str = "claude", primary_model: str = None):
        self.primary_provider = primary_provider
        self.primary_model = primary_model or DEFAULT_MODELS.get(primary_provider)

        # Provider health tracking
        self._provider_status: dict[str, ProviderStatus] = {}

        # Initialize all providers as healthy
        for provider in FALLBACK_MODELS:
            self._provider_status[provider] = ProviderStatus(
                provider=provider, is_healthy=True, last_check=time.time()
            )

    def get_fallback_chain(self, provider: str = None) -> list[tuple[str, str]]:
        """Get the fallback chain for a provider.

        Returns list of (provider, model) tuples in fallback order.
        """
        provider = provider or self.primary_provider
        chain = []

        # Add primary provider's models first
        if provider in FALLBACK_MODELS:
            for model in FALLBACK_MODELS[provider]:
                chain.append((provider, model))

        # Add free fallbacks
        if "openrouter" in FALLBACK_MODELS and provider != "openrouter":
            for model in FALLBACK_MODELS["openrouter"]:
                chain.append(("openrouter", model))

        return chain

    def mark_provider_unhealthy(self, provider: str, error: str):
        """Mark a provider as unhealthy after an error."""
        if provider in self._provider_status:
            status = self._provider_status[provider]
            status.is_healthy = False
            status.error_count += 1
            status.last_error = error
            status.last_check = time.time()

    def mark_provider_healthy(self, provider: str):
        """Mark a provider as healthy after successful request."""
        if provider in self._provider_status:
            status = self._provider_status[provider]
            status.is_healthy = True
            status.error_count = 0
            status.last_error = ""
            status.last_check = time.time()

    def is_provider_healthy(self, provider: str) -> bool:
        """Check if a provider is currently healthy."""
        if provider not in self._provider_status:
            return True

        status = self._provider_status[provider]

        # Auto-recover after 5 minutes
        if not status.is_healthy:
            if time.time() - status.last_check > 300:  # 5 minutes
                status.is_healthy = True
                return True

        return status.is_healthy

    def select_model(
        self, task_complexity: TaskComplexity = TaskComplexity.MEDIUM, max_cost: float = None
    ) -> tuple[str, str]:
        """Select the best model for a task.

        Args:
            task_complexity: How complex the task is
            max_cost: Maximum cost per 1M tokens (optional)

        Returns:
            Tuple of (provider, model)
        """
        # Get fallback chain
        chain = self.get_fallback_chain()

        # Filter by health and cost
        for provider, model in chain:
            # Skip unhealthy providers
            if not self.is_provider_healthy(provider):
                continue

            # Check cost constraint
            if max_cost is not None and model in MODEL_PRICING:
                input_cost, output_cost = MODEL_PRICING[model]
                if input_cost > max_cost or output_cost > max_cost:
                    continue

            # For simple tasks, prefer cheaper models
            if task_complexity == TaskComplexity.SIMPLE:
                if model in MODEL_PRICING:
                    input_cost, _ = MODEL_PRICING[model]
                    if input_cost == 0:  # Free model
                        return provider, model

            return provider, model

        # Fallback to primary if nothing else works
        return self.primary_provider, self.primary_model

    def select_cost_effective(self) -> tuple[str, str]:
        """Select the most cost-effective available model."""
        return self.select_model(
            task_complexity=TaskComplexity.SIMPLE,
            max_cost=1.0,  # Max $1 per 1M tokens
        )

    def route_with_fallback(
        self, api_call: Callable[[str, str], dict], provider: str = None, model: str = None
    ) -> dict:
        """Execute an API call with automatic fallback on failure.

        Args:
            api_call: Function that takes (provider, model) and returns response
            provider: Starting provider (optional)
            model: Starting model (optional)

        Returns:
            API response dict
        """
        provider = provider or self.primary_provider
        model = model or self.primary_model

        chain = self.get_fallback_chain(provider)

        # Ensure primary is first
        primary_pair = (provider, model)
        if primary_pair in chain:
            chain.remove(primary_pair)
        chain.insert(0, primary_pair)

        last_error = None

        for try_provider, try_model in chain:
            if not self.is_provider_healthy(try_provider):
                continue

            try:
                result = api_call(try_provider, try_model)
                self.mark_provider_healthy(try_provider)
                return result

            except Exception as e:
                last_error = str(e)
                self.mark_provider_unhealthy(try_provider, last_error)
                continue

        # All providers failed
        raise RuntimeError(f"All providers failed. Last error: {last_error}")


# Global router instance
_router: ModelRouter | None = None


def get_router(primary_provider: str = None, primary_model: str = None) -> ModelRouter:
    """Get or create the global model router."""
    global _router
    if _router is None:
        _router = ModelRouter(
            primary_provider=primary_provider or "claude", primary_model=primary_model
        )
    return _router


def select_model_for_task(complexity: str = "medium", max_cost: float = None) -> tuple[str, str]:
    """Convenience function to select a model for a task.

    Args:
        complexity: "simple", "medium", or "complex"
        max_cost: Maximum cost per 1M tokens

    Returns:
        Tuple of (provider, model)
    """
    complexity_map = {
        "simple": TaskComplexity.SIMPLE,
        "medium": TaskComplexity.MEDIUM,
        "complex": TaskComplexity.COMPLEX,
    }
    task_complexity = complexity_map.get(complexity, TaskComplexity.MEDIUM)
    return get_router().select_model(task_complexity, max_cost)
