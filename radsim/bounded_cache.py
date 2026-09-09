"""A small bounded cache that reports its own hit rate and evictions.

Every long-lived cache in a process that runs for hours needs two things a bare
dictionary does not give: an upper bound on entries, so a long session cannot
grow without limit, and counters, so a cache that never hits can be found rather
than assumed to be working.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any

DEFAULT_MAX_ENTRIES = 64

MISSING = object()


def path_signature(path: Any) -> tuple[Any, ...] | None:
    """Build a small key that changes whenever a file changes.

    A missing file is a signature of its own, so a cache entry built while a
    file was absent is invalidated the moment it appears.
    """
    if path is None:
        return None

    path = Path(path)
    try:
        stat_result = path.stat()
    except OSError:
        return (str(path), False, None, None)
    return (str(path), True, stat_result.st_mtime_ns, stat_result.st_size)


class BoundedCache:
    """Least-recently-used cache with hit, miss, and eviction counters."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self.max_entries = max(1, int(max_entries))
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._entries: OrderedDict[Any, Any] = OrderedDict()
        self._lock = Lock()

    def get(self, key: Any) -> Any:
        """Return the cached value, or :data:`MISSING` when absent."""
        with self._lock:
            if key not in self._entries:
                self.misses += 1
                return MISSING
            self._entries.move_to_end(key)
            self.hits += 1
            return self._entries[key]

    def set(self, key: Any, value: Any) -> None:
        """Store a value, evicting the least recently used entry when full."""
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
            self._entries[key] = value
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self.evictions += 1

    def clear(self) -> None:
        """Drop every entry, keeping the lifetime counters."""
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, Any]:
        """Return hit rate and size, for telemetry and cache review."""
        with self._lock:
            lookups = self.hits + self.misses
            return {
                "entries": len(self._entries),
                "max_entries": self.max_entries,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "hit_rate": round(self.hits / lookups, 4) if lookups else 0.0,
            }
