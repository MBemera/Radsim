"""Property tests for bounded-cache invariants."""

from __future__ import annotations

from collections import OrderedDict

from hypothesis import given, settings
from hypothesis import strategies as st

from radsim.bounded_cache import MISSING, BoundedCache, path_signature

PROPERTY_TEST_SETTINGS = settings(max_examples=100, deadline=None)

operations = st.lists(
    st.tuples(
        st.sampled_from(["set", "get"]),
        st.integers(min_value=0, max_value=20),
    ),
    max_size=60,
)


@PROPERTY_TEST_SETTINGS
@given(steps=operations, max_entries=st.integers(min_value=1, max_value=8))
def test_the_cache_never_exceeds_its_bound(steps, max_entries):
    cache = BoundedCache(max_entries=max_entries)

    for action, key in steps:
        if action == "set":
            cache.set(key, key * 2)
        else:
            cache.get(key)
        assert cache.stats()["entries"] <= max_entries


@PROPERTY_TEST_SETTINGS
@given(steps=operations, max_entries=st.integers(min_value=1, max_value=8))
def test_counters_always_account_for_every_lookup(steps, max_entries):
    cache = BoundedCache(max_entries=max_entries)
    lookups = 0

    for action, key in steps:
        if action == "set":
            cache.set(key, key)
        else:
            cache.get(key)
            lookups += 1

    stats = cache.stats()
    assert stats["hits"] + stats["misses"] == lookups
    assert 0.0 <= stats["hit_rate"] <= 1.0


@PROPERTY_TEST_SETTINGS
@given(steps=operations, max_entries=st.integers(min_value=1, max_value=8))
def test_a_returned_value_is_always_the_one_stored(steps, max_entries):
    cache = BoundedCache(max_entries=max_entries)
    written = {}

    for action, key in steps:
        if action == "set":
            cache.set(key, key * 3)
            written[key] = key * 3
        else:
            value = cache.get(key)
            if value is not MISSING:
                assert value == written[key]


@PROPERTY_TEST_SETTINGS
@given(keys=st.lists(st.integers(min_value=0, max_value=50), max_size=40))
def test_the_most_recently_stored_key_is_always_present(keys):
    cache = BoundedCache(max_entries=4)

    for key in keys:
        cache.set(key, key)

    if keys:
        assert cache.get(keys[-1]) == keys[-1]


@PROPERTY_TEST_SETTINGS
@given(
    keys=st.lists(st.integers(min_value=0, max_value=50), min_size=1, max_size=40),
    max_entries=st.integers(min_value=1, max_value=6),
)
def test_the_cache_matches_a_reference_lru_model(keys, max_entries):
    cache = BoundedCache(max_entries=max_entries)
    model: OrderedDict[int, int] = OrderedDict()
    insertions = 0

    for key in keys:
        cache.set(key, key)
        if key not in model:
            insertions += 1
        model[key] = key
        model.move_to_end(key)
        while len(model) > max_entries:
            model.popitem(last=False)

    stats = cache.stats()
    assert stats["entries"] == len(model)
    assert stats["entries"] + stats["evictions"] == insertions
    for key in model:
        assert cache.get(key) == key


@PROPERTY_TEST_SETTINGS
@given(body=st.text(max_size=60))
def test_a_path_signature_is_stable_while_a_file_is_unchanged(tmp_path_factory, body):
    target = tmp_path_factory.mktemp("signature") / "file.txt"
    target.write_text(body)

    assert path_signature(target) == path_signature(target)
    assert path_signature(target)[0] == str(target)
