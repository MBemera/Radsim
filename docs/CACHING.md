# Schema, Hook, and Repository Metadata Caches

Three things were recomputed on a fixed cadence regardless of whether their
inputs had changed: tool schemas on every provider request, hook definitions
twice per tool call, and repository metadata per lookup.

All three now share one bounded cache that reports its own hit rate. No feature
flag — these are pure memoisations with explicit invalidation, and a cache that
cannot serve a stale answer needs no opt-in.

## Measured effect

`benchmarks/cache-baseline.json`. Cold is the median of 30 single calls each
preceded by a cache clear outside the timer; warm is the mean of 300 cached
calls. The machine was running a concurrent mutation sweep, so the ratios are
like-for-like but the absolute values are not a clean baseline.

| Cache | Case | Cold | Warm | Speed-up |
| --- | --- | ---: | ---: | ---: |
| Tool schema | all 72 tools | 1.78 ms | 0.045 ms | 40× |
| Tool schema | routed 15 tools | 0.284 ms | 0.018 ms | 15× |
| User hooks | 10 hooks | 11.4 ms | 0.16 ms | 71× |

The hook figure is the largest single win here and the least obvious. Hook
definitions are read and revalidated on both `pre_tool` and `post_tool`, so a
round of ten tool calls paid that cost twenty times.

## What is cached, and how it is invalidated

| Cache | Key | Invalidated by | Bound |
| --- | --- | --- | ---: |
| Tool schema | registry version + selected tool names | registering, removing, or toggling a tool; MCP connect and disconnect | 32 |
| User hooks | hooks.json modification signature | any change to the file's mtime or size; `save_user_hooks` clears explicitly | 4 |
| Project detection | working directory + source file signatures | any tracked file changing | 32 |
| Prompt fragment | working directory + source file signatures | any tracked file changing | 32 |

`registry_version()` is a counter in `radsim/tools/__init__.py` bumped by every
path that mutates `TOOL_DEFINITIONS`. It cannot see a change the registry does
not make, so MCP `connect` and `disconnect` call `clear_schema_cache()` — an
MCP server keeps its tool names across a reconnect, so a replaced schema body
would otherwise be invisible to the key.

`save_user_hooks` clears the hook cache explicitly rather than relying on the
new mtime: a write within the filesystem's timestamp resolution could otherwise
produce the signature already held.

## Aliasing

Both the schema and hook caches return a copy of the cached list. A caller that
sorts, appends to, or clears the returned list cannot reach the entry every
later request reads. This was a real bug during development — the first version
copied only on the hit path, so the very first caller could corrupt the entry,
and `test_a_cached_schema_list_cannot_be_corrupted_by_a_caller` catches it.

## Bounds and telemetry

`BoundedCache` is an LRU with hit, miss, and eviction counters. Every cache is
bounded, so a long session that moves between projects cannot grow entries
without limit.

With `RADSIM_PERFORMANCE_TELEMETRY=1`, each turn ends with one `cache_stats`
event per cache carrying entries, hits, misses, evictions, and hit rate — so a
cache that never hits, or one evicting constantly because it is sized wrong,
shows up as data rather than an assumption.

## Verifying

```bash
python -m pytest tests/test_bounded_cache.py tests/property/test_bounded_cache_invariants.py -q -p no:randomly
```
