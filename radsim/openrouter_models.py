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

from .persistence import atomic_write_json

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 24 * 60 * 60
FETCH_TIMEOUT_SECONDS = 10
MAX_CATALOGUE_MODELS = 5_000
MAX_CACHE_BYTES = 5_000_000
MAX_STRING_LENGTH = 512

_catalogue = None
_catalogue_key = None
_catalogue_fetched_at = 0.0


def _cache_path() -> Path:
    from .config import CONFIG_DIR

    return CONFIG_DIR / "models_cache.json"


def _load_cache() -> dict | None:
    """Load and validate the disk cache, reusing unchanged in-memory data."""
    global _catalogue, _catalogue_key, _catalogue_fetched_at
    path = _cache_path()
    try:
        stat = path.stat()
    except OSError:
        return None

    cache_key = (stat.st_mtime_ns, stat.st_size)
    if _catalogue is not None and cache_key == _catalogue_key:
        return {"fetched_at": _catalogue_fetched_at, "models": _catalogue}
    if stat.st_size > MAX_CACHE_BYTES:
        logger.debug("models_cache exceeds the size limit")
        return None

    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        logger.debug("models_cache read failed: %s", error)
        return None

    if not _is_valid_cache(payload):
        logger.debug("models_cache failed validation")
        return None

    _catalogue = payload["models"]
    _catalogue_key = cache_key
    _catalogue_fetched_at = payload["fetched_at"]
    return payload


def _is_valid_cache(payload) -> bool:
    """Validate semi-trusted on-disk catalogue state."""
    if not isinstance(payload, dict):
        return False
    fetched_at = payload.get("fetched_at")
    if not _is_number_in_range(fetched_at, 0, time.time() + 300):
        return False
    return _is_valid_models(payload.get("models"))


def _is_valid_models(models) -> bool:
    """Validate normalized model records with explicit resource bounds."""
    if not isinstance(models, list) or len(models) > MAX_CATALOGUE_MODELS:
        return False
    return all(_is_valid_model(model) for model in models)


def _is_valid_model(model) -> bool:
    """Validate one normalized model record."""
    if not isinstance(model, dict):
        return False
    if not _is_bounded_string(model.get("id"), required=True):
        return False
    if not _is_bounded_string(model.get("name"), required=False):
        return False
    if not _is_optional_number(model.get("context_length"), 0, 10_000_000):
        return False
    if not _is_optional_number(model.get("input_price"), 0, 1):
        return False
    if not _is_optional_number(model.get("output_price"), 0, 1):
        return False
    return all(
        field not in model or isinstance(model[field], bool)
        for field in ("supports_reasoning", "supports_tools")
    )


def _is_bounded_string(value, required: bool) -> bool:
    """Validate an optional or required bounded string."""
    if value is None:
        return not required
    if not isinstance(value, str) or len(value) > MAX_STRING_LENGTH:
        return False
    return bool(value) if required else True


def _is_optional_number(value, minimum, maximum) -> bool:
    """Validate an optional finite numeric field within bounds."""
    if value is None:
        return True
    return _is_number_in_range(value, minimum, maximum)


def _is_number_in_range(value, minimum, maximum) -> bool:
    """Validate a non-boolean number within inclusive bounds."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


def _save_cache(models: list[dict]) -> None:
    from .config import CONFIG_DIR

    if not _is_valid_models(models):
        logger.debug("refusing to cache an invalid model catalogue")
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": time.time(), "models": models}
    try:
        atomic_write_json(_cache_path(), payload)
    except OSError as error:
        logger.debug("models_cache write failed: %s", error)


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
        response_bytes = response.read(MAX_CACHE_BYTES + 1)
    if len(response_bytes) > MAX_CACHE_BYTES:
        raise ValueError("OpenRouter model response exceeds the size limit")

    payload = json.loads(response_bytes.decode("utf-8"))
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or len(entries) > MAX_CATALOGUE_MODELS:
        raise ValueError("OpenRouter model response has an invalid model list")

    models = [_normalize_model(entry) for entry in entries if isinstance(entry, dict)]
    if not _is_valid_models(models):
        raise ValueError("OpenRouter model response failed validation")
    return models


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


def get_openrouter_models(
    force_refresh: bool = False, allow_network: bool = True
) -> list[dict]:
    """Return the OpenRouter model catalogue.

    Order of preference:
    1. Live API fetch (when cache is stale or force_refresh is set)
    2. Cached copy on disk (even if stale, when the network call fails)
    3. Static fallback derived from config.PROVIDER_MODELS
    """
    cache = _load_cache()

    if not force_refresh and cache and (_is_cache_fresh(cache) or not allow_network):
        return cache["models"]

    if not allow_network:
        return _static_fallback()

    try:
        models = _fetch_from_api()
        if models:
            _save_cache(models)
            return models
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValueError,
    ) as error:
        logger.debug("openrouter fetch failed: %s", error)

    if cache and cache.get("models"):
        return cache["models"]

    return _static_fallback()


def _static_fallback() -> list[dict]:
    from .config import CONTEXT_LIMITS, MODEL_CAPABILITIES, MODEL_PRICING, PROVIDER_MODELS
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


def find_model(model_id: str, allow_network: bool = False) -> dict | None:
    """Look up a model without network I/O unless explicitly allowed."""
    for model in get_openrouter_models(allow_network=allow_network):
        if model["id"] == model_id:
            return model
    return None


def model_supports_reasoning(model_id: str) -> bool:
    model = find_model(model_id)
    return bool(model and model.get("supports_reasoning"))
