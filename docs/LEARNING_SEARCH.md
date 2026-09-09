# FTS5 Candidate Retrieval

Ranking a learning query used to pull every stored event of the right type — up
to 1,000 rows — and score all of them with the pure-Python TF-IDF ranker. SQLite
FTS5 runs in native C and narrows that to a short candidate list first.

This is a **first-stage filter only**. The Python ranker still applies the
outcome, recency, category, and revert weighting; FTS5 only decides which events
it gets to see.

Off by default.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `RADSIM_LEARNING_FTS5` | unset (off) | `1`, `true`, `yes`, or `on` narrows candidates with FTS5 |

## Measured effect

Retrieval plus ranking, 20 rounds per configuration
(`benchmarks/fts5-retrieval-baseline.json`):

| Stored records | Python full scan | FTS5 candidates | Speed-up |
| ---: | ---: | ---: | ---: |
| 500 | 102.7 ms | 2.6 ms | 40× |
| 2,000 | 438.6 ms | 3.1 ms | 139× |

Absolute numbers are higher than the plan's section 2 baseline because these
include the store fetch as well as ranking, and the machine was under load. The
ratio is what the run establishes: both columns were measured back to back on
the same corpus.

**Relevance: 10 of 10.** On a labelled corpus of five documents plus filler, at
both corpus sizes, the narrowed ranking returned the same top result as the full
scan, and both matched the labelled expectation.

## How it works

1. A standalone FTS5 table, `learning_events_fts`, indexes a searchable
   projection of each event: summary, tool name, error type, error message, and
   metadata.
2. Two SQLite triggers keep it in sync with `learning_events` on insert and
   delete, so the index cannot drift from the table. Events written before the
   index existed are backfilled the first time it is built.
3. `LearningStore.search_events` joins the FTS5 match against the events table,
   applies the same event-type and outcome filters as `query`, orders by
   `bm25` with `event_id` as a deterministic tie-break, and returns about 20
   candidates.
4. `candidate_events` hands those to the unchanged ranker.

The index is created lazily on first search, so a session that never enables the
flag pays no write cost for the triggers.

## Falling back

`candidate_events` returns the full bounded scan whenever narrowing is not
usable — the flag is off, the SQLite build has no FTS5, the query yields no
usable terms, the FTS5 query errors, or the search matched nothing. An empty
search result never reaches the ranker as "no relevant events exist".

## Query safety

Terms come from the existing `tokenize()`, and `_match_expression` emits each as
a quoted FTS5 string literal. Operators (`OR`, `NEAR`, `*`), punctuation, and
non-ASCII text are matched as text rather than parsed as syntax, and terms
containing a double quote are dropped. The expression is also bound as a
parameter. Term count is capped at 32.

## Verifying

```bash
python -m pytest tests/test_learning_search.py tests/property/test_learning_search_invariants.py -q -p no:randomly
```

The suite covers the section 8.2 quality list: labelled relevance cases,
event-type and outcome filtering, recency/success/category weighting through the
ranker, revert suppression, empty and punctuation-heavy and non-ASCII queries,
deterministic tie-breaking, index backfill and trigger sync, and every fallback
path. Tests skip automatically on a SQLite build without FTS5.
