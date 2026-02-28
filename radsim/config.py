"""Configuration loader for RadSim Agent."""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Config:
    """RadSim configuration."""

    provider: str
    api_key: str
    model: str
    auto_confirm: bool = False
    verbose: bool = False
    stream: bool = True
    agent_config: dict = field(default_factory=dict)
    # Rate limiting settings (aggressive loop protection)
    max_api_calls_per_turn: int = 15  # Hard stop after 15 calls without user input
    max_session_input_tokens: int = 0  # 0 = unlimited (set to 500000 for budget limit)
    max_session_output_tokens: int = 0  # 0 = unlimited (set to 100000 for budget limit)
    rate_limit_cooldown_ms: int = 50  # Faster cooldown
    circuit_breaker_threshold: int = 3


# Available models for each provider (Updated Feb 2026)
PROVIDER_MODELS = {
    "claude": [
        ("claude-opus-4-6", "Claude Opus 4.6 (Most capable)"),
        ("claude-sonnet-4-5", "Claude Sonnet 4.5 (Recommended)"),
        ("claude-haiku-4-5", "Claude Haiku 4.5 (Fast & cheap)"),
    ],
    "openai": [
        ("gpt-5.2", "GPT-5.2 (Recommended)"),
        ("gpt-5.2-codex", "GPT-5.2 Codex (Agentic coding)"),
        ("gpt-5-codex", "GPT-5 Codex (Coding optimized)"),
        ("gpt-5-mini", "GPT-5 Mini (Fast & cheap)"),
        ("gpt-5.1", "GPT-5.1"),
    ],
    "gemini": [
        ("gemini-3-pro", "Gemini 3 Pro (Most capable)"),
        ("gemini-3-flash", "Gemini 3 Flash (Recommended)"),
        ("gemini-2.5-pro", "Gemini 2.5 Pro"),
        ("gemini-2.5-flash", "Gemini 2.5 Flash (Fast & cheap)"),
    ],
    "vertex": [
        ("claude-opus-4-6", "Claude Opus 4.6 on Vertex (Most capable)"),
        ("gemini-2.5-pro", "Gemini 2.5 Pro on Vertex (Recommended)"),
        ("gemini-2.5-flash", "Gemini 2.5 Flash on Vertex (Fast)"),
        ("claude-sonnet-4-5", "Claude Sonnet 4.5 on Vertex"),
        ("claude-haiku-4-5", "Claude Haiku 4.5 on Vertex (Cheap)"),
    ],
    "openrouter": [
        ("moonshotai/kimi-k2.5", "Kimi K2.5 (Recommended)"),
        ("anthropic/claude-opus-4.6", "Claude Opus 4.6 via OpenRouter"),
        ("anthropic/claude-sonnet-4.6", "Claude Sonnet 4.6 via OpenRouter"),
        ("openai/gpt-5.2-codex", "GPT-5.2 Codex via OpenRouter"),
        ("minimax/minimax-m2.1", "Minimax M2.1 (Fast)"),
        ("z-ai/glm-4.7", "GLM 4.7 (Capable)"),
    ],
}

# Default model for each provider (Updated Feb 2026)
DEFAULT_MODELS = {
    "claude": "claude-sonnet-4-5",
    "openai": "gpt-5.2",
    "gemini": "gemini-3-flash",
    "vertex": "gemini-2.5-pro",
    "openrouter": "moonshotai/kimi-k2.5",
}

PROVIDER_URLS = {
    "claude": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
    "gemini": "https://aistudio.google.com/apikey",
    "vertex": "https://console.cloud.google.com/vertex-ai",
    "openrouter": "https://openrouter.ai/keys",
}

# Provider-specific environment variable names
PROVIDER_ENV_VARS = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "vertex": "GOOGLE_CLOUD_PROJECT",
    "openrouter": "OPENROUTER_API_KEY",
}

# Fallback models for automatic failover (in priority order)
FALLBACK_MODELS = {
    "claude": [
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    ],
    "openai": [
        "gpt-5.2",
        "gpt-5.1",
        "gpt-5-mini",
    ],
    "gemini": [
        "gemini-3-flash",
        "gemini-2.5-flash",
    ],
    "vertex": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "claude-haiku-4-5",
    ],
    "openrouter": [
        "moonshotai/kimi-k2.5",
        "anthropic/claude-opus-4.6",
        "anthropic/claude-sonnet-4.6",
        "openai/gpt-5.2-codex",
        "minimax/minimax-m2.1",
        "z-ai/glm-4.7",
    ],
}

# Pricing per 1M tokens (input, output) in USD - Updated Feb 2026
MODEL_PRICING = {
    # Claude Series
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    # OpenAI GPT-5 Series
    "gpt-5.2": (5.00, 15.00),
    "gpt-5.2-codex": (5.00, 15.00),
    "gpt-5-codex": (5.00, 15.00),
    "gpt-5-mini": (1.00, 4.00),
    "gpt-5.1": (5.00, 15.00),
    # Google Gemini 3 Series
    "gemini-3-pro": (1.25, 5.00),
    "gemini-3-flash": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 5.00),
    "gemini-2.5-flash": (0.075, 0.30),
    # OpenRouter models
    "moonshotai/kimi-k2.5": (0.14, 0.28),
    "anthropic/claude-opus-4.6": (5.00, 25.00),
    "anthropic/claude-sonnet-4.6": (3.00, 15.00),
    "openai/gpt-5.2-codex": (0.60, 2.40),
    "minimax/minimax-m2.1": (0.20, 0.55),
    "z-ai/glm-4.7": (0.50, 0.50),
}

# Context window limits per model (in tokens) - Updated Feb 2026
CONTEXT_LIMITS = {
    # Claude Series
    "claude-opus-4-6": 200000,
    "claude-sonnet-4-5": 200000,
    "claude-haiku-4-5": 200000,
    # OpenAI GPT-5 Series
    "gpt-5.2": 256000,
    "gpt-5.2-codex": 256000,
    "gpt-5-codex": 256000,
    "gpt-5-mini": 128000,
    "gpt-5.1": 256000,
    # Google Gemini 3 Series
    "gemini-3-pro": 2000000,
    "gemini-3-flash": 1000000,
    "gemini-2.5-pro": 2000000,
    "gemini-2.5-flash": 1000000,
    # OpenRouter models
    "anthropic/claude-opus-4.6": 1000000,
    "anthropic/claude-sonnet-4.6": 1000000,
    "openai/gpt-5.2-codex": 128000,
}

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
    "gpt-5-codex": {
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
    "gpt-5.1": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": True,
        "max_output_tokens": 16384,
    },
    # Gemini 3 Series - Enhanced multimodal
    "gemini-3-pro": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "supports_audio": True,
        "max_output_tokens": 8192,
    },
    "gemini-3-flash": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "supports_audio": True,
        "max_output_tokens": 8192,
    },
    "gemini-2.5-pro": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "max_output_tokens": 8192,
    },
    "gemini-2.5-flash": {
        "supports_tools": True,
        "supports_streaming": True,
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
    "openai/gpt-5.2-codex": {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_reasoning": True,
        "supports_vision": False,
        "max_output_tokens": 16384,
    },
}


def get_model_capabilities(model: str) -> dict:
    """Get capabilities for a specific model.

    RadSim Principle: Graceful Degradation
    Returns default capabilities if model not found.
    """
    default_capabilities = {
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": False,
        "max_output_tokens": 4096,
    }
    return MODEL_CAPABILITIES.get(model, default_capabilities)


CONFIG_DIR = Path.home() / ".radsim"
ENV_FILE = CONFIG_DIR / ".env"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
MEMORY_DIR = CONFIG_DIR / "memory"
SCHEDULES_FILE = CONFIG_DIR / "schedules.json"
PACKAGE_DIR = Path(__file__).parent  # The radsim source directory
CUSTOM_PROMPT_FILE = CONFIG_DIR / "custom_prompt.txt"


def load_env_file():
    """Load config from .env file.

    Always reads ONLY from the global ~/.radsim/.env.
    Local project .env files are intentionally ignored so that
    API keys and model settings are always controlled from one place.

    Supports both RADSIM_API_KEY and provider-specific keys.
    """
    result = {"api_key": None, "provider": None, "model": None, "keys": {}}

    # Only read from the global config file — never local project .env
    env_files_to_check = []
    if ENV_FILE.exists():
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
                elif key == "RADSIM_MODEL" and not result["model"]:
                    result["model"] = value
                # Also capture provider-specific API keys and access code
                elif key in (
                    "ANTHROPIC_API_KEY",
                    "OPENAI_API_KEY",
                    "GOOGLE_API_KEY",
                    "OPENROUTER_API_KEY",
                    "GOOGLE_CLOUD_PROJECT",
                    "GOOGLE_CLOUD_LOCATION",
                    "RADSIM_ACCESS_CODE",
                    "TELEGRAM_BOT_TOKEN",
                    "TELEGRAM_CHAT_ID",
                ):
                    if key not in result["keys"]:
                        result["keys"][key] = value
        except Exception:
            logger.debug(f"Failed to parse env file: {env_file}")

    return result


def load_settings_file():
    """Load config from settings.json file."""
    if not SETTINGS_FILE.exists():
        return {}

    try:
        return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        logger.debug(f"Failed to parse settings file: {SETTINGS_FILE}")
        return {}


def save_config(api_key, provider, model):
    """Save config to .env file with secure permissions.

    Saves provider, model, AND API key to ~/.radsim/.env
    Preserves existing API keys from other providers.
    File is chmod 600 (owner read/write only) for security.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Get provider-specific env var name
    env_var = PROVIDER_ENV_VARS.get(provider, "RADSIM_API_KEY")

    # Load existing keys to preserve them
    existing_config = load_env_file()
    existing_keys = existing_config.get("keys", {})

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
        print("  🔐 For security, API keys must be set in the .env file.")
        print()
        print("  Edit your .env file:")
        print("    Local:  ./.env")
        print(f"    Global: {ENV_FILE}")
        print()
        print("  Add your API key for your chosen provider:")
        print("    ANTHROPIC_API_KEY    - https://console.anthropic.com/settings/keys")
        print("    OPENAI_API_KEY       - https://platform.openai.com/api-keys")
        print("    GOOGLE_API_KEY       - https://aistudio.google.com/apikey")
        print("    GOOGLE_CLOUD_PROJECT - https://console.cloud.google.com/vertex-ai")
        print("    OPENROUTER_API_KEY   - https://openrouter.ai/keys")
        print()
        print("  Then run 'radsim' again.")
        print()
    else:
        print("  ╭─────────────────────────────────────╮")
        print("  │        RadSim - Configuration       │")
        print("  ╰─────────────────────────────────────╯")
    print()
    print("  Select your AI provider:")
    print("    1. Claude (Anthropic)")
    print("    2. GPT-5 (OpenAI)")
    print("    3. Gemini (Google)")
    print("    4. Vertex AI (Google Cloud)")
    print("    5. OpenRouter (Free)")
    print()

    try:
        choice = input("  Enter 1-5: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        return None, None, None

    provider_map = {
        "1": "claude",
        "2": "openai",
        "3": "gemini",
        "4": "vertex",
        "5": "openrouter",
    }
    provider = provider_map.get(choice)

    if not provider:
        print("  Invalid choice.")
        return None, None, None

    # Select model
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
            model = models[0][0]  # Default to first
    except ValueError:
        model = models[0][0]  # Default to first

    env_var_name = PROVIDER_ENV_VARS.get(provider, "RADSIM_API_KEY")

    # Vertex AI uses project ID instead of an API key
    if provider == "vertex":
        existing_project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not existing_project:
            env_config = load_env_file()
            existing_project = env_config.get("keys", {}).get("GOOGLE_CLOUD_PROJECT")

        if existing_project and not existing_project.startswith("PASTE_YOUR"):
            print()
            print(f"  ✓ Found GOOGLE_CLOUD_PROJECT: {existing_project}")
            location = os.getenv("GOOGLE_CLOUD_LOCATION")
            if not location:
                env_config = env_config if "env_config" in dir() else load_env_file()
                location = env_config.get("keys", {}).get(
                    "GOOGLE_CLOUD_LOCATION", "us-central1"
                )
            api_key = f"{existing_project}:{location}"
        else:
            print()
            print("  ⚠ No Google Cloud project configured for Vertex AI.")
            print()
            print("  🔐 Add to your .env file:")
            print(f"     ./.env  OR  {ENV_FILE}")
            print()
            print('     GOOGLE_CLOUD_PROJECT="your-gcp-project-id"')
            print('     GOOGLE_CLOUD_LOCATION="us-central1"  # optional')
            print()
            print("  Also ensure ADC is set up:")
            print("     gcloud auth application-default login")
            print()
            print(f"  More info: {PROVIDER_URLS[provider]}")
            print()
            print("  Then run 'radsim' again.")
            return None, None, None
    else:
        # Standard API key flow for other providers
        # Check environment first, then .env file
        existing_key = os.getenv(env_var_name)
        if not existing_key:
            env_config = load_env_file()
            existing_key = env_config.get("keys", {}).get(env_var_name)

        if existing_key and not existing_key.startswith("PASTE_YOUR"):
            print()
            print(f"  ✓ Found {env_var_name} configured.")
            api_key = existing_key
        else:
            print()
            print(f"  ⚠ No API key found for {provider}.")
            print()
            print("  🔐 For security, please edit your .env file directly:")
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
    print(f"  ✓ Preferences saved to {ENV_FILE}")
    print()

    return api_key, provider, model


def load_config(
    provider_override=None, api_key_override=None, auto_confirm=False, verbose=False, stream=True
):
    """Load configuration from environment or overrides."""
    # Load from .env file and settings.json
    env_config = load_env_file()
    settings_config = load_settings_file()

    agent_config = settings_config.get("agent_config", {})

    # Determine provider (priority: override > env var > .env file > settings.json > default)
    provider = (
        provider_override
        or os.getenv("RADSIM_PROVIDER")
        or env_config["provider"]
        or settings_config.get("default_provider")
        or "claude"
    )

    # Determine API key
    # Priority: 1) CLI override, 2) .env file (provider-specific), 3) .env file (RADSIM_API_KEY), 4) System env var
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

    if not api_key and provider == "vertex":
        # Vertex AI uses project ID + location instead of an API key
        project_id = env_config.get("keys", {}).get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        if project_id and not is_placeholder_key(project_id):
            location = env_config.get("keys", {}).get(
                "GOOGLE_CLOUD_LOCATION", "us-central1"
            )
            if not location:
                location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
            api_key = f"{project_id}:{location}"

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

    # Determine model (priority: env var > .env file > settings.json > default)
    model = (
        os.getenv("RADSIM_MODEL") or env_config.get("model") or settings_config.get("default_model")
    )

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

    return Config(
        provider=provider,
        api_key=api_key,
        model=model,
        auto_confirm=auto_confirm,
        verbose=final_verbose,
        stream=final_stream,
        agent_config=agent_config,
    )
