"""Batched learning-event persistence.

One SQLite transaction per tool round instead of one per event. Committing 20
events individually costs about 52.9 ms; the same 20 in one transaction cost
about 3.0 ms, because per-commit fsync and transaction overhead dominates small
writes.

Buffering trades durability-per-event for throughput, so the queue is flushed at
every point a later decision could depend on it: the end of a tool round, turn
completion, process shutdown, and before any read of the store.
"""

from __future__ import annotations

import logging
import threading
import time

from ..performance import emit_active_performance_event
from .events import LearningEvent

logger = logging.getLogger(__name__)

DEFAULT_FLUSH_THRESHOLD = 20
DEFAULT_MAX_PENDING = 500


class LearningEventBuffer:
    """Queue validated events and persist them in one transaction per flush."""

    def __init__(
        self,
        store,
        *,
        flush_threshold: int = DEFAULT_FLUSH_THRESHOLD,
        max_pending: int = DEFAULT_MAX_PENDING,
    ) -> None:
        self.store = store
        self.flush_threshold = max(1, int(flush_threshold))
        self.max_pending = max(self.flush_threshold, int(max_pending))
        self.dropped_events = 0
        self._pending: list[LearningEvent] = []
        self._lock = threading.Lock()

    @property
    def pending_count(self) -> int:
        """Return how many events are waiting to be written."""
        with self._lock:
            return len(self._pending)

    def add(self, event: LearningEvent) -> bool:
        """Queue one event, flushing when the batch threshold is reached.

        Validation happens here rather than inside the transaction so one
        malformed event cannot roll back a batch of good ones.
        """
        if not _is_persistable(event):
            logger.debug("Rejected malformed learning event before buffering")
            return False

        with self._lock:
            self._pending.append(event)
            self._discard_overflow()
            should_flush = len(self._pending) >= self.flush_threshold

        if should_flush:
            self.flush()
        return True

    def flush(self) -> int:
        """Write every queued event in one transaction and return the count.

        A failed transaction writes nothing, so the batch is returned to the
        front of the queue and retried on the next flush.
        """
        with self._lock:
            batch = self._pending
            self._pending = []

        if not batch:
            return 0

        started_at = time.perf_counter()
        try:
            inserted = self.store.append_many(batch)
        except Exception as error:
            self._requeue(batch)
            logger.debug("Learning batch flush failed; events requeued", exc_info=True)
            self._emit_flush_event(
                batch_size=len(batch),
                inserted=0,
                started_at=started_at,
                success=False,
                error_type=type(error).__name__,
            )
            return 0

        self._emit_flush_event(
            batch_size=len(batch),
            inserted=inserted,
            started_at=started_at,
            success=True,
            error_type="",
        )
        return inserted

    def clear(self) -> int:
        """Discard queued events without writing them and return the count."""
        with self._lock:
            discarded = len(self._pending)
            self._pending = []
        return discarded

    def _requeue(self, batch: list[LearningEvent]) -> None:
        """Restore an unwritten batch ahead of events queued during the flush."""
        with self._lock:
            self._pending = batch + self._pending
            self._discard_overflow()

    def _discard_overflow(self) -> None:
        """Bound the queue by dropping the oldest events. Caller holds the lock."""
        overflow = len(self._pending) - self.max_pending
        if overflow <= 0:
            return
        del self._pending[:overflow]
        self.dropped_events += overflow
        logger.debug("Dropped %d buffered learning events over the queue bound", overflow)

    def _emit_flush_event(
        self,
        *,
        batch_size: int,
        inserted: int,
        started_at: float,
        success: bool,
        error_type: str,
    ) -> None:
        emit_active_performance_event(
            "learning_flush",
            batch_size=batch_size,
            inserted_events=inserted,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            queue_depth=self.pending_count,
            dropped_events=self.dropped_events,
            success=success,
            error_type=error_type,
        )


def _is_persistable(event: object) -> bool:
    """Return whether an event carries the identity the store requires."""
    if not isinstance(event, LearningEvent):
        return False
    return bool(event.event_id and event.event_type and event.created_at)
