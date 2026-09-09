# Batched Learning Persistence

Every tool call used to open a SQLite connection, insert one row, and commit.
Commit overhead dominates small writes, so a tool round of 20 calls paid 20
fsyncs. `LearningEventBuffer` queues tool-execution events and writes them in one
transaction per flush.

## Measured effect

Wall clock on this machine, 10 rounds per configuration
(`benchmarks/learning-batch-baseline.json`):

| Events per round | One transaction per event | One transaction per round | Speed-up |
| ---: | ---: | ---: | ---: |
| 20 | 51.5 ms | 4.1 ms | 12.5× |
| 100 | 279.0 ms | 12.2 ms | 22.8× |

## What is buffered

Only `tool_execution` events, the high-volume path. Task completions, errors,
reverts, feedback, and proposals still write immediately — they are low-volume
and a later decision can depend on them.

## When the queue is flushed

Buffering trades per-event durability for throughput, so the queue is drained
everywhere a later decision could read it:

| Point | Where |
| --- | --- |
| Batch is full | `LearningEventBuffer.add`, at 20 queued events |
| End of a tool round | `_process_tool_calls`, before the next provider request |
| Turn completion or cancellation | `flush_tool_optimizer()` in `process_message` |
| Task chain completion | `ToolOptimizer.complete_task_chain` |
| Before any read of buffered data | `_tool_groups`, `_executions`, `suggest_tool_chain` |
| Data reset | `ToolOptimizer.clear_data` discards the queue too |
| Process shutdown | the pre-existing `atexit.register(flush_tool_optimizer)` |

## Failure behaviour

Validation runs in `add`, before the transaction, so one malformed event cannot
roll back a batch of good ones — it is rejected at the door and `add` returns
`False`.

`append_many` commits once. A failed transaction writes nothing, so the batch is
returned to the *front* of the queue and retried on the next flush; ordering
survives the retry. The queue is bounded at 500 events and drops the oldest on
overflow, counting them in `dropped_events`, so a database that stays unwritable
cannot grow memory without limit.

## Telemetry

With `RADSIM_PERFORMANCE_TELEMETRY=1`, every flush emits a `learning_flush`
event: `batch_size`, `inserted_events`, `duration_ms`, `queue_depth`,
`dropped_events`, `success`, and `error_type`.

## Mutation testing

`radsim/learning/buffer.py` is in the Tier 1 mutation set. Score at the time of
writing: **94 killed of 114 considered, 82.5%**, against the plan's 80% Tier 1
target.

All 20 survivors were inspected as diffs and are equivalent mutants:

- 18 mutate `logger.debug` message text or its arguments. They change no state,
  no return value, and no persisted row.
- `_discard_overflow` `overflow <= 0` → `overflow < 0`. At `overflow == 0` the
  mutant runs `del self._pending[:0]` and `dropped_events += 0`, both no-ops, so
  the reachable state is identical.
- `_emit_flush_event` `* 1000` → `* 1001`. A 0.1% error in a reported duration,
  below the resolution any assertion on wall-clock timing can distinguish
  without becoming flaky.

```bash
python -m mutmut run 'radsim.learning.buffer.*'
python -m mutmut export-cicd-stats
python scripts/mutation_ci.py check mutants/mutmut-cicd-stats.json --minimum 0.80
```
