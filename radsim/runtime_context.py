"""Shared runtime context for long-lived caches and services."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from .bounded_cache import MISSING, BoundedCache, path_signature

# One entry per working directory and cache key. A session that moves between
# projects accumulates entries, so the bound matters even though each is small.
MAX_CACHE_ENTRIES = 32


def _get_path_signature(path):
    """Build a small signature that changes when a file changes."""
    return path_signature(path)


@dataclass
class CachedPromptFragment:
    """Cached prompt fragment with its source file signatures."""

    signatures: tuple
    content: str


@dataclass
class CachedProjectDetection:
    """Cached project detection for one working directory."""

    signatures: tuple
    result: dict


class RuntimeContext:
    """Hold shared runtime state for the current process."""

    def __init__(self):
        self._lock = RLock()
        self._memory = None
        self._memory_key = None
        self._project_detection_cache = BoundedCache(max_entries=MAX_CACHE_ENTRIES)
        self._prompt_fragment_cache = BoundedCache(max_entries=MAX_CACHE_ENTRIES)

    def get_memory(self):
        """Return one shared Memory instance per working directory."""
        current_cwd = Path.cwd().resolve()
        from .config import CONFIG_DIR

        memory_key = (current_cwd, Path(CONFIG_DIR).resolve())

        with self._lock:
            if self._memory is None or self._memory_key != memory_key:
                from .memory import Memory

                self._memory = Memory()
                self._memory_key = memory_key

            return self._memory

    def get_cached_project_detection(self, cache_key, paths, builder):
        """Cache project detection until one of the source files changes."""
        signatures = tuple(_get_path_signature(path) for path in paths)
        cache_id = (Path.cwd().resolve(), cache_key)

        cached_entry = self._project_detection_cache.get(cache_id)
        if cached_entry is not MISSING and cached_entry.signatures == signatures:
            return deepcopy(cached_entry.result)

        result = builder()
        self._project_detection_cache.set(
            cache_id,
            CachedProjectDetection(signatures=signatures, result=deepcopy(result)),
        )
        return deepcopy(result)

    def get_cached_prompt_fragment(self, cache_key, paths, builder):
        """Cache a prompt fragment until one of its backing files changes."""
        signatures = tuple(_get_path_signature(path) for path in paths)
        cache_id = (Path.cwd().resolve(), cache_key)

        cached_entry = self._prompt_fragment_cache.get(cache_id)
        if cached_entry is not MISSING and cached_entry.signatures == signatures:
            return cached_entry.content

        content = builder()
        self._prompt_fragment_cache.set(
            cache_id,
            CachedPromptFragment(signatures=signatures, content=content),
        )
        return content

    def cache_stats(self):
        """Return hit rate and size for every cache the context owns."""
        from .tool_schema import schema_cache_stats
        from .user_hooks import hook_cache_stats

        return {
            "project_detection": self._project_detection_cache.stats(),
            "prompt_fragment": self._prompt_fragment_cache.stats(),
            "tool_schema": schema_cache_stats(),
            "user_hooks": hook_cache_stats(),
        }

    def clear_all(self):
        """Drop every cache tracked by the runtime context."""
        from .tool_schema import clear_schema_cache
        from .user_hooks import clear_hook_cache

        with self._lock:
            self._memory = None
            self._memory_key = None
            self._project_detection_cache.clear()
            self._prompt_fragment_cache.clear()
        clear_schema_cache()
        clear_hook_cache()


_runtime_context = RuntimeContext()


def get_runtime_context():
    """Return the process-wide runtime context."""
    return _runtime_context
