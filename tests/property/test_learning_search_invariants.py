"""Property tests for FTS5 candidate-retrieval invariants."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from radsim.learning.events import LearningEvent, TaskOutcome
from radsim.learning.retrieval import (
    DEFAULT_CANDIDATE_LIMIT,
    FTS5_ENV_VAR,
    candidate_events,
    rank_learning_events,
    tokenize,
)
from radsim.learning.store import MAX_SEARCH_TERMS, LearningStore, _match_expression, fts5_available

pytestmark = pytest.mark.skipif(
    not fts5_available(),
    reason="SQLite build has no FTS5 support",
)

PROPERTY_TEST_SETTINGS = settings(max_examples=50, deadline=None)
ON = {FTS5_ENV_VAR: "1"}
OFF: dict[str, str] = {}

SUMMARIES = (
    "fix the python validation failure and run tests",
    "deploy the docker container to staging",
    "add a sqlite index for the slow query",
    "automate the browser login with playwright",
    "refactor the nested memoization helper",
)

search_text = st.one_of(
    st.text(max_size=80),
    st.lists(st.sampled_from(SUMMARIES), max_size=3).map(" ".join),
)

term_list = st.lists(st.text(max_size=12), max_size=40)


def _store(tmp_path_factory, name):
    store = LearningStore(
        storage_dir=tmp_path_factory.mktemp(name),
        max_events=10_000,
        migrate_legacy=False,
    )
    store.append_many(
        [
            LearningEvent.create(
                event_id=f"event-{index:04d}",
                task_id=f"task-{index}",
                event_type="task_example",
                task_category="general",
                outcome=TaskOutcome.SUCCESSFUL,
                summary=SUMMARIES[index % len(SUMMARIES)],
            )
            for index in range(40)
        ]
    )
    return store


@PROPERTY_TEST_SETTINGS
@given(terms=term_list)
def test_a_match_expression_is_always_balanced_and_bounded(terms):
    expression = _match_expression(terms)

    assert expression.count('"') % 2 == 0
    if expression:
        assert expression.count(" OR ") < MAX_SEARCH_TERMS
        for quoted in expression.split(" OR "):
            assert quoted.startswith('"') and quoted.endswith('"')
            assert '"' not in quoted[1:-1]


@PROPERTY_TEST_SETTINGS
@given(terms=term_list)
def test_search_never_raises_on_arbitrary_terms(tmp_path_factory, terms):
    store = _store(tmp_path_factory, "arbitrary")

    candidates = store.search_events(terms, event_types={"task_example"})

    assert all(isinstance(event, LearningEvent) for event in candidates)


@PROPERTY_TEST_SETTINGS
@given(query=search_text, limit=st.integers(min_value=1, max_value=50))
def test_candidates_are_always_real_stored_events(tmp_path_factory, query, limit):
    store = _store(tmp_path_factory, "identity")
    stored_ids = {event.event_id for event in store.query(limit=1_000)}

    candidates = store.search_events(tokenize(query), event_types={"task_example"}, limit=limit)

    returned = [event.event_id for event in candidates]
    assert set(returned) <= stored_ids
    assert len(returned) == len(set(returned))
    assert len(returned) <= limit


@PROPERTY_TEST_SETTINGS
@given(query=search_text)
def test_search_is_deterministic(tmp_path_factory, query):
    store = _store(tmp_path_factory, "deterministic")
    terms = tokenize(query)

    first = store.search_events(terms, event_types={"task_example"})
    second = store.search_events(terms, event_types={"task_example"})

    assert [event.event_id for event in first] == [event.event_id for event in second]


@PROPERTY_TEST_SETTINGS
@given(query=search_text)
def test_narrowing_never_returns_more_than_the_candidate_limit(tmp_path_factory, query):
    store = _store(tmp_path_factory, "bounded")

    events = candidate_events(store, query, event_types={"task_example"}, limit=500, environ=ON)

    assert len(events) <= max(DEFAULT_CANDIDATE_LIMIT, len(store.query(limit=1_000)))


@PROPERTY_TEST_SETTINGS
@given(query=search_text)
def test_narrowing_never_produces_an_empty_candidate_set(tmp_path_factory, query):
    store = _store(tmp_path_factory, "nonempty")

    narrowed = candidate_events(store, query, event_types={"task_example"}, limit=500, environ=ON)
    scanned = candidate_events(store, query, event_types={"task_example"}, limit=500, environ=OFF)

    assert narrowed
    assert {event.event_id for event in narrowed} <= {event.event_id for event in scanned}


@PROPERTY_TEST_SETTINGS
@given(query=search_text)
def test_ranking_a_narrowed_set_only_returns_candidates(tmp_path_factory, query):
    """The ranker itself is not order-stable across calls.

    ``_recency_score`` scores against the current time, so two events with
    otherwise equal scores can swap places between invocations. That is the
    existing ranker's design, not something narrowing introduces, so the
    invariant here is provenance: a ranked result is always drawn from the
    candidate set it was given.
    """
    store = _store(tmp_path_factory, "ranking")
    events = candidate_events(store, query, event_types={"task_example"}, limit=500, environ=ON)

    ranked = rank_learning_events(query, events, limit=3)

    assert {item.event.event_id for item in ranked} <= {event.event_id for event in events}
    assert len(ranked) <= 3
