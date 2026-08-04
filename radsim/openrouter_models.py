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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .persistence import atomic_write_json

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 24 * 60 * 60
FETCH_TIMEOUT_SECONDS = 10
MAX_CATALOGUE_MODELS = 5_000
MAX_CACHE_BYTES = 5_000_000
MAX_STRING_LENGTH = 512
REASONING_EFFORT_ORDER = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
REASONING_EFFORT_LEVELS = set(REASONING_EFFORT_ORDER)

_catalogue = None
_catalogue_key = None
_catalogue_fetched_at = 0.0


@dataclass(frozen=True)
class CatalogueStatus:
    """Provenance for one coherent OpenRouter catalogue selection."""

    source: str
    fetched_at: str | None
    stale: bool


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
    if not _is_optional_number(model.get("cache_read_price"), 0, 1):
        return False
    if not _is_optional_number(model.get("cache_write_price"), 0, 1):
        return False
    if not _is_valid_reasoning_metadata(model):
        return False
    return all(
        field not in model or isinstance(model[field], bool)
        for field in ("supports_reasoning", "supports_tools", "reasoning_mandatory")
    )


def _is_valid_reasoning_metadata(model) -> bool:
    """Validate optional model-specific reasoning metadata."""
    efforts = model.get("reasoning_efforts")
    if efforts is not None:
        if not isinstance(efforts, list) or len(efforts) > len(REASONING_EFFORT_LEVELS):
            return False
        if len(efforts) != len(set(efforts)):
            return False
        if any(effort not in REASONING_EFFORT_LEVELS for effort in efforts):
            return False
    default_effort = model.get("default_reasoning_effort")
    return default_effort is None or default_effort in REASONING_EFFORT_LEVELS


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


def _save_cache(models: list[dict], fetched_at: float | None = None) -> float | None:
    from .config import CONFIG_DIR

    if not _is_valid_models(models):
        logger.debug("refusing to cache an invalid model catalogue")
        return None

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    saved_at = fetched_at or time.time()
    payload = {"fetched_at": saved_at, "models": models}
    try:
        atomic_write_json(_cache_path(), payload)
    except OSError as error:
        logger.debug("models_cache write failed: %s", error)
        return None
    return saved_at


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
    reasoning = entry.get("reasoning") or {}
    if not isinstance(pricing, dict):
        pricing = {}
    if not isinstance(top_provider, dict):
        top_provider = {}
    if not isinstance(supported_params, list):
        supported_params = []
    if not isinstance(reasoning, dict):
        reasoning = {}
    advertised_efforts = reasoning.get("supported_efforts") or []
    if not isinstance(advertised_efforts, list):
        advertised_efforts = []
    reasoning_efforts = [
        effort for effort in REASONING_EFFORT_ORDER
        if effort in advertised_efforts
    ]
    default_reasoning_effort = reasoning.get("default_effort")
    if default_reasoning_effort not in REASONING_EFFORT_LEVELS:
        default_reasoning_effort = None
    return {
        "id": entry.get("id", ""),
        "name": entry.get("name") or entry.get("id", ""),
        "context_length": entry.get("context_length")
            or top_provider.get("context_length")
            or 0,
        "input_price": _safe_float(pricing.get("prompt")),
        "output_price": _safe_float(pricing.get("completion")),
        "cache_read_price": _safe_float(pricing.get("input_cache_read")),
        "cache_write_price": _safe_float(pricing.get("input_cache_write")),
        "supports_reasoning": "reasoning" in supported_params
            or "reasoning_effort" in supported_params,
        "supports_tools": "tools" in supported_params,
        "reasoning_efforts": reasoning_efforts,
        "default_reasoning_effort": default_reasoning_effort,
        "reasoning_mandatory": bool(reasoning.get("mandatory", False)),
    }


def _safe_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def get_openrouter_catalogue(
    force_refresh: bool = False, allow_network: bool = True
) -> tuple[list[dict], CatalogueStatus]:
    """Return one catalogue and explicit source metadata without mixing sources."""
    cache = _load_cache()
    if not force_refresh and cache and _is_cache_fresh(cache):
        return cache["models"], _cache_status(cache, stale=False)
    if not allow_network:
        if cache:
            return cache["models"], _cache_status(cache, stale=not _is_cache_fresh(cache))
        return _static_fallback(), CatalogueStatus("static-fallback", None, True)

    models = _fetch_catalogue_safely()
    if models:
        fetched_at = time.time()
        _save_cache(models, fetched_at)
        return models, CatalogueStatus("live-catalogue", _iso_timestamp(fetched_at), False)
    if cache and cache.get("models"):
        return cache["models"], _cache_status(cache, stale=True)
    return _static_fallback(), CatalogueStatus("static-fallback", None, True)


def _fetch_catalogue_safely() -> list[dict] | None:
    try:
        return _fetch_from_api()
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValueError,
    ) as error:
        logger.debug("openrouter fetch failed: %s", error)
        return None


def _cache_status(cache: dict, *, stale: bool) -> CatalogueStatus:
    source = "stale-catalogue-cache" if stale else "catalogue-cache"
    return CatalogueStatus(source, _iso_timestamp(cache["fetched_at"]), stale)


def _iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")


def get_openrouter_models(
    force_refresh: bool = False, allow_network: bool = True
) -> list[dict]:
    """Return the OpenRouter model catalogue.

    Order of preference:
    1. Live API fetch (when cache is stale or force_refresh is set)
    2. Cached copy on disk (even if stale, when the network call fails)
    3. Static fallback derived from config.PROVIDER_MODELS
    """
    models, _status = get_openrouter_catalogue(force_refresh, allow_network)
    return models


def _static_fallback() -> list[dict]:
    from .config import (
        CONTEXT_LIMITS,
        MODEL_CAPABILITIES,
        PROVIDER_MODELS,
        get_static_model_pricing,
    )
    fallback = []
    for model_id, label in PROVIDER_MODELS.get("openrouter", []):
        capabilities = MODEL_CAPABILITIES.get(model_id, {})
        pricing = get_static_model_pricing(model_id, "openrouter", "routing")
        fallback.append({
            "id": model_id,
            "name": label,
            "context_length": CONTEXT_LIMITS.get(model_id, 0),
            "input_price": _price_per_token(pricing, "input_per_million_usd"),
            "output_price": _price_per_token(pricing, "output_per_million_usd"),
            "cache_read_price": _price_per_token(
                pricing, "cache_read_per_million_usd"
            ),
            "cache_write_price": _price_per_token(
                pricing, "cache_write_per_million_usd"
            ),
            "supports_reasoning": capabilities.get("supports_reasoning", False)
                or capabilities.get("supports_extended_thinking", False),
            "supports_tools": capabilities.get("supports_tools", True),
            "reasoning_efforts": list(capabilities.get("reasoning_efforts", ())),
            "default_reasoning_effort": capabilities.get("default_reasoning_effort"),
            "reasoning_mandatory": capabilities.get("reasoning_mandatory", False),
        })
    return fallback


def _price_per_token(pricing, field_name: str) -> float | None:
    if pricing is None:
        return None
    price = getattr(pricing, field_name)
    return None if price is None else float(price / 1_000_000)


def find_model(model_id: str, allow_network: bool = False) -> dict | None:
    """Look up a model without network I/O unless explicitly allowed."""
    model, _status = find_model_with_status(model_id, allow_network=allow_network)
    return model


def find_model_with_status(
    model_id: str, allow_network: bool = False
) -> tuple[dict | None, CatalogueStatus]:
    """Look up a model and preserve the selected catalogue's provenance."""
    models, status = get_openrouter_catalogue(allow_network=allow_network)
    for model in models:
        if model["id"] == model_id:
            return model, status
    for model in _static_fallback():
        if model["id"] == model_id:
            return model, CatalogueStatus("static-fallback", None, True)
    return None, status


def model_supports_reasoning(model_id: str) -> bool:
    model = find_model(model_id)
    return bool(model and model.get("supports_reasoning"))


def get_model_reasoning_efforts(model_id: str) -> tuple[str, ...]:
    """Return the exact effort levels advertised by OpenRouter."""
    model = find_model(model_id)
    if not model or not model.get("supports_reasoning"):
        return ()
    return tuple(model.get("reasoning_efforts") or ())


def get_model_default_reasoning_effort(model_id: str) -> str | None:
    """Return OpenRouter's default reasoning effort for one model."""
    model = find_model(model_id)
    if not model:
        return None
    return model.get("default_reasoning_effort")
