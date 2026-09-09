"""Relevance, filtering, and fallback tests for FTS5 candidate retrieval."""

from __future__ import annotations

import sqlite3

import pytest

from radsim.learning import retrieval
from radsim.learning.events import LearningEvent, TaskOutcome
from radsim.learning.retrieval import (
    DEFAULT_CANDIDATE_LIMIT,
    FTS5_ENV_VAR,
    candidate_events,
    fts5_candidates_enabled,
    rank_learning_events,
    tokenize,
    verified_success_events,
)
from radsim.learning.store import (
    MAX_SEARCH_TERMS,
    LearningStore,
    _match_expression,
    fts5_available,
)

pytestmark = pytest.mark.skipif(
    not fts5_available(),
    reason="SQLite build has no FTS5 support",
)

ON = {FTS5_ENV_VAR: "1"}
OFF: dict[str, str] = {}

LABELLED_CORPUS = [
    ("fix-validation", "Fix the python validation failure and run focused tests"),
    ("browser-login", "Automate the browser login flow with playwright selectors"),
    ("docker-deploy", "Deploy the docker container to the staging environment"),
    ("sql-index", "Add a database index to speed up the slow sqlite query"),
    ("memo-refactor", "Refactor the memoization helper to remove nested branches"),
]

LABELLED_QUERIES = [
    ("validation failure in python tests", "fix-validation"),
    ("playwright browser selectors for login", "browser-login"),
    ("staging docker deployment", "docker-deploy"),
    ("slow sqlite query needs an index", "sql-index"),
    ("remove nesting from the memoization helper", "memo-refactor"),
]


def _store(tmp_path, name="search"):
    return LearningStore(storage_dir=tmp_path / name, max_events=10_000, migrate_legacy=False)


def _event(event_id, summary, **overrides):
    fields = {
        "event_id": event_id,
        "task_id": overrides.pop("task_id", f"task-{event_id}"),
        "event_type": overrides.pop("event_type", "task_example"),
        "task_category": overrides.pop("task_category", "general"),
        "outcome": overrides.pop("outcome", TaskOutcome.SUCCESSFUL),
        "summary": summary,
    }
    fields.update(overrides)
    return LearningEvent.create(**fields)


def _corpus_store(tmp_path, filler=0):
    store = _store(tmp_path)
    events = [_event(event_id, summary) for event_id, summary in LABELLED_CORPUS]
    events.extend(
        _event(f"filler-{index:04d}", f"unrelated maintenance chore number {index}")
        for index in range(filler)
    )
    store.append_many(events)
    return store


def _ids(events):
    return [event.event_id for event in events]


def test_match_expression_quotes_every_term():
    assert _match_expression(["alpha", "beta"]) == '"alpha" OR "beta"'


def test_match_expression_deduplicates_and_sorts():
    assert _match_expression(["beta", "alpha", "beta"]) == '"alpha" OR "beta"'


def test_match_expression_is_empty_without_usable_terms():
    assert _match_expression([]) == ""
    assert _match_expression(["", "   "]) == ""
    assert _match_expression([None, 42]) == ""


def test_match_expression_drops_terms_containing_a_quote():
    assert _match_expression(['bad"term', "good"]) == '"good"'


def test_match_expression_is_bounded():
    expression = _match_expression(f"term{index:03d}" for index in range(MAX_SEARCH_TERMS * 3))

    assert expression.count(" OR ") == MAX_SEARCH_TERMS - 1


def test_fts5_operators_in_a_term_are_matched_as_text(tmp_path):
    store = _corpus_store(tmp_path)

    assert store.search_events(["NEAR"], event_types={"task_example"}) == []
    assert store.search_events(["OR"], event_types={"task_example"}) == []
    assert store.search_events(["*"], event_types={"task_example"}) == []


def test_search_ranks_the_matching_event_first(tmp_path):
    store = _corpus_store(tmp_path, filler=300)

    candidates = store.search_events(
        tokenize("validation failure in python tests"),
        event_types={"task_example"},
        limit=DEFAULT_CANDIDATE_LIMIT,
    )

    assert candidates[0].event_id == "fix-validation"


def test_search_filters_by_event_type(tmp_path):
    store = _store(tmp_path)
    store.append_many(
        [
            _event("example", "docker deployment notes", event_type="task_example"),
            _event("error", "docker deployment notes", event_type="error"),
        ]
    )

    candidates = store.search_events(tokenize("docker deployment"), event_types={"error"})

    assert _ids(candidates) == ["error"]


def test_search_filters_by_outcome(tmp_path):
    store = _store(tmp_path)
    store.append_many(
        [
            _event("good", "docker deployment notes", outcome=TaskOutcome.SUCCESSFUL),
            _event("bad", "docker deployment notes", outcome=TaskOutcome.FAILED),
        ]
    )

    candidates = store.search_events(
        tokenize("docker deployment"),
        event_types={"task_example"},
        outcomes={TaskOutcome.SUCCESSFUL.value},
    )

    assert _ids(candidates) == ["good"]


def test_search_matches_error_text_and_tool_name(tmp_path):
    store = _store(tmp_path)
    store.append_many(
        [
            _event(
                "tool-error",
                "a task summary with no distinguishing words",
                event_type="error",
                tool_name="run_shell_command",
                error_type="PermissionError",
                error_message="the sandbox refused the write",
            )
        ]
    )

    assert _ids(store.search_events(["permissionerror"], event_types={"error"})) == ["tool-error"]
    assert _ids(store.search_events(["run_shell_command"], event_types={"error"})) == ["tool-error"]
    assert _ids(store.search_events(["sandbox"], event_types={"error"})) == ["tool-error"]


def test_search_is_deterministic_for_identical_text(tmp_path):
    store = _store(tmp_path)
    store.append_many([_event(f"tie-{index}", "identical searchable text") for index in range(6)])

    first = _ids(store.search_events(["identical"], event_types={"task_example"}))
    second = _ids(store.search_events(["identical"], event_types={"task_example"}))

    assert first == second == sorted(first)


def test_search_handles_a_non_ascii_query(tmp_path):
    store = _store(tmp_path)
    store.append_many([_event("unicode", "corrige la validación en español")])

    assert _ids(store.search_events(["validación"], event_types={"task_example"})) == ["unicode"]


def test_search_handles_punctuation_heavy_and_empty_queries(tmp_path):
    store = _corpus_store(tmp_path)

    assert store.search_events(tokenize("!!! ??? *** ---"), event_types={"task_example"}) == []
    assert store.search_events(tokenize(""), event_types={"task_example"}) == []
    assert store.search_events(tokenize("   "), event_types={"task_example"}) == []


def test_search_respects_the_candidate_limit(tmp_path):
    store = _store(tmp_path)
    store.append_many(
        [_event(f"many-{index:03d}", "shared searchable text") for index in range(40)]
    )

    candidates = store.search_events(["shared"], event_types={"task_example"}, limit=5)

    assert len(candidates) == 5


def test_the_index_backfills_events_written_before_it_existed(tmp_path):
    store = _corpus_store(tmp_path)

    assert store._search_index_ready is False

    candidates = store.search_events(tokenize("docker staging"), event_types={"task_example"})

    assert store._search_index_ready is True
    assert "docker-deploy" in _ids(candidates)


def test_the_index_tracks_later_inserts(tmp_path):
    store = _corpus_store(tmp_path)
    store.search_events(["docker"], event_types={"task_example"})

    store.append(_event("later", "a brand new kubernetes rollout note"))

    assert _ids(store.search_events(["kubernetes"], event_types={"task_example"})) == ["later"]


def test_the_index_tracks_deletes(tmp_path):
    store = _store(tmp_path)
    store.append_many([_event("removable", "a deletable kubernetes note", event_type="error")])
    assert _ids(store.search_events(["kubernetes"], event_types={"error"})) == ["removable"]

    store.delete(event_types={"error"})

    assert store.search_events(["kubernetes"], event_types={"error"}) == []


def test_search_returns_nothing_when_fts5_is_unavailable(tmp_path, monkeypatch):
    store = _corpus_store(tmp_path)
    monkeypatch.setattr("radsim.learning.store.fts5_available", lambda: False)

    assert store.search_events(["docker"], event_types={"task_example"}) == []


def test_search_returns_nothing_when_the_query_fails(tmp_path, monkeypatch):
    store = _corpus_store(tmp_path)
    store.search_events(["docker"], event_types={"task_example"})

    def failing_connect():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "_connect", failing_connect)

    assert store.search_events(["docker"], event_types={"task_example"}) == []


def test_the_flag_is_off_by_default():
    assert fts5_candidates_enabled({}) is False
    assert fts5_candidates_enabled({FTS5_ENV_VAR: "0"}) is False
    assert fts5_candidates_enabled({FTS5_ENV_VAR: "1"}) is True
    assert fts5_candidates_enabled({FTS5_ENV_VAR: " On "}) is True


def test_candidates_use_the_full_scan_when_the_flag_is_off(tmp_path):
    store = _corpus_store(tmp_path, filler=40)

    events = candidate_events(
        store, "docker staging", event_types={"task_example"}, limit=500, environ=OFF
    )

    assert len(events) == len(LABELLED_CORPUS) + 40


def test_candidates_narrow_when_the_flag_is_on(tmp_path):
    store = _corpus_store(tmp_path, filler=40)

    events = candidate_events(
        store, "docker staging", event_types={"task_example"}, limit=500, environ=ON
    )

    assert len(events) <= DEFAULT_CANDIDATE_LIMIT
    assert "docker-deploy" in _ids(events)


def test_candidates_fall_back_when_search_finds_nothing(tmp_path):
    store = _corpus_store(tmp_path, filler=10)

    events = candidate_events(
        store, "zzzz nonexistent terminology", event_types={"task_example"}, limit=500, environ=ON
    )

    assert len(events) == len(LABELLED_CORPUS) + 10


def test_candidates_fall_back_without_usable_query_terms(tmp_path):
    store = _corpus_store(tmp_path, filler=5)

    events = candidate_events(store, "!!! ???", event_types={"task_example"}, limit=500, environ=ON)

    assert len(events) == len(LABELLED_CORPUS) + 5


def test_candidates_fall_back_when_fts5_is_unavailable(tmp_path, monkeypatch):
    store = _corpus_store(tmp_path, filler=5)
    monkeypatch.setattr("radsim.learning.store.fts5_available", lambda: False)

    events = candidate_events(
        store, "docker staging", event_types={"task_example"}, limit=500, environ=ON
    )

    assert len(events) == len(LABELLED_CORPUS) + 5


@pytest.mark.parametrize(("query", "expected_id"), LABELLED_QUERIES)
def test_narrowed_ranking_matches_the_full_scan_on_a_labelled_corpus(tmp_path, query, expected_id):
    store = _corpus_store(tmp_path, filler=200)

    narrowed = candidate_events(store, query, event_types={"task_example"}, limit=500, environ=ON)
    scanned = candidate_events(store, query, event_types={"task_example"}, limit=500, environ=OFF)

    narrowed_top = rank_learning_events(query, narrowed, limit=1)
    scanned_top = rank_learning_events(query, scanned, limit=1)

    assert narrowed_top[0].event.event_id == expected_id
    assert scanned_top[0].event.event_id == expected_id


def test_narrowing_preserves_revert_suppression(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.append_many(
        [
            _event("kept", "fix the flaky docker integration test", task_id="task-kept"),
            _event("reverted", "fix the flaky docker integration test", task_id="task-reverted"),
            _event(
                "revert-record",
                "user reverted the change",
                event_type="task_revert",
                task_id="task-reverted",
                outcome=TaskOutcome.REVERTED,
            ),
        ]
    )
    monkeypatch.setenv(FTS5_ENV_VAR, "1")

    events = verified_success_events(
        store,
        event_types={"task_example"},
        limit=500,
        query="flaky docker integration test",
    )

    assert _ids(events) == ["kept"]


def test_narrowing_preserves_success_weighting(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.append_many(
        [
            _event("failed", "resolve the docker network timeout", outcome=TaskOutcome.FAILED),
            _event("passed", "resolve the docker network timeout", outcome=TaskOutcome.SUCCESSFUL),
        ]
    )
    monkeypatch.setenv(FTS5_ENV_VAR, "1")

    events = candidate_events(
        store, "docker network timeout", event_types={"task_example"}, limit=500
    )
    ranked = rank_learning_events("docker network timeout", events, limit=1)

    assert ranked[0].event.event_id == "passed"


def test_narrowing_preserves_category_weighting(tmp_path):
    store = _store(tmp_path)
    store.append_many(
        [
            _event("feature", "handle the docker network timeout", task_category="feature"),
            _event("bugfix", "handle the docker network timeout", task_category="bug_fix"),
        ]
    )

    events = candidate_events(
        store, "docker network timeout", event_types={"task_example"}, limit=500, environ=ON
    )
    ranked = rank_learning_events(
        "docker network timeout", events, task_category="bug_fix", limit=1
    )

    assert ranked[0].event.event_id == "bugfix"


def test_check_similar_error_still_finds_a_match_with_narrowing(tmp_path, monkeypatch):
    monkeypatch.setenv(FTS5_ENV_VAR, "1")
    analyzer = retrieval.ErrorAnalyzer(storage_dir=tmp_path)
    analyzer.record_error(
        error_type="PermissionError",
        error_message="the sandbox refused the write to /etc",
        context={"action": "tool_execution", "tool": "write_file"},
    )

    result = analyzer.check_similar_error("write a file into /etc", tool_name="write_file")

    assert result["error_found"] is True
    assert result["error_type"] == "PermissionError"
