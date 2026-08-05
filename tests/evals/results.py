"""Private, atomic, bounded storage for behavioural eval results."""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from radsim.memory import sanitize_data
from radsim.persistence import atomic_write_json

RESULT_SCHEMA_VERSION = 1
MAX_RESULT_BYTES = 20 * 1024 * 1024
MAX_STRING_CHARS = 100_000
MAX_CONTAINER_ITEMS = 2_000
MAX_NESTING_DEPTH = 20
RETENTION_DAYS = 30
MAX_RESULT_FILES = 50
LATEST_FILE_NAME = "latest.json"
RESULT_NAME_PATTERN = re.compile(
    r"^\d{8}T\d{6}\.\d{6}Z-(?:[0-9a-f]{7,12}|unknown)-"
    r"(?:[0-9a-f]{12}|unknown)\.json$"
)
SENSITIVE_KEY_PARTS = (
    "access_code",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
)
SENSITIVE_KEY_NAMES = ("token", "access_token", "refresh_token", "session_token")

logger = logging.getLogger(__name__)


class EvalResultTooLarge(ValueError):
    """Raised before persistence when a sanitized result exceeds its bound."""


def write_eval_result(
    result_directory: str | Path,
    payload: dict[str, Any],
    *,
    created_at: datetime | None = None,
) -> Path:
    """Write one immutable result and then update the portable latest pointer."""
    directory = _prepare_directory(result_directory)
    timestamp = _utc_time(created_at)
    sanitized = sanitize_result(payload)
    sanitized["result_schema_version"] = RESULT_SCHEMA_VERSION
    _validate_result_size(sanitized)

    result_path = directory / _result_name(timestamp, sanitized.get("manifest", {}))
    if result_path.exists():
        raise FileExistsError(f"Eval result already exists: {result_path.name}")
    atomic_write_json(result_path, sanitized, secure=True)
    atomic_write_json(directory / LATEST_FILE_NAME, _latest_pointer(result_path, sanitized), secure=True)
    prune_results(directory, now=timestamp)
    return result_path


def sanitize_result(value: Any, depth: int = 0) -> Any:
    """Redact likely secrets and bound nested provider/model-controlled data."""
    if depth > MAX_NESTING_DEPTH:
        return "[bounded]"
    if isinstance(value, dict):
        return _sanitize_mapping(value, depth)
    if isinstance(value, (list, tuple)):
        items = [sanitize_result(item, depth + 1) for item in value[:MAX_CONTAINER_ITEMS]]
        if len(value) > MAX_CONTAINER_ITEMS:
            items.append("[truncated]")
        return items
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (bool, int)):
        return value
    return _sanitize_text(str(value))


def load_latest_compatible(
    result_directory: str | Path,
    current_manifest: dict[str, Any],
) -> dict[str, Any] | None:
    """Load latest only when its pointer, size and provenance are trustworthy."""
    directory = Path(result_directory)
    if directory.is_symlink():
        return None
    pointer = _read_json_file(directory / LATEST_FILE_NAME)
    if not isinstance(pointer, dict):
        return None
    if pointer.get("schema_version") != RESULT_SCHEMA_VERSION:
        return None
    result_name = pointer.get("result_file")
    if not isinstance(result_name, str) or not RESULT_NAME_PATTERN.fullmatch(result_name):
        return None

    result = _read_json_file(directory / result_name)
    if not isinstance(result, dict):
        return None
    if result.get("result_schema_version") != RESULT_SCHEMA_VERSION:
        return None
    stored_manifest = result.get("manifest")
    if not isinstance(stored_manifest, dict):
        return None
    if pointer.get("artifact_digest") != stored_manifest.get("artifact_digest"):
        return None
    if not manifests_compatible(stored_manifest, current_manifest):
        return None
    return result


def manifests_compatible(stored: Any, current: Any) -> bool:
    """Require exact eval artifacts and model configuration for baseline reuse."""
    if not isinstance(stored, dict) or not isinstance(current, dict):
        return False
    required_fields = ("schema_version", "artifact_digest", "artifacts", "selection")
    if any(stored.get(field) != current.get(field) for field in required_fields):
        return False
    stored_execution = stored.get("execution", {})
    current_execution = current.get("execution", {})
    compatibility_fields = ("max_iterations", "seed")
    return all(
        stored_execution.get(field) == current_execution.get(field)
        for field in compatibility_fields
    )


def prune_results(result_directory: str | Path, *, now: datetime | None = None) -> None:
    """Remove only recognized generated result files outside the retention policy."""
    directory = Path(result_directory)
    cutoff = _utc_time(now) - timedelta(days=RETENTION_DAYS)
    files = _result_files(directory)
    retained = []
    for path in files:
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError:
            continue
        if modified_at < cutoff:
            _unlink_result(path)
        else:
            retained.append(path)
    for path in retained[:-MAX_RESULT_FILES]:
        _unlink_result(path)


def _prepare_directory(result_directory: str | Path) -> Path:
    directory = Path(result_directory)
    if directory.is_symlink():
        raise ValueError("Eval result directory must not be a symlink.")
    if directory.exists() and not directory.is_dir():
        raise ValueError("Eval result path must be a directory.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def _sanitize_mapping(value: dict[Any, Any], depth: int) -> dict[str, Any]:
    sanitized = {}
    items = list(value.items())[:MAX_CONTAINER_ITEMS]
    for key, item in items:
        safe_key = _sanitize_text(str(key))[:200]
        if _is_sensitive_key(safe_key):
            sanitized[safe_key] = "[REDACTED_SECRET]"
        else:
            sanitized[safe_key] = sanitize_result(item, depth + 1)
    if len(value) > MAX_CONTAINER_ITEMS:
        sanitized["truncated"] = True
    return sanitized


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in SENSITIVE_KEY_NAMES:
        return True
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _sanitize_text(value: str) -> str:
    bounded = value[:MAX_STRING_CHARS]
    redacted = sanitize_data(bounded)
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+",
        r"\1[REDACTED_SECRET]",
        redacted,
    )
    return re.sub(r"(?i)(://[^:\s/@]+:)[^@\s/]+@", r"\1[REDACTED_SECRET]@", redacted)


def _validate_result_size(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_RESULT_BYTES:
        raise EvalResultTooLarge(f"Sanitized eval result exceeds {MAX_RESULT_BYTES} bytes.")


def _result_name(created_at: datetime, manifest: Any) -> str:
    timestamp = created_at.strftime("%Y%m%dT%H%M%S.%fZ")
    repository = manifest.get("repository", {}) if isinstance(manifest, dict) else {}
    commit = _safe_digest(repository.get("commit"), 12, minimum=7)
    artifact = _safe_digest(manifest.get("artifact_digest"), 12)
    return f"{timestamp}-{commit}-{artifact}.json"


def _safe_digest(value: Any, length: int, *, minimum: int | None = None) -> str:
    minimum = minimum or length
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]+", value):
        return "unknown"
    if len(value) < minimum:
        return "unknown"
    return value[:length].lower()


def _latest_pointer(result_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest", {})
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result_file": result_path.name,
        "created_at": manifest.get("created_at"),
        "artifact_digest": manifest.get("artifact_digest"),
    }


def _read_json_file(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_RESULT_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _result_files(directory: Path) -> list[Path]:
    if not directory.is_dir() or directory.is_symlink():
        return []
    paths = (
        path
        for path in directory.iterdir()
        if not path.is_symlink() and path.is_file() and RESULT_NAME_PATTERN.fullmatch(path.name)
    )
    return sorted(paths, key=lambda path: path.name)


def _unlink_result(path: Path) -> None:
    try:
        path.unlink()
    except OSError as error:
        logger.warning("Could not prune eval result %s: %s", path.name, error)


def _utc_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
