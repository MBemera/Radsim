"""Shared local retrieval plus compatibility learning facades."""

from __future__ import annotations

import atexit
import math
import os
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .buffer import LearningEventBuffer
from .events import (
    LearningEvent,
    TaskOutcome,
    bounded_text,
    classify_task,
    normalize_outcome,
    stable_identifier,
)
from .store import LearningStore

TEXT_WEIGHT = 0.55
OUTCOME_WEIGHT = 0.20
RECENCY_WEIGHT = 0.08
DECISION_WEIGHT = 0.07
CATEGORY_WEIGHT = 0.05
CONTEXT_WEIGHT = 0.05
REVERT_WEIGHT = 0.25
DEFAULT_MIN_SCORE = 0.20
MAX_INJECTED_EXAMPLE_CHARS = 3_000

FTS5_ENV_VAR = "RADSIM_LEARNING_FTS5"
DEFAULT_CANDIDATE_LIMIT = 20
_TRUTHY_VALUES = {"1", "true", "yes", "on"}

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "are", "was",
    "were", "has", "have", "had", "not", "but", "you", "your", "our", "their",
    "can", "could", "would", "should", "will", "then", "than", "when", "where",
    "what", "which", "how", "why", "all", "any", "some", "only", "use", "using",
}


def tokenize(text: str) -> set[str]:
    """Return normalized search terms used by every learning retriever."""
    return {
        word
        for word in re.findall(r"\b[a-z0-9_]+\b", (text or "").lower())
        if len(word) >= 3 and word not in STOPWORDS
    }


def tfidf_cosine_scores(query: str, documents: list[str]) -> list[float]:
    """Score documents with one pure-Python TF-IDF cosine implementation."""
    query_terms = tokenize(query)
    document_terms = [tokenize(document) for document in documents]
    if not query_terms:
        return [0.0] * len(documents)

    frequencies = Counter(
        term
        for terms in document_terms
        for term in set(terms)
    )
    document_count = len(documents)
    scores = []
    for terms in document_terms:
        shared = query_terms & terms
        if not shared:
            scores.append(0.0)
            continue
        all_terms = query_terms | terms
        dot_product = query_norm = document_norm = 0.0
        for term in all_terms:
            inverse_frequency = math.log(
                (document_count + 1) / (frequencies.get(term, 0) + 1)
            ) + 1.0
            query_value = inverse_frequency if term in query_terms else 0.0
            document_value = inverse_frequency if term in terms else 0.0
            dot_product += query_value * document_value
            query_norm += query_value * query_value
            document_norm += document_value * document_value
        denominator = math.sqrt(query_norm) * math.sqrt(document_norm)
        scores.append(dot_product / denominator if denominator else 0.0)
    return scores


def text_similarity(first: str, second: str) -> float:
    """Convenience pair score backed by the shared TF-IDF implementation."""
    return tfidf_cosine_scores(first, [second])[0]


@dataclass
class RankedEvent:
    """One event plus an explainable retrieval score."""

    event: LearningEvent
    score: float
    explanation: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "score": self.score,
            "explanation": dict(self.explanation),
        }


def rank_learning_events(
    query: str,
    events: list[LearningEvent],
    *,
    task_category: str | None = None,
    tool_name: str | None = None,
    error_type: str | None = None,
    reverted_task_ids: set[str] | None = None,
    min_score: float = DEFAULT_MIN_SCORE,
    limit: int = 5,
) -> list[RankedEvent]:
    """Rank learning events without allowing weak text overlap to hide failure."""
    if not events:
        return []
    reverted_task_ids = set(reverted_task_ids or ())
    reverted_task_ids.update(
        event.task_id
        for event in events
        if event.event_type == "task_revert"
        or event.outcome == TaskOutcome.REVERTED.value
    )
    text_scores = tfidf_cosine_scores(query, [_event_search_text(event) for event in events])
    ranked = []
    for event, text_score in zip(events, text_scores, strict=True):
        outcome_score = {
            TaskOutcome.SUCCESSFUL.value: 1.0,
            TaskOutcome.PARTIALLY_SUCCESSFUL.value: 0.35,
            TaskOutcome.UNKNOWN.value: -0.25,
            TaskOutcome.FAILED.value: -0.75,
            TaskOutcome.CANCELLED.value: -0.9,
            TaskOutcome.USER_REJECTED.value: -1.0,
            TaskOutcome.REVERTED.value: -1.0,
        }.get(event.outcome, -0.25)
        recency_score = _recency_score(event.created_at)
        decision_score = {
            "accepted": 1.0,
            "approved": 1.0,
            "rejected": -1.0,
            "reverted": -1.0,
        }.get((event.user_decision or "").lower(), 0.0)
        category_score = float(bool(task_category and event.task_category == task_category))
        context_score = float(
            bool(
                (tool_name and event.tool_name == tool_name)
                or (error_type and event.error_type == error_type)
            )
        )
        revert_score = -1.0 if event.task_id in reverted_task_ids else 0.0
        explanation = {
            "text": text_score * TEXT_WEIGHT,
            "outcome": outcome_score * OUTCOME_WEIGHT,
            "recency": recency_score * RECENCY_WEIGHT,
            "user_decision": decision_score * DECISION_WEIGHT,
            "task_category": category_score * CATEGORY_WEIGHT,
            "tool_or_error": context_score * CONTEXT_WEIGHT,
            "revert_history": revert_score * REVERT_WEIGHT,
        }
        score = sum(explanation.values())
        has_relevance = text_score > 0 or category_score > 0 or context_score > 0
        if has_relevance and score >= min_score:
            ranked.append(RankedEvent(event=event, score=score, explanation=explanation))
    guidance_priority = {
        TaskOutcome.SUCCESSFUL.value: 2,
        TaskOutcome.PARTIALLY_SUCCESSFUL.value: 1,
    }
    ranked.sort(
        key=lambda item: (
            (
                0
                if item.event.task_id in reverted_task_ids
                else guidance_priority.get(item.event.outcome, 0)
            ),
            item.score,
            item.event.created_at,
        ),
        reverse=True,
    )
    return ranked[: max(0, limit)]


def fts5_candidates_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether FTS5 narrows the candidate set before Python ranking."""
    source = os.environ if environ is None else environ
    return source.get(FTS5_ENV_VAR, "").strip().lower() in _TRUTHY_VALUES


def candidate_events(
    store: LearningStore,
    query: str,
    *,
    event_types: set[str],
    outcomes: set[str] | None = None,
    limit: int = 500,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    environ: Mapping[str, str] | None = None,
) -> list[LearningEvent]:
    """Return events for the ranker to score.

    FTS5 runs in native C and narrows a large store to a short candidate list.
    It is a first-stage filter only: the Python ranker still applies the
    outcome, recency, category, and revert weighting. Any condition that makes
    search unusable falls back to the full bounded scan, so a flag, a SQLite
    build without FTS5, or a query with no usable terms can never silently
    shrink what the ranker sees.
    """
    if fts5_candidates_enabled(environ):
        candidates = store.search_events(
            tokenize(query),
            event_types=event_types,
            outcomes=outcomes,
            limit=candidate_limit,
        )
        if candidates:
            return candidates
    return store.query(event_types=event_types, outcomes=outcomes, limit=limit)


def verified_success_events(
    store: LearningStore,
    *,
    event_types: set[str],
    limit: int = 500,
    query: str = "",
) -> list[LearningEvent]:
    """Return successful guidance events whose task was never reverted."""
    reverted = {
        event.task_id
        for event in store.query(event_types={"task_revert"}, limit=store.max_events)
    }
    successful = candidate_events(
        store,
        query,
        event_types=event_types,
        outcomes={TaskOutcome.SUCCESSFUL.value},
        limit=limit,
    )
    return [event for event in successful if event.task_id not in reverted]


def _event_search_text(event: LearningEvent) -> str:
    metadata = event.metadata
    values = (
        event.summary,
        event.error_type or "",
        event.error_message or "",
        metadata.get("approach", ""),
        metadata.get("result", ""),
        metadata.get("correction", ""),
        " ".join(str(item) for item in metadata.get("tools_used", [])),
    )
    return " ".join(str(value) for value in values)


def _recency_score(created_at: str) -> float:
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds() / 86400,
        )
        return max(0.0, 1.0 - age_days / 180)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class ErrorRecord:
    error_type: str
    error_message: str
    context: dict[str, Any]
    correction: str = ""
    timestamp: str = ""
    frequency: int = 1


class ErrorAnalyzer:
    """Error compatibility API backed by canonical events and shared retrieval."""

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = Path(storage_dir or Path.home() / ".radsim" / "learning")
        self.store = LearningStore(storage_dir=self.storage_dir)

    def record_error(
        self,
        error_type: str,
        error_message: str,
        context: dict[str, Any] | None = None,
        correction: str = "",
    ) -> None:
        context = context if isinstance(context, dict) else {}
        tool_name = context.get("tool_name") or context.get("tool")
        task = bounded_text(context.get("task_description") or context.get("action") or "")
        event = LearningEvent.create(
            event_type="error",
            task_category=classify_task(task),
            tool_name=tool_name,
            action_signature=stable_identifier(error_type, bounded_text(error_message, 100)),
            outcome=TaskOutcome.FAILED,
            summary=task or bounded_text(error_message),
            error_type=error_type,
            error_message=error_message,
            metadata={"correction": correction},
        )
        self.store.append(event)

    def check_similar_error(self, planned_action: str, tool_name: str = "") -> dict[str, Any]:
        events = candidate_events(
            self.store,
            planned_action,
            event_types={"error"},
            limit=200,
        )
        ranked = rank_learning_events(
            planned_action,
            events,
            tool_name=tool_name or None,
            min_score=0.18,
            limit=1,
        )
        if ranked:
            event = ranked[0].event
            return {
                "error_found": True,
                "warning": f"Similar error occurred before: {bounded_text(event.error_message, 100)}",
                "solution": event.metadata.get("correction") or "No recorded fix",
                "error_type": event.error_type,
                "score": ranked[0].score,
                "score_explanation": ranked[0].explanation,
            }
        frequent = self.get_error_patterns(min_frequency=3)
        for pattern in frequent:
            if tool_name and tool_name in pattern["tools_affected"]:
                return {
                    "error_found": True,
                    "warning": (
                        f"Frequent error pattern ({pattern['frequency']}x): "
                        f"{pattern['message']}"
                    ),
                    "solution": pattern["solutions"][0] if pattern["solutions"] else "Check logs",
                    "error_type": pattern["error_type"],
                }
        return {"error_found": False}

    def _similarity_score(self, text1: str, text2: str) -> float:
        return text_similarity(text1, text2)

    def get_error_patterns(self, min_frequency: int = 2) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for event in self.store.query(event_types={"error"}, limit=500):
            prefix = bounded_text(event.error_message, 100)
            key = (event.error_type or "error", prefix[:50])
            group = groups.setdefault(
                key,
                {
                    "pattern": f"{key[0]}:{key[1]}",
                    "error_type": key[0],
                    "message": prefix,
                    "frequency": 0,
                    "solutions": [],
                    "tools_affected": [],
                },
            )
            group["frequency"] += 1
            correction = bounded_text(event.metadata.get("correction", ""), 200)
            if correction and correction not in group["solutions"]:
                group["solutions"].append(correction)
            if event.tool_name and event.tool_name not in group["tools_affected"]:
                group["tools_affected"].append(event.tool_name)
        patterns = [group for group in groups.values() if group["frequency"] >= min_frequency]
        return sorted(patterns, key=lambda item: item["frequency"], reverse=True)

    def get_error_stats(self) -> dict[str, Any]:
        events = self.store.query(event_types={"error"}, limit=500)
        by_type = Counter(event.error_type or "error" for event in events)
        return {
            "total_errors": len(events),
            "unique_patterns": len(self.get_error_patterns(min_frequency=1)),
            "by_type": dict(by_type),
            "most_common": self.get_error_patterns(min_frequency=1)[:5],
        }

    def get_prevention_rules(self) -> list[str]:
        rules = []
        for pattern in self.get_error_patterns(min_frequency=3):
            if pattern["solutions"]:
                tools = ", ".join(pattern["tools_affected"]) or "tools"
                rules.append(f"When using {tools}: {pattern['solutions'][0]}")
        return rules[:10]

    def clear_history(self) -> None:
        self.store.delete(event_types={"error"})

    @property
    def _errors(self) -> list[dict[str, Any]]:
        return [
            {
                "error_type": event.error_type,
                "error_message": event.error_message,
                "context": {
                    "tool_name": event.tool_name or "",
                    "task_description": event.summary,
                },
                "correction": event.metadata.get("correction", ""),
                "timestamp": event.created_at,
            }
            for event in self.store.query(event_types={"error"}, limit=500)
        ]


@dataclass
class TaskExample:
    task_description: str
    approach_taken: str
    outcome: str
    success: bool
    timestamp: str = ""
    tools_used: list[str] | None = None


class FewShotAssembler:
    """Few-shot compatibility API using the shared event retriever."""

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = Path(storage_dir or Path.home() / ".radsim" / "learning")
        self.store = LearningStore(storage_dir=self.storage_dir)

    def record_task_completion(
        self,
        task_description: str,
        approach: str,
        outcome: str,
        success: TaskOutcome | str | bool,
        tools_used: list[str] | None = None,
    ) -> None:
        normalized = normalize_outcome(success)
        self.store.append(
            LearningEvent.create(
                event_type="task_example",
                task_category=classify_task(task_description),
                action_signature=stable_identifier(task_description),
                outcome=normalized,
                summary=task_description,
                metadata={
                    "approach": approach,
                    "result": outcome,
                    "tools_used": list(tools_used or []),
                },
            )
        )

    def _extract_keywords(self, text: str) -> list[str]:
        return sorted(tokenize(text))

    def get_examples_for_task(self, task_description: str, top_k: int = 3) -> list[dict[str, Any]]:
        events = verified_success_events(
            self.store,
            event_types={"task_example", "task_completion"},
            limit=500,
            query=task_description,
        )
        ranked = rank_learning_events(
            task_description,
            events,
            task_category=classify_task(task_description),
            min_score=DEFAULT_MIN_SCORE,
            limit=top_k,
        )
        examples = []
        used_chars = 0
        for item in ranked:
            event = item.event
            example = {
                "task_description": event.summary,
                "approach": bounded_text(event.metadata.get("approach", ""), 1000),
                "outcome": bounded_text(event.metadata.get("result", ""), 500),
                "success": True,
                "verified_outcome": event.outcome,
                "tools_used": list(event.metadata.get("tools_used", [])),
                "timestamp": event.created_at,
                "score": item.score,
                "score_explanation": item.explanation,
            }
            size = len(str(example))
            if examples and used_chars + size > MAX_INJECTED_EXAMPLE_CHARS:
                break
            examples.append(example)
            used_chars += size
        return examples

    def format_examples_for_prompt(self, examples: list[dict[str, Any]]) -> str:
        if not examples:
            return ""
        lines = ["", "## Similar Verified Tasks"]
        for index, example in enumerate(examples, 1):
            tools = ", ".join(example.get("tools_used", [])) or "none recorded"
            lines.extend(
                (
                    f"### Example {index}: {example['task_description'][:100]}",
                    f"- Approach: {example.get('approach', '')[:200]}",
                    f"- Tools: {tools}",
                    f"- Result: {example.get('outcome', '')[:100]}",
                )
            )
        lines.append("Use only the verified execution evidence that applies.")
        return "\n".join(lines)[:MAX_INJECTED_EXAMPLE_CHARS]

    def inject_examples_into_prompt(
        self,
        base_prompt: str,
        task_description: str,
        max_examples: int = 2,
    ) -> str:
        context = self.format_examples_for_prompt(
            self.get_examples_for_task(task_description, top_k=max_examples)
        )
        if not context:
            return base_prompt
        for marker in ("## Your Capabilities", "## Available Tools", "## Tools"):
            if marker in base_prompt:
                index = base_prompt.find(marker)
                return f"{base_prompt[:index]}{context}\n\n{base_prompt[index:]}"
        return f"{base_prompt}\n{context}"

    def get_examples_stats(self) -> dict[str, Any]:
        events = self.store.query(
            event_types={"task_example", "task_completion"},
            limit=500,
        )
        successful = [event for event in events if event.outcome == TaskOutcome.SUCCESSFUL.value]
        keywords = Counter(term for event in events for term in tokenize(event.summary))
        return {
            "total": len(events),
            "successful": len(successful),
            "success_rate": len(successful) / len(events) if events else 0,
            "top_keywords": keywords.most_common(10),
        }

    def clear_examples(self) -> None:
        self.store.delete(event_types={"task_example"})

    @property
    def _examples(self) -> list[dict[str, Any]]:
        return [
            {
                "task_description": event.summary,
                "approach": event.metadata.get("approach", ""),
                "outcome": event.metadata.get("result", ""),
                "success": event.outcome == TaskOutcome.SUCCESSFUL.value,
                "tools_used": event.metadata.get("tools_used", []),
                "timestamp": event.created_at,
            }
            for event in self.store.query(
                event_types={"task_example"},
                limit=500,
            )
        ]


@dataclass
class ToolExecution:
    tool_name: str
    success: bool
    duration_ms: float
    input_size: int
    output_size: int
    error: str = ""
    task_context: str = ""
    timestamp: str = ""


class ToolOptimizer:
    """Tool statistics and chain hints over the canonical event store."""

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = Path(storage_dir or Path.home() / ".radsim" / "learning")
        self.store = LearningStore(storage_dir=self.storage_dir)
        self._current_chain: list[str] = []
        self._buffer = LearningEventBuffer(self.store)

    def track_tool_execution(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        error: str = "",
        task_context: str = "",
        *,
        task_id: str = "",
        model: str = "",
        provider: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self._current_chain.append(tool_name)
        event = LearningEvent.create(
            task_id=task_id,
            event_type="tool_execution",
            task_category=classify_task(task_context),
            tool_name=tool_name,
            action_signature=stable_identifier(tool_name, task_context),
            outcome=TaskOutcome.SUCCESSFUL if success else TaskOutcome.FAILED,
            duration_ms=duration_ms,
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_type="tool_error" if not success else None,
            error_message=error if not success else None,
            summary=task_context or tool_name,
            metadata={
                "input_size": len(str(input_data or {})),
                "output_size": len(str(output_data or {})),
            },
        )
        self._buffer.add(event)

    def complete_task_chain(
        self,
        task_description: str,
        success: TaskOutcome | str | bool,
    ) -> None:
        if not self._current_chain:
            return
        self._buffer.flush()
        outcome = normalize_outcome(success)
        self.store.append(
            LearningEvent.create(
                event_type="task_completion",
                task_category=classify_task(task_description),
                action_signature=stable_identifier(task_description),
                outcome=outcome,
                summary=task_description,
                metadata={"tools_used": self._current_chain.copy()},
            )
        )
        self._current_chain = []

    def reset_current_chain(self) -> None:
        self._current_chain = []

    def suggest_tool_chain(self, task_description: str) -> list[str]:
        self._buffer.flush()
        events = verified_success_events(
            self.store,
            event_types={"task_completion", "task_example"},
            limit=500,
            query=task_description,
        )
        events = [event for event in events if event.metadata.get("tools_used")]
        ranked = rank_learning_events(
            task_description,
            events,
            task_category=classify_task(task_description),
            min_score=0.28,
            limit=1,
        )
        return list(ranked[0].event.metadata.get("tools_used", [])) if ranked else []

    def get_tool_rankings(self, context: str = "") -> list[dict[str, Any]]:
        grouped = self._tool_groups(context)
        rankings = []
        for tool_name, events in grouped.items():
            if len(events) < 2:
                continue
            successes = sum(event.outcome == TaskOutcome.SUCCESSFUL.value for event in events)
            average_duration = sum(event.duration_ms for event in events) / len(events)
            success_rate = successes / len(events)
            speed_score = max(0.0, 1.0 - average_duration / 5000)
            rankings.append(
                {
                    "tool_name": tool_name,
                    "success_rate": success_rate,
                    "avg_duration_ms": average_duration,
                    "total_uses": len(events),
                    "reliability_score": success_rate * 0.7 + speed_score * 0.3,
                }
            )
        return sorted(rankings, key=lambda item: item["reliability_score"], reverse=True)

    def get_tool_stats(self, tool_name: str) -> dict[str, Any]:
        events = self.store.query(event_types={"tool_execution"}, tool_name=tool_name, limit=500)
        if not events:
            return {"tool_name": tool_name, "total_uses": 0, "message": "No data"}
        recent = events[-100:]
        successes = sum(event.outcome == TaskOutcome.SUCCESSFUL.value for event in recent)
        midpoint = len(recent) // 2
        trend = "insufficient_data"
        if len(recent) >= 5:
            first = recent[:midpoint]
            second = recent[midpoint:]
            first_rate = sum(
                event.outcome == TaskOutcome.SUCCESSFUL.value for event in first
            ) / len(first)
            second_rate = sum(
                event.outcome == TaskOutcome.SUCCESSFUL.value for event in second
            ) / len(second)
            trend = "improving" if second_rate > first_rate else (
                "declining" if second_rate < first_rate else "stable"
            )
        return {
            "tool_name": tool_name,
            "total_uses": len(events),
            "success_rate": successes / len(recent),
            "avg_duration_ms": sum(event.duration_ms for event in recent) / len(recent),
            "trend": trend,
            "recent_errors": [
                event.error_message for event in recent if event.error_message
            ][-3:],
        }

    def get_common_chains(self) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        events = verified_success_events(
            self.store,
            event_types={"task_completion"},
            limit=500,
        )
        for event in events:
            tools = list(event.metadata.get("tools_used", []))
            if not tools:
                continue
            key = "->".join(tools)
            group = groups.setdefault(
                key,
                {"tools": tools, "count": 0, "sample_tasks": []},
            )
            group["count"] += 1
            if len(group["sample_tasks"]) < 3:
                group["sample_tasks"].append(event.summary)
        return sorted(groups.values(), key=lambda item: item["count"], reverse=True)[:10]

    def get_slow_tools(self, threshold_ms: float = 3000) -> list[dict[str, Any]]:
        return [
            ranking
            for ranking in self.get_tool_rankings()
            if ranking["avg_duration_ms"] > threshold_ms
        ]

    def get_unreliable_tools(self, threshold: float = 0.7) -> list[dict[str, Any]]:
        return [
            ranking
            for ranking in self.get_tool_rankings()
            if ranking["total_uses"] >= 3 and ranking["success_rate"] < threshold
        ]

    def clear_data(self) -> None:
        self._buffer.clear()
        self.store.delete(event_types={"tool_execution"})
        self._current_chain = []

    def flush(self) -> bool:
        """Persist buffered tool events and report whether anything was written."""
        return self._buffer.flush() > 0

    @property
    def pending_event_count(self) -> int:
        """Return how many tool events are queued but not yet written."""
        return self._buffer.pending_count

    def _tool_groups(self, context: str = "") -> dict[str, list[LearningEvent]]:
        self._buffer.flush()
        events = self.store.query(event_types={"tool_execution"}, limit=1000)
        if context:
            relevant_ids = {
                ranked.event.event_id
                for ranked in rank_learning_events(context, events, min_score=0.05, limit=1000)
            }
            events = [event for event in events if event.event_id in relevant_ids]
        groups: dict[str, list[LearningEvent]] = {}
        for event in events:
            if event.tool_name:
                groups.setdefault(event.tool_name, []).append(event)
        return groups

    @property
    def _executions(self) -> list[dict[str, Any]]:
        self._buffer.flush()
        return [
            {
                "tool_name": event.tool_name,
                "success": event.outcome == TaskOutcome.SUCCESSFUL.value,
                "duration_ms": event.duration_ms,
                "error": event.error_message or "",
                "task_context": event.summary,
                "timestamp": event.created_at,
            }
            for event in self.store.query(event_types={"tool_execution"}, limit=500)
        ]

    @property
    def _chains(self) -> list[dict[str, Any]]:
        return [
            {
                "tools_used": event.metadata.get("tools_used", []),
                "task_description": event.summary,
                "success": event.outcome == TaskOutcome.SUCCESSFUL.value,
                "outcome": event.outcome,
                "timestamp": event.created_at,
            }
            for event in self.store.query(event_types={"task_completion"}, limit=500)
            if event.metadata.get("tools_used")
        ]


_error_analyzer: ErrorAnalyzer | None = None
_few_shot_assembler: FewShotAssembler | None = None
_tool_optimizer: ToolOptimizer | None = None


def get_error_analyzer() -> ErrorAnalyzer:
    global _error_analyzer
    if _error_analyzer is None:
        _error_analyzer = ErrorAnalyzer()
    return _error_analyzer


def record_error(
    error_type: str,
    error_message: str,
    context: dict[str, Any] | None = None,
    correction: str = "",
) -> None:
    from ..agent_config import get_agent_config_manager

    if not get_agent_config_manager().is_learning_module_enabled("error_analysis"):
        return
    get_error_analyzer().record_error(error_type, error_message, context, correction)


def check_similar_error(planned_action: str, tool_name: str = "") -> dict[str, Any]:
    return get_error_analyzer().check_similar_error(planned_action, tool_name)


def get_error_patterns(min_frequency: int = 2) -> list[dict[str, Any]]:
    return get_error_analyzer().get_error_patterns(min_frequency)


def get_few_shot_assembler() -> FewShotAssembler:
    global _few_shot_assembler
    if _few_shot_assembler is None:
        _few_shot_assembler = FewShotAssembler()
    return _few_shot_assembler


def get_examples_for_task(task_description: str, top_k: int = 3) -> list[dict[str, Any]]:
    return get_few_shot_assembler().get_examples_for_task(task_description, top_k)


def inject_examples_into_prompt(
    base_prompt: str,
    task_description: str,
    max_examples: int = 2,
) -> str:
    return get_few_shot_assembler().inject_examples_into_prompt(
        base_prompt,
        task_description,
        max_examples,
    )


def get_tool_optimizer() -> ToolOptimizer:
    global _tool_optimizer
    if _tool_optimizer is None:
        _tool_optimizer = ToolOptimizer()
    return _tool_optimizer


def flush_tool_optimizer() -> bool:
    return _tool_optimizer.flush() if _tool_optimizer is not None else False


def track_tool_execution(
    tool_name: str,
    success: bool,
    duration_ms: float,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    error: str = "",
    task_context: str = "",
    **event_context: Any,
) -> None:
    get_tool_optimizer().track_tool_execution(
        tool_name,
        success,
        duration_ms,
        input_data,
        output_data,
        error,
        task_context,
        **event_context,
    )


def suggest_tool_chain(task_description: str) -> list[str]:
    return get_tool_optimizer().suggest_tool_chain(task_description)


def get_tool_rankings(context: str = "") -> list[dict[str, Any]]:
    return get_tool_optimizer().get_tool_rankings(context)


atexit.register(flush_tool_optimizer)
