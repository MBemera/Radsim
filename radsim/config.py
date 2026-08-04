"""Configuration loader for RadSim Agent."""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .context_budget import (
    DEFAULT_CONTEXT_INPUT_TOKENS,
    DEFAULT_CONTEXT_OUTPUT_RESERVE_TOKENS,
    DEFAULT_CONTEXT_RECOVERY_TOKENS,
    MAX_CONTEXT_SETTING_TOKENS,
)
from .persistence import atomic_write_json
from .pricing import ModelPricing
from .runtime_context import get_runtime_context
from .terminal import is_unsafe_terminal_character

logger = logging.getLogger(__name__)


REASONING_EFFORT_LEVELS = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
DEFAULT_REASONING_EFFORT_OPTIONS = ("low", "medium", "high")
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_OPENROUTER_MODEL = "z-ai/glm-5.2"


@dataclass
class Config:
    """RadSim configuration."""

    provider: str
    api_key: str
    model: str
    auto_confirm: bool = False
    trust_mode: str = "medium"
    verbose: bool = False
    stream: bool = True
    agent_config: dict = field(default_factory=dict)
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    # Rate limiting settings (aggressive loop protection)
    max_api_calls_per_turn: int = 15  # Hard stop after 15 calls without user input
    max_session_input_tokens: int = 0  # 0 = unlimited (set to 500000 for budget limit)
    max_session_output_tokens: int = 0  # 0 = unlimited (set to 100000 for budget limit)
    max_context_input_tokens: int = DEFAULT_CONTEXT_INPUT_TOKENS
    context_output_reserve_tokens: int = DEFAULT_CONTEXT_OUTPUT_RESERVE_TOKENS
    context_recovery_tokens: int = DEFAULT_CONTEXT_RECOVERY_TOKENS
    rate_limit_cooldown_ms: int = 50  # Faster cooldown
    circuit_breaker_threshold: int = 3


# Rate limit tiers - user-selectable API call limits per turn
RATE_LIMIT_TIERS = {
    "light": {"max_calls": 15, "label": "Light (15 calls)", "description": "Conservative - good for simple tasks"},
    "standard": {"max_calls": 30, "label": "Standard (30 calls)", "description": "Balanced - recommended for most work"},
    "heavy": {"max_calls": 75, "label": "Heavy (75 calls)", "description": "For complex multi-step tasks"},
    "intensive": {"max_calls": 100, "label": "Intensive (100 calls)", "description": "For large refactors and deep analysis"},
    "unlimited": {"max_calls": 200, "label": "Maximum (200 calls)", "description": "Maximum throughput - use with caution"},
}

DEFAULT_RATE_LIMIT_TIER = "standard"


# Available models for each provider (Updated Jul 2026)
PROVIDER_MODELS = {
    "claude": [
        ("claude-opus-4-8", "Claude Opus 4.8 (Most capable — recommended)"),
        ("claude-sonnet-4-6", "Claude Sonnet 4.6 (Best speed/intelligence balance)"),
        ("claude-haiku-4-5", "Claude Haiku 4.5 (Fast & cheap)"),
    ],
    "openai": [
        ("gpt-5.4", "GPT-5.4 (Most capable)"),
        ("gpt-5.3-codex", "GPT-5.3 Codex (Agentic coding)"),
        ("gpt-5.2", "GPT-5.2 (Recommended)"),
        ("gpt-5.2-codex", "GPT-5.2 Codex (Cheap)"),
        ("gpt-5-mini", "GPT-5 Mini (Fast & cheap)"),
    ],
    "openrouter": [
        ("z-ai/glm-5.2", "GLM 5.2 (Recommended fallback, 1M context)"),
        ("moonshotai/kimi-k3", "Kimi K3 (Coding and long-horizon agents)"),
        ("anthropic/claude-fable-5", "Claude Fable 5 (Autonomous coding)"),
        ("openai/gpt-5.6-sol-pro", "GPT-5.6 Sol Pro (Deepest reasoning)"),
        ("openai/gpt-5.6-sol", "GPT-5.6 Sol (Flagship)"),
        ("openai/gpt-5.6-terra-pro", "GPT-5.6 Terra Pro (Balanced pro)"),
        ("openai/gpt-5.6-terra", "GPT-5.6 Terra (Balanced)"),
        ("openai/gpt-5.6-luna-pro", "GPT-5.6 Luna Pro (Fast pro)"),
        ("openai/gpt-5.6-luna", "GPT-5.6 Luna (Fast and cost-efficient)"),
        ("minimax/minimax-m3", "MiniMax M3 (Recommended — top usage)"),
        ("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash (Fast & cheapest)"),
        ("anthropic/claude-opus-4.8", "Claude Opus 4.8 via OpenRouter (Most capable)"),
        ("anthropic/claude-sonnet-4.6", "Claude Sonnet 4.6 via OpenRouter"),
        ("moonshotai/kimi-k2.5", "Kimi K2.5 (Capable & cheap)"),
        ("openai/gpt-5.4", "GPT-5.4 via OpenRouter"),
        ("openai/gpt-5.3-codex", "GPT-5.3 Codex via OpenRouter"),
        ("z-ai/glm-4.7", "GLM 4.7 (Capable)"),
    ],
}

# Default model for each provider (Updated Jul 2026)
DEFAULT_MODELS = {
    "openrouter": DEFAULT_OPENROUTER_MODEL,
    "openai": "gpt-5.4",
    "claude": "claude-opus-4-8",
}

PROVIDER_URLS = {
    "openrouter": "https://openrouter.ai/keys",
    "openai": "https://platform.openai.com/api-keys",
    "claude": "https://console.anthropic.com/settings/keys",
}

# Provider-specific environment variable names
PROVIDER_ENV_VARS = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}

# Fallback models for automatic failover (in priority order)
FALLBACK_MODELS = {
    "claude": [
        "claude-opus-4-8",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ],
    "openai": [
        "gpt-5.4",
        "gpt-5.3-codex",
        "gpt-5.2",
        "gpt-5.2-codex",
        "gpt-5-mini",
    ],
    "openrouter": [
        DEFAULT_OPENROUTER_MODEL,
        "moonshotai/kimi-k3",
        "openai/gpt-5.6-luna",
        "minimax/minimax-m3",
        "deepseek/deepseek-v4-flash",
        "moonshotai/kimi-k2.5",
        "anthropic/claude-sonnet-4.6",
        "anthropic/claude-opus-4.8",
        "openai/gpt-5.4",
        "openai/gpt-5.3-codex",
        "z-ai/glm-4.7",
    ],
}

# Static estimates are provider and billing-mode scoped. OpenRouter catalogue
# prices take precedence at runtime; these values are labelled stale fallbacks.
PricingKey = tuple[str, str, str]


def _static_pricing(
    provider: str,
    model: str,
    input_price: str,
    output_price: str,
    *,
    cache_read_price: str | None = None,
    fetched_at: str | None = None,
) -> ModelPricing:
    return ModelPricing(
        provider=provider,
        billing_mode="routing" if provider == "openrouter" else "api",
        model=model,
        input_per_million_usd=input_price,
        output_per_million_usd=output_price,
        cache_read_per_million_usd=cache_read_price,
        source="static-fallback",
        fetched_at=fetched_at,
        stale=True,
    )


_STATIC_PRICE_ROWS = (
    ("claude", "claude-opus-4-8", "5.00", "25.00"),
    ("claude", "claude-opus-4-6", "5.00", "25.00"),
    ("claude", "claude-sonnet-4-6", "3.00", "15.00"),
    ("claude", "claude-sonnet-4-5", "3.00", "15.00"),
    ("claude", "claude-haiku-4-5", "1.00", "5.00"),
    ("openai", "gpt-5.4", "5.00", "15.00"),
    ("openai", "gpt-5.3-codex", "5.00", "15.00"),
    ("openai", "gpt-5.2", "2.50", "10.00"),
    ("openai", "gpt-5.2-codex", "2.50", "10.00"),
    ("openai", "gpt-5-mini", "1.00", "4.00"),
    ("openrouter", "minimax/minimax-m3", "0.30", "1.20"),
    ("openrouter", "deepseek/deepseek-v4-flash", "0.09", "0.18"),
    ("openrouter", "moonshotai/kimi-k3", "3.00", "15.00"),
    ("openrouter", "moonshotai/kimi-k2.5", "0.38", "2.02"),
    ("openrouter", "anthropic/claude-fable-5", "10.00", "50.00"),
    ("openrouter", "anthropic/claude-opus-4.8", "5.00", "25.00"),
    ("openrouter", "anthropic/claude-opus-4.6", "5.00", "25.00"),
    ("openrouter", "anthropic/claude-sonnet-4.6", "3.00", "15.00"),
    ("openrouter", "anthropic/claude-haiku-4.5", "1.00", "5.00"),
    ("openrouter", "openai/gpt-5.4", "2.50", "15.00"),
    ("openrouter", "openai/gpt-5.6-sol-pro", "5.00", "30.00"),
    ("openrouter", "openai/gpt-5.6-sol", "5.00", "30.00"),
    ("openrouter", "openai/gpt-5.6-terra-pro", "2.50", "15.00"),
    ("openrouter", "openai/gpt-5.6-terra", "2.50", "15.00"),
    ("openrouter", "openai/gpt-5.6-luna-pro", "1.00", "6.00"),
    ("openrouter", "openai/gpt-5.6-luna", "1.00", "6.00"),
    ("openrouter", "openai/gpt-5.3-codex", "1.75", "14.00"),
    ("openrouter", "openai/gpt-5.2-codex", "1.75", "14.00"),
    ("openrouter", "minimax/minimax-m2.1", "0.30", "1.20"),
    ("openrouter", "z-ai/glm-4.7", "0.40", "1.75"),
)

MODEL_PRICING: dict[PricingKey, ModelPricing] = {
    (provider, pricing.billing_mode, model): pricing
    for provider, model, input_price, output_price in _STATIC_PRICE_ROWS
    for pricing in (_static_pricing(provider, model, input_price, output_price),)
}
MODEL_PRICING[("openrouter", "routing", "z-ai/glm-5.2")] = _static_pricing(
    "openrouter",
    "z-ai/glm-5.2",
    "0.76",
    "2.42",
    cache_read_price="0.14",
    fetched_at="2026-08-04T00:00:00Z",
)


def get_static_model_pricing(
    model: str,
    provider: str | None = None,
    billing_mode: str | None = None,
) -> ModelPricing | None:
    """Return one static provider/billing estimate without network access."""
    matches = [
        pricing
        for (price_provider, price_mode, price_model), pricing in MODEL_PRICING.items()
        if price_model == model
        and (provider is None or provider == price_provider)
        and (billing_mode is None or billing_mode == price_mode)
    ]
    return matches[0] if len(matches) == 1 else None


def get_model_pricing(
    model: str,
    provider: str | None = None,
    billing_mode: str | None = None,
    *,
    allow_network: bool = False,
) -> ModelPricing | None:
    """Resolve one validated snapshot, preferring OpenRouter's catalogue."""
    resolved_provider = provider or ("openrouter" if "/" in model else None)
    resolved_mode = billing_mode or ("routing" if resolved_provider == "openrouter" else "api")
    if resolved_provider == "openrouter":
        catalogue_pricing = _get_openrouter_pricing(model, allow_network)
        if catalogue_pricing is not None:
            return catalogue_pricing
    return get_static_model_pricing(model, resolved_provider, resolved_mode)


def _get_openrouter_pricing(model: str, allow_network: bool) -> ModelPricing | None:
    try:
        from .openrouter_models import find_model_with_status

        entry, status = find_model_with_status(model, allow_network=allow_network)
        if not entry or status.source == "static-fallback":
            return None
        return ModelPricing.from_per_token(
            provider="openrouter",
            billing_mode="routing",
            model=model,
            input_price=entry.get("input_price"),
            output_price=entry.get("output_price"),
            cache_read_price=entry.get("cache_read_price"),
            cache_write_price=entry.get("cache_write_price"),
            source=status.source,
            fetched_at=status.fetched_at,
            stale=status.stale,
        )
    except (OSError, TypeError, ValueError):
        return None

# Context window limits per model (in tokens) - Updated Jul 2026
CONTEXT_LIMITS = {
    # Claude Series
    "claude-opus-4-8": 1000000,
    "claude-opus-4-6": 1000000,
    "claude-sonnet-4-6": 1000000,
    "claude-sonnet-4-5": 200000,
    "claude-haiku-4-5": 200000,
    # OpenAI GPT-5 Series
    "gpt-5.4": 1050000,
    "gpt-5.3-codex": 400000,
    "gpt-5.2": 256000,
    "gpt-5.2-codex": 256000,
    "gpt-5-mini": 128000,
    # OpenRouter models (live context windows, verified Jul 2026)
    "minimax/minimax-m3": 1048576,
    "deepseek/deepseek-v4-flash": 1048576,
    "moonshotai/kimi-k3": 1048576,
    "moonshotai/kimi-k2.5": 262144,
    "anthropic/claude-fable-5": 1000000,
    "anthropic/claude-opus-4.8": 1000000,
    "anthropic/claude-opus-4.6": 1000000,
    "anthropic/claude-sonnet-4.6": 1000000,
    "anthropic/claude-haiku-4.5": 200000,
    "openai/gpt-5.4": 1050000,
    "openai/gpt-5.6-sol-pro": 1050000,
    "openai/gpt-5.6-sol": 1050000,
    "openai/gpt-5.6-terra-pro": 1050000,
    "openai/gpt-5.6-terra": 1050000,
    "openai/gpt-5.6-luna-pro": 1050000,
    "openai/gpt-5.6-luna": 1050000,
    "openai/gpt-5.3-codex": 400000,
    "openai/gpt-5.2-codex": 400000,
    "z-ai/glm-5.2": 1048576,
    "z-ai/glm-4.7": 202752,
}


def get_context_limit(model, default=100000):
    """Return the context window for a model in tokens.

    Checks the static table first, then the OpenRouter catalogue cache,
    then falls back to a conservative default.
    """
    if model in CONTEXT_LIMITS:
        return CONTEXT_LIMITS[model]
    try:
        from .openrouter_models import find_model

        entry = find_model(model, allow_network=False)
    except Exception:
        return default
    if entry and entry.get("context_length"):
        return entry["context_length"]
    return default

# Model-specific capabilities and settings per provider documentation
# RadSim Principle: Explicit Configuration Over Implicit Defaults
MODEL_CAPABILITIES = {
    # Claude Series
    "claude-opus-4-6": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_extended_thinking": True,
        "supports_vision": True,
        "max_output_tokens": 16384,
    },
    "claude-sonnet-4-5": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_extended_thinking": True,
        "supports_vision": True,
        "max_output_tokens": 8192,
    },
    "claude-haiku-4-5": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_extended_thinking": False,
        "supports_vision": True,
        "max_output_tokens": 4096,
    },
    # GPT-5 Series - Multimodal with O-series reasoning
    "gpt-5.4": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": True,
        "max_output_tokens": 128000,
    },
    "gpt-5.3-codex": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": False,
        "max_output_tokens": 16384,
    },
    "gpt-5.2": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": True,
        "max_output_tokens": 16384,
    },
    "gpt-5.2-codex": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": False,
        "max_output_tokens": 16384,
    },
    "gpt-5-mini": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": True,
        "max_output_tokens": 8192,
    },
    # OpenRouter models (Claude/OpenAI via OpenRouter)
    "anthropic/claude-opus-4.6": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_extended_thinking": True,
        "supports_vision": True,
        "max_output_tokens": 16384,
    },
    "anthropic/claude-sonnet-4.6": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_extended_thinking": True,
        "supports_vision": True,
        "max_output_tokens": 8192,
    },
    "openai/gpt-5.4": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": True,
        "max_output_tokens": 128000,
    },
    "openai/gpt-5.3-codex": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": False,
        "max_output_tokens": 16384,
    },
    "openai/gpt-5.2-codex": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": False,
        "max_output_tokens": 16384,
    },
    "z-ai/glm-5.2": {
        "supports_tools": True,
        "supports_reasoning": True,
        "reasoning_efforts": ("high", "xhigh"),
        "default_reasoning_effort": "high",
    },
    "moonshotai/kimi-k3": {
        "supports_tools": True,
        "supports_reasoning": True,
        "reasoning_efforts": ("max",),
        "default_reasoning_effort": "max",
        "reasoning_mandatory": True,
    },
    "anthropic/claude-fable-5": {
        "supports_tools": True,
        "supports_reasoning": True,
        "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
        "default_reasoning_effort": "medium",
        "reasoning_mandatory": True,
    },
    "openai/gpt-5.6-sol-pro": {
        "supports_tools": True,
        "supports_reasoning": True,
        "reasoning_efforts": ("none", "low", "medium", "high", "xhigh", "max"),
        "default_reasoning_effort": "medium",
    },
    "openai/gpt-5.6-sol": {
        "supports_tools": True,
        "supports_reasoning": True,
        "reasoning_efforts": ("none", "low", "medium", "high", "xhigh", "max"),
        "default_reasoning_effort": "medium",
    },
    "openai/gpt-5.6-terra-pro": {
        "supports_tools": True,
        "supports_reasoning": True,
        "reasoning_efforts": ("none", "low", "medium", "high", "xhigh", "max"),
        "default_reasoning_effort": "medium",
    },
    "openai/gpt-5.6-terra": {
        "supports_tools": True,
        "supports_reasoning": True,
        "reasoning_efforts": ("none", "low", "medium", "high", "xhigh", "max"),
        "default_reasoning_effort": "medium",
    },
    "openai/gpt-5.6-luna-pro": {
        "supports_tools": True,
        "supports_reasoning": True,
        "reasoning_efforts": ("none", "low", "medium", "high", "xhigh", "max"),
        "default_reasoning_effort": "medium",
    },
    "openai/gpt-5.6-luna": {
        "supports_tools": True,
        "supports_reasoning": True,
        "reasoning_efforts": ("none", "low", "medium", "high", "xhigh", "max"),
        "default_reasoning_effort": "medium",
    },
}


CONFIG_DIR = Path.home() / ".radsim"
ENV_FILE = CONFIG_DIR / ".env"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
MEMORY_DIR = CONFIG_DIR / "memory"
SCHEDULES_FILE = CONFIG_DIR / "schedules.json"
PACKAGE_DIR = Path(__file__).parent  # The radsim source directory
CUSTOM_PROMPT_FILE = CONFIG_DIR / "custom_prompt.txt"
PROJECT_ENV_FILE = PACKAGE_DIR.parent / ".env"


def _project_env_trusted():
    """Return True only when the user explicitly trusts project-local .env.

    Off by default so repository content cannot redirect the provider/model
    or inject credentials through a checked-in .env (R-08). Opt in with the
    env var ``RADSIM_TRUST_PROJECT_ENV=1``, the settings.json key
    ``trust_project_env``, or the ``trust_project_env`` memory preference.
    """
    flag = os.getenv("RADSIM_TRUST_PROJECT_ENV", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    try:
        if load_settings_file().get("trust_project_env"):
            return True
    except Exception:
        logger.debug("trust_project_env settings lookup failed", exc_info=True)
    try:
        memory = get_runtime_context().get_memory()
        if memory.global_mem.get_preference("trust_project_env"):
            return True
    except Exception:
        logger.debug("trust_project_env preference lookup failed", exc_info=True)
    return False


def _log_skipped_project_env():
    """Note (at debug level) when an untrusted project .env is ignored."""
    try:
        if (Path.cwd() / ".env").exists() or PROJECT_ENV_FILE.exists():
            logger.debug(
                "Ignoring project-local .env for provider config (untrusted). "
                "Set RADSIM_TRUST_PROJECT_ENV=1 to opt in."
            )
    except OSError:
        pass


def load_env_file():
    """Load provider config from .env files with deterministic precedence.

    Sources are consulted in this fixed order, and the first value seen for a
    given key wins:

    1. An explicitly configured preferred env file (``RADSIM_ENV_FILE``,
       ``settings.json``, or the ``preferred_env_file`` memory preference).
    2. Project-local ``.env`` (current directory, then the source checkout)
       — **only** when the project is explicitly trusted
       (:func:`_project_env_trusted`). Ignored by default so untrusted
       repository content cannot select a provider or inject credentials.
    3. The global ``~/.radsim/.env``, which is always trusted.

    Supports both RADSIM_API_KEY and provider-specific keys.
    """
    result = {
        "api_key": None,
        "provider": None,
        "provider_source": None,
        "model": None,
        "model_source": None,
        "keys": {},
    }

    env_files_to_check = []

    preferred_env_file = _get_preferred_env_file()
    if preferred_env_file is not None and preferred_env_file.exists():
        env_files_to_check.append(preferred_env_file)

    if _project_env_trusted():
        try:
            cwd_env_file = Path.cwd() / ".env"
        except (FileNotFoundError, OSError):
            cwd_env_file = None
        for candidate in (cwd_env_file, PROJECT_ENV_FILE):
            if candidate is not None and candidate.exists() and candidate not in env_files_to_check:
                env_files_to_check.append(candidate)
    else:
        _log_skipped_project_env()

    if ENV_FILE.exists() and ENV_FILE not in env_files_to_check:
        env_files_to_check.append(ENV_FILE)

    if not env_files_to_check:
        return result

    # Process global config only
    for env_file in env_files_to_check:
        try:
            content = env_file.read_text()
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]

                # Only set if not already set (priority to earlier files)
                if key == "RADSIM_API_KEY" and not result["api_key"]:
                    result["api_key"] = value
                elif key == "RADSIM_PROVIDER" and not result["provider"]:
                    result["provider"] = value
                    result["provider_source"] = (
                        "global" if env_file == ENV_FILE else "project"
                    )
                elif key == "RADSIM_MODEL" and not result["model"]:
                    result["model"] = value
                    result["model_source"] = (
                        "global" if env_file == ENV_FILE else "project"
                    )
                # Also capture provider-specific API keys and access code
                elif key in (
                    "ANTHROPIC_API_KEY",
                    "OPENAI_API_KEY",
                    "OPENROUTER_API_KEY",
                    "RADSIM_ACCESS_CODE",
                    "TELEGRAM_BOT_TOKEN",
                    "TELEGRAM_CHAT_ID",
                ):
                    if key not in result["keys"]:
                        result["keys"][key] = value
        except Exception:
            logger.debug(f"Failed to parse env file: {env_file}")

    return result


def _get_preferred_env_file() -> Path | None:
    """Return a user-configured env file path when one is available."""
    env_file_path = os.getenv("RADSIM_ENV_FILE")
    if not env_file_path:
        settings = load_settings_file()
        env_file_path = settings.get("env_file")
    if not env_file_path:
        try:
            memory = get_runtime_context().get_memory()
            env_file_path = memory.global_mem.get_preference("preferred_env_file")
        except Exception:
            logger.debug("Preferred env file lookup failed", exc_info=True)
            return None

    if not env_file_path:
        return None

    return Path(env_file_path).expanduser()


def load_settings_file():
    """Load config from settings.json file."""
    if not SETTINGS_FILE.exists():
        return {}

    try:
        return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        logger.debug(f"Failed to parse settings file: {SETTINGS_FILE}")
        return {}


def is_supported_provider_model(provider, model):
    """Check a provider/model pair against the shipped catalogue.

    Shared by the primary and subagent selection paths so both reject a
    model that was removed from the catalogue instead of quietly running
    something the user did not choose.

    Returns:
        (supported: bool, reason: str)
    """
    if not provider or not isinstance(provider, str):
        return False, "No provider selected"
    if not model or not isinstance(model, str):
        return False, "No model selected"

    catalogue = PROVIDER_MODELS.get(provider)
    if catalogue is None:
        return False, f"Unknown provider '{provider}'"

    if model in {model_id for model_id, _description in catalogue}:
        return True, ""

    return False, f"Model '{model}' is not available for provider '{provider}'"


def get_provider_api_key(provider):
    """Resolve one provider's API key from the environment or credential store.

    Reads at call time and never caches: credentials belong in the existing
    store, not copied into other config files.
    """
    env_var = PROVIDER_ENV_VARS.get(provider)
    if not env_var:
        return None

    key = os.getenv(env_var)
    if key:
        return key

    return load_env_file().get("keys", {}).get(env_var)


def save_config(api_key, provider, model):
    """Save config to .env file with secure permissions.

    Saves provider, model, AND API key to ~/.radsim/.env
    Preserves existing API keys from other providers.
    File is chmod 600 (owner read/write only) for security.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Get provider-specific env var name
    env_var = PROVIDER_ENV_VARS.get(provider, "RADSIM_API_KEY")

    # Load existing config to preserve keys and, when the caller passes no
    # model (e.g. /login), the previously-saved model. Never persist a
    # falsy/None model — doing so wrote the literal RADSIM_MODEL="None"
    # and corrupted the user's model preference.
    existing_config = load_env_file()
    existing_keys = existing_config.get("keys", {})

    if not model:
        model = load_last_model_selection(provider)
    if not model:
        existing_model = existing_config.get("model")
        if existing_model and model_belongs_to_provider(existing_model, provider):
            model = existing_model
    if not model:
        model = DEFAULT_MODELS.get(provider, "")

    # Update with the new key
    existing_keys[env_var] = api_key

    # Build content preserving all API keys
    lines = [
        "# RadSim Configuration",
        "# This file is chmod 600 (secure)",
        "",
        f'RADSIM_PROVIDER="{provider}"',
        f'RADSIM_MODEL="{model}"',
        "",
        "# API Keys (preserved across provider switches)",
    ]

    # Add all API keys
    for key_name, key_value in existing_keys.items():
        if key_value and not key_value.lower().startswith("paste_your"):
            lines.append(f'{key_name}="{key_value}"')

    lines.append("")  # Trailing newline

    ENV_FILE.write_text("\n".join(lines))
    ENV_FILE.chmod(0o600)  # Secure: owner read/write only
    save_last_model_selection(provider, model)


def save_last_model_selection(provider: str, model: str) -> None:
    """Persist the most recently selected provider and model without secrets."""
    if not _is_valid_model_selection(provider, model):
        raise ValueError("Provider and model selection is invalid")

    settings = load_settings_file()
    settings["last_provider"] = provider
    settings["last_model"] = model
    atomic_write_json(SETTINGS_FILE, settings, secure=True)


def load_last_model_selection(provider: str) -> str | None:
    """Return the last model selected for the requested provider."""
    settings = load_settings_file()
    if settings.get("last_provider") != provider:
        return None

    model = settings.get("last_model")
    if not _is_valid_model_selection(provider, model):
        return None
    return model


def _is_valid_model_selection(provider: str, model) -> bool:
    """Return whether a provider/model pair is safe to persist and display."""
    if provider not in DEFAULT_MODELS or not isinstance(model, str):
        return False
    if not model or model != model.strip() or len(model) > 256:
        return False
    if any(is_unsafe_terminal_character(character) for character in model):
        return False
    return model_belongs_to_provider(model, provider)


def save_reasoning_effort(effort: str) -> None:
    """Persist global reasoning effort to settings.json."""
    if effort not in REASONING_EFFORT_LEVELS:
        raise ValueError(
            f"Invalid reasoning_effort: {effort}. "
            f"Expected one of {REASONING_EFFORT_LEVELS}."
        )
    settings = load_settings_file()
    settings["reasoning_effort"] = effort
    atomic_write_json(SETTINGS_FILE, settings, secure=True)


def load_reasoning_effort() -> str:
    """Read global reasoning effort from settings.json, default to medium."""
    effort = load_settings_file().get("reasoning_effort", DEFAULT_REASONING_EFFORT)
    if effort not in REASONING_EFFORT_LEVELS:
        return DEFAULT_REASONING_EFFORT
    return effort


def save_rate_limit_tier(tier_name):
    """Save rate limit tier to settings.json.

    Args:
        tier_name: One of the keys from RATE_LIMIT_TIERS.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    settings = load_settings_file()
    settings["rate_limit_tier"] = tier_name
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


def _format_model_label(entry: dict) -> str:
    """Build a TUI-friendly label from a normalized OpenRouter model entry."""
    label = entry.get("name") or entry["id"]
    suffix_parts = []
    if entry.get("supports_reasoning"):
        suffix_parts.append("reasoning")
    ctx = entry.get("context_length") or 0
    if ctx:
        suffix_parts.append(f"{ctx // 1000}k ctx")
    if suffix_parts:
        return f"{label} ({', '.join(suffix_parts)})"
    return label


def _build_openrouter_choices(top_only: bool = True) -> list[tuple[str, str]]:
    """Return (model_id, label) pairs for the OpenRouter catalogue.

    When top_only is True, returns the curated short list from
    PROVIDER_MODELS enriched with live capability metadata when available.
    Otherwise returns the full live catalogue.
    """
    from .openrouter_models import find_model, get_openrouter_models

    if top_only:
        choices = []
        for model_id, fallback_label in PROVIDER_MODELS["openrouter"]:
            entry = find_model(model_id)
            if entry:
                choices.append((model_id, _format_model_label(entry)))
            else:
                choices.append((model_id, fallback_label))
        return choices

    catalogue = get_openrouter_models()
    if not catalogue:
        return PROVIDER_MODELS["openrouter"]
    return [(entry["id"], _format_model_label(entry)) for entry in catalogue]


def _select_openrouter_model() -> str | None:
    """Two-level OpenRouter picker: curated top list with an opt-in full browse."""
    top = _build_openrouter_choices(top_only=True)
    expand_index = len(top) + 1

    print()
    print("  Recommended OpenRouter models:")
    for i, (_, label) in enumerate(top, 1):
        print(f"    {i}. {label}")
    print(f"    {expand_index}. Show all models…")
    print()

    try:
        choice = input(f"  Enter 1-{expand_index} [1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        return None

    try:
        idx = int(choice) - 1
    except ValueError:
        return top[0][0]

    if idx == len(top):
        return _select_from_full_openrouter()
    if 0 <= idx < len(top):
        return top[idx][0]
    return top[0][0]


def _vendor_of(model_id: str) -> str:
    """Extract the vendor prefix from an OpenRouter model id (e.g. anthropic/claude-…)."""
    if "/" in model_id:
        return model_id.split("/", 1)[0]
    return "other"


def _group_by_vendor(choices: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    for model_id, label in choices:
        grouped.setdefault(_vendor_of(model_id), []).append((model_id, label))
    return grouped


def _select_from_full_openrouter() -> str | None:
    """Browse the full OpenRouter catalogue via a vendor menu or substring search."""
    full = _build_openrouter_choices(top_only=False)
    if not full:
        print("  warning: full catalogue unavailable, using top list.")
        top = _build_openrouter_choices(top_only=True)
        return top[0][0] if top else None

    grouped = _group_by_vendor(full)
    vendors = sorted(grouped.keys(), key=lambda v: (-len(grouped[v]), v))

    while True:
        print()
        print(f"  Browse {len(full)} models by vendor:")
        for i, vendor in enumerate(vendors, 1):
            print(f"    {i}. {vendor} ({len(grouped[vendor])})")
        search_index = len(vendors) + 1
        back_index = len(vendors) + 2
        print(f"    {search_index}. Search by name…")
        print(f"    {back_index}. Back")
        print()

        try:
            choice = input(f"  Enter 1-{back_index}: ").strip()
        except (KeyboardInterrupt, EOFError):
            return None

        try:
            idx = int(choice) - 1
        except ValueError:
            continue

        if idx == back_index - 1:
            return None
        if idx == search_index - 1:
            picked = _search_openrouter_models(full)
            if picked:
                return picked
            continue
        if 0 <= idx < len(vendors):
            picked = _select_from_vendor(vendors[idx], grouped[vendors[idx]])
            if picked:
                return picked
            continue


def _select_from_vendor(vendor: str, models: list[tuple[str, str]]) -> str | None:
    print()
    print(f"  {vendor} ({len(models)} models):")
    for i, (_, label) in enumerate(models, 1):
        print(f"    {i}. {label}")
    back_index = len(models) + 1
    print(f"    {back_index}. Back")
    print()

    try:
        choice = input(f"  Enter 1-{back_index}: ").strip()
    except (KeyboardInterrupt, EOFError):
        return None

    try:
        idx = int(choice) - 1
    except ValueError:
        return None

    if idx == len(models):
        return None
    if 0 <= idx < len(models):
        return models[idx][0]
    return None


def _search_openrouter_models(full: list[tuple[str, str]]) -> str | None:
    print()
    try:
        query = input("  Search (substring of name or id): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return None
    if not query:
        return None

    filtered = [
        (model_id, label)
        for model_id, label in full
        if query in model_id.lower() or query in label.lower()
    ]
    if not filtered:
        print(f"  No matches for '{query}'.")
        return None

    print()
    print(f"  Matches ({len(filtered)}):")
    for i, (_, label) in enumerate(filtered, 1):
        print(f"    {i}. {label}")
    back_index = len(filtered) + 1
    print(f"    {back_index}. Back")
    print()

    try:
        choice = input(f"  Enter 1-{back_index}: ").strip()
    except (KeyboardInterrupt, EOFError):
        return None

    try:
        idx = int(choice) - 1
    except ValueError:
        return None

    if idx == len(filtered):
        return None
    if 0 <= idx < len(filtered):
        return filtered[idx][0]
    return None


def get_reasoning_effort_options(provider: str, model: str) -> tuple[str, ...]:
    """Return the effort levels accepted by the selected model."""
    capabilities = MODEL_CAPABILITIES.get(model, {})
    if provider == "openrouter":
        from .openrouter_models import (
            get_model_reasoning_efforts,
            model_supports_reasoning,
        )

        live_efforts = get_model_reasoning_efforts(model)
        if live_efforts:
            return live_efforts
    if capabilities.get("supports_reasoning"):
        return tuple(capabilities.get("reasoning_efforts", DEFAULT_REASONING_EFFORT_OPTIONS))
    if provider == "openrouter" and model_supports_reasoning(model):
        return DEFAULT_REASONING_EFFORT_OPTIONS
    return ()


def resolve_reasoning_effort(provider: str, model: str, effort: str) -> str:
    """Map a saved effort to one supported by the selected model."""
    options = get_reasoning_effort_options(provider, model)
    if not options or effort in options:
        return effort
    capabilities = MODEL_CAPABILITIES.get(model, {})
    default_effort = capabilities.get("default_reasoning_effort")
    if provider == "openrouter":
        from .openrouter_models import get_model_default_reasoning_effort

        default_effort = get_model_default_reasoning_effort(model) or default_effort
    return default_effort if default_effort in options else options[0]


def _maybe_prompt_reasoning_effort(provider: str, model: str) -> None:
    """Prompt only with reasoning levels supported by the selected model."""
    options = get_reasoning_effort_options(provider, model)
    if not options:
        return
    if len(options) == 1:
        effort = options[0]
        print(f"\n  This model requires reasoning effort '{effort}'.")
    else:
        default_effort = resolve_reasoning_effort(provider, model, DEFAULT_REASONING_EFFORT)
        default_choice = str(options.index(default_effort) + 1)
        print("\n  This model supports reasoning. Choose effort level:")
        for index, option in enumerate(options, 1):
            print(f"    {index}. {option}")
        try:
            choice = input(
                f"  Enter 1-{len(options)} [{default_choice}]: "
            ).strip() or default_choice
        except (KeyboardInterrupt, EOFError):
            return
        try:
            effort = options[int(choice) - 1]
        except (ValueError, IndexError):
            effort = default_effort
    save_reasoning_effort(effort)
    print(f"  ok Reasoning effort set to '{effort}'.")


def setup_config(first_time=True):
    """Prompt user to configure RadSim via .env file.

    Security: Never ask for API keys directly in conversation.
    """
    print()
    if first_time:
        print("  ╭─────────────────────────────────────╮")
        print("  │      RadSim - First Time Setup      │")
        print("  ╰─────────────────────────────────────╯")
        print()
        print("  [api key] For security, API keys must be set in the .env file.")
        print()
        print("  Edit your .env file:")
        print("    Local:  ./.env")
        print(f"    Global: {ENV_FILE}")
        print()
        print("  Add your API key for your chosen provider:")
        print("    OPENROUTER_API_KEY   - https://openrouter.ai/keys")
        print("    OPENAI_API_KEY       - https://platform.openai.com/api-keys")
        print("    ANTHROPIC_API_KEY    - https://console.anthropic.com/settings/keys")
        print()
        print("  Then run 'radsim' again.")
        print()
    else:
        print("  ╭─────────────────────────────────────╮")
        print("  │        RadSim - Configuration       │")
        print("  ╰─────────────────────────────────────╯")
    print()
    print("  Select your AI provider:")
    print("    1. OpenRouter (recommended — free models available)")
    print("    2. OpenAI (GPT-5)")
    print("    3. Claude (Anthropic)")
    print()

    try:
        choice = input("  Enter 1-3: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        return None, None, None

    provider_map = {
        "1": "openrouter",
        "2": "openai",
        "3": "claude",
    }
    provider = provider_map.get(choice)

    if not provider:
        print("  Invalid choice.")
        return None, None, None

    # Select model — OpenRouter uses a two-level dynamic picker, others a static list
    if provider == "openrouter":
        model = _select_openrouter_model()
        if not model:
            print("\n  Setup cancelled.")
            return None, None, None
    else:
        print()
        print("  Select model:")
        models = PROVIDER_MODELS[provider]
        for i, (_, model_name) in enumerate(models, 1):
            print(f"    {i}. {model_name}")
        print()

        try:
            model_choice = input(f"  Enter 1-{len(models)} [1]: ").strip() or "1"
        except (KeyboardInterrupt, EOFError):
            print("\n  Setup cancelled.")
            return None, None, None

        try:
            model_index = int(model_choice) - 1
            if 0 <= model_index < len(models):
                model = models[model_index][0]
            else:
                model = models[0][0]
        except ValueError:
            model = models[0][0]

    _maybe_prompt_reasoning_effort(provider, model)

    env_var_name = PROVIDER_ENV_VARS.get(provider, "RADSIM_API_KEY")

    # Standard API key flow
    # Check environment first, then .env file
    existing_key = os.getenv(env_var_name)
    if not existing_key:
        env_config = load_env_file()
        existing_key = env_config.get("keys", {}).get(env_var_name)

    if existing_key and not existing_key.startswith("PASTE_YOUR"):
        print()
        print(f"  ok Found {env_var_name} configured.")
        api_key = existing_key
    else:
        print()
        print(f"  warning: No API key found for {provider}.")
        print()
        print("  [api key] For security, please edit your .env file directly:")
        print(f"     ./.env  OR  {ENV_FILE}")
        print()
        print(f'     Add: {env_var_name}="your-api-key"')
        print()
        print(f"     Get key from: {PROVIDER_URLS[provider]}")
        print()
        print("  Then run 'radsim' again.")
        return None, None, None

    # Save provider and model preferences
    save_config(api_key, provider, model)
    print()
    print(f"  ok Preferences saved to {ENV_FILE}")
    print()

    return api_key, provider, model


def model_belongs_to_provider(model: str, provider: str) -> bool:
    """Check whether a model ID is listed under a provider's catalog.

    Unknown models (custom IDs) are allowed for any provider — this
    only rejects models that are explicitly listed under a DIFFERENT
    provider, which happens when the provider is switched but a stale
    RADSIM_MODEL is still saved.
    """
    known_models = {model_id for model_id, _ in PROVIDER_MODELS.get(provider, [])}
    if model in known_models:
        return True

    other_provider_models = {
        model_id
        for other_provider, models in PROVIDER_MODELS.items()
        if other_provider != provider
        for model_id, _ in models
    }
    return model not in other_provider_models


def load_config(
    provider_override=None,
    api_key_override=None,
    model_override=None,
    auto_confirm=False,
    verbose=False,
    stream=True,
):
    """Load configuration from environment or overrides."""
    # Load from env files and settings.json
    env_config = load_env_file()
    settings_config = load_settings_file()

    agent_config = settings_config.get("agent_config", {})

    project_provider = (
        env_config["provider"]
        if env_config.get("provider_source") == "project"
        else None
    )
    global_provider = (
        env_config["provider"]
        if env_config.get("provider_source") == "global"
        else None
    )
    last_provider = settings_config.get("last_provider")
    if last_provider not in DEFAULT_MODELS:
        last_provider = None

    # Explicit project/process choices win. Otherwise reuse the last selection.
    provider = (
        provider_override
        or os.getenv("RADSIM_PROVIDER")
        or project_provider
        or last_provider
        or global_provider
        or settings_config.get("default_provider")
        or "openrouter"
    )

    # Determine API key
    # Priority: 1) CLI override, 2) env files (provider-specific), 3) env files (RADSIM_API_KEY),
    # 4) System env var
    api_key = api_key_override
    provider_env_var = PROVIDER_ENV_VARS.get(provider)

    def is_placeholder_key(key):
        """Check if key is a placeholder, not a real API key."""
        if not key:
            return True
        key_lower = key.lower().strip()
        return (
            key_lower.startswith("paste_your")
            or key_lower.startswith("your-")
            or key_lower == ""
            or "placeholder" in key_lower
        )

    if not api_key:
        # 1. Check .env file for provider-specific key (SECURE - preferred)
        if provider_env_var and provider_env_var in env_config.get("keys", {}):
            candidate = env_config["keys"][provider_env_var]
            if not is_placeholder_key(candidate):
                api_key = candidate

    if not api_key:
        # 2. Check .env file for RADSIM_API_KEY
        api_key = env_config.get("api_key")

    if not api_key:
        # 3. Fall back to system environment variable
        if provider_env_var:
            api_key = os.getenv(provider_env_var)

    if not api_key:
        # 4. Legacy fallback
        api_key = os.getenv("RADSIM_API_KEY")

    project_model = (
        env_config.get("model")
        if env_config.get("model_source") == "project"
        else None
    )
    global_model = (
        env_config.get("model")
        if env_config.get("model_source") == "global"
        else None
    )
    last_model = load_last_model_selection(provider)

    # Explicit project/process values win. Otherwise reuse the last selection.
    model = (
        model_override
        or os.getenv("RADSIM_MODEL")
        or project_model
        or last_model
        or global_model
        or settings_config.get("default_model")
    )

    # A saved model from a previously selected provider must not leak into
    # the new provider (e.g. --provider openai with a saved Claude model).
    if model and not model_override and not model_belongs_to_provider(model, provider):
        logger.debug(
            f"Saved model '{model}' belongs to another provider; "
            f"using default for '{provider}'"
        )
        model = None

    # Global flags
    final_verbose = verbose or settings_config.get("verbose", False)

    # If stream is passed as False (specifically disabled), respect that.
    final_stream = stream
    if stream and "stream" in settings_config:
        final_stream = settings_config["stream"]

    if not api_key:
        # Prompt user for setup
        api_key, selected_provider, selected_model = setup_config()
        if not api_key:
            raise ValueError("API key is required to use RadSim.")
        if selected_provider:
            provider = selected_provider
        if selected_model:
            model = selected_model

    if provider not in DEFAULT_MODELS:
        raise ValueError(
            f"Unknown provider: {provider}\nSupported: {', '.join(DEFAULT_MODELS.keys())}"
        )

    # Use default model if none specified
    if not model:
        model = DEFAULT_MODELS[provider]

    # Load rate limit tier from settings
    rate_limit_tier = settings_config.get("rate_limit_tier", DEFAULT_RATE_LIMIT_TIER)
    if rate_limit_tier not in RATE_LIMIT_TIERS:
        rate_limit_tier = DEFAULT_RATE_LIMIT_TIER
    max_api_calls = RATE_LIMIT_TIERS[rate_limit_tier]["max_calls"]

    reasoning_effort = settings_config.get("reasoning_effort", DEFAULT_REASONING_EFFORT)
    if reasoning_effort not in REASONING_EFFORT_LEVELS:
        reasoning_effort = DEFAULT_REASONING_EFFORT
    reasoning_effort = resolve_reasoning_effort(provider, model, reasoning_effort)

    max_session_input_tokens = _token_setting(
        settings_config,
        "max_session_input_tokens",
        0,
    )
    max_session_output_tokens = _token_setting(
        settings_config,
        "max_session_output_tokens",
        0,
    )
    max_context_input_tokens = _token_setting(
        settings_config,
        "max_context_input_tokens",
        DEFAULT_CONTEXT_INPUT_TOKENS,
    )
    context_output_reserve_tokens = _token_setting(
        settings_config,
        "context_output_reserve_tokens",
        DEFAULT_CONTEXT_OUTPUT_RESERVE_TOKENS,
        allow_zero=False,
    )
    context_recovery_tokens = _token_setting(
        settings_config,
        "context_recovery_tokens",
        DEFAULT_CONTEXT_RECOVERY_TOKENS,
    )

    return Config(
        provider=provider,
        api_key=api_key,
        model=model,
        auto_confirm=auto_confirm,
        verbose=final_verbose,
        stream=final_stream,
        agent_config=agent_config,
        reasoning_effort=reasoning_effort,
        max_api_calls_per_turn=max_api_calls,
        max_session_input_tokens=max_session_input_tokens,
        max_session_output_tokens=max_session_output_tokens,
        max_context_input_tokens=max_context_input_tokens,
        context_output_reserve_tokens=context_output_reserve_tokens,
        context_recovery_tokens=context_recovery_tokens,
    )


def _token_setting(
    settings: dict[str, object],
    name: str,
    default: int,
    *,
    allow_zero: bool = True,
) -> int:
    """Load one bounded token setting and reject unsafe malformed values."""
    if name not in settings:
        return default
    value = settings[name]
    minimum = 0 if allow_zero else 1
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > MAX_CONTEXT_SETTING_TOKENS
    ):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a {qualifier} bounded integer")
    return value
