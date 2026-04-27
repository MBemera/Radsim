"""Dynamic OpenRouter model catalog with on-disk caching.

Fetches the live model list from https://openrouter.ai/api/v1/models, caches
it to ~/.radsim/models_cache.json with a 24-hour TTL, and falls back to the
static catalogue in config.PROVIDER_MODELS on failure.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 24 * 60 * 60
FETCH_TIMEOUT_SECONDS = 10


def _cache_path() -> Path:
    from .config import CONFIG_DIR
    return CONFIG_DIR / "models_cache.json"


def _load_cache() -> dict | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug(f"models_cache read failed: {exc}")
        return None


def _save_cache(models: list[dict]) -> None:
    from .config import CONFIG_DIR
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": time.time(), "models": models}
    try:
        _cache_path().write_text(json.dumps(payload, indent=2))
    except OSError as exc:
        logger.debug(f"models_cache write failed: {exc}")


def _is_cache_fresh(cache: dict, ttl_seconds: int = CACHE_TTL_SECONDS) -> bool:
    fetched_at = cache.get("fetched_at", 0)
    return (time.time() - fetched_at) < ttl_seconds


def _fetch_from_api() -> list[dict]:
    request = urllib.request.Request(
        OPENROUTER_MODELS_URL,
        headers={
            "User-Agent": "RadSim/1.4",
            "HTTP-Referer": "https://github.com/radsim/radsim",
            "X-Title": "RadSim Agent",
        },
    )
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [_normalize_model(entry) for entry in payload.get("data", [])]


def _normalize_model(entry: dict) -> dict:
    """Reduce an OpenRouter model entry to the fields RadSim cares about."""
    pricing = entry.get("pricing") or {}
    top_provider = entry.get("top_provider") or {}
    supported_params = entry.get("supported_parameters") or []
    return {
        "id": entry.get("id", ""),
        "name": entry.get("name") or entry.get("id", ""),
        "context_length": entry.get("context_length")
            or top_provider.get("context_length")
            or 0,
        "input_price": _safe_float(pricing.get("prompt")),
        "output_price": _safe_float(pricing.get("completion")),
        "supports_reasoning": "reasoning" in supported_params
            or "reasoning_effort" in supported_params,
        "supports_tools": "tools" in supported_params,
    }


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def get_openrouter_models(force_refresh: bool = False) -> list[dict]:
    """Return the OpenRouter model catalogue.

    Order of preference:
    1. Live API fetch (when cache is stale or force_refresh is set)
    2. Cached copy on disk (even if stale, when the network call fails)
    3. Static fallback derived from config.PROVIDER_MODELS
    """
    cache = _load_cache()

    if not force_refresh and cache and _is_cache_fresh(cache):
        return cache["models"]

    try:
        models = _fetch_from_api()
        if models:
            _save_cache(models)
            return models
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.debug(f"openrouter fetch failed: {exc}")

    if cache and cache.get("models"):
        return cache["models"]

    return _static_fallback()


def _static_fallback() -> list[dict]:
    from .config import PROVIDER_MODELS, MODEL_CAPABILITIES, MODEL_PRICING, CONTEXT_LIMITS
    fallback = []
    for model_id, label in PROVIDER_MODELS.get("openrouter", []):
        capabilities = MODEL_CAPABILITIES.get(model_id, {})
        prompt_price, completion_price = MODEL_PRICING.get(model_id, (0.0, 0.0))
        fallback.append({
            "id": model_id,
            "name": label,
            "context_length": CONTEXT_LIMITS.get(model_id, 0),
            "input_price": prompt_price / 1_000_000,
            "output_price": completion_price / 1_000_000,
            "supports_reasoning": capabilities.get("supports_reasoning", False)
                or capabilities.get("supports_extended_thinking", False),
            "supports_tools": capabilities.get("supports_tools", True),
        })
    return fallback


def find_model(model_id: str) -> dict | None:
    """Look up a model by id from the cached/dynamic catalogue."""
    for model in get_openrouter_models():
        if model["id"] == model_id:
            return model
    return None


def model_supports_reasoning(model_id: str) -> bool:
    model = find_model(model_id)
    return bool(model and model.get("supports_reasoning"))
