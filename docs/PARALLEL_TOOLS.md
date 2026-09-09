# Bounded Parallel Read-Only Tools

A tool round of four independent `read_file` calls used to cost four sequential
waits. This runs the round's leading independent read-only calls on a bounded
pool instead.

Off by default. Parallelism changes **when** a read happens, never the order
anything is recorded in.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `RADSIM_PARALLEL_TOOLS` | unset (off) | `1`, `true`, `yes`, or `on` enables bounded parallel reads |

Worker count is fixed at 4, the plan's starting value.

## Measured effect

Simulated per-call I/O latency, 5 rounds each
(`benchmarks/parallel-tools-baseline.json`):

| Read calls | Per-call latency | Serial | Parallel | Speed-up |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 20 ms | 50.8 ms | 26.3 ms | 1.9× |
| 4 | 20 ms | 95.9 ms | 26.6 ms | 3.6× |
| 8 | 20 ms | 194.4 ms | 53.1 ms | 3.7× |
| 4 | 50 ms | 216.2 ms | 54.3 ms | 4.0× |

Speed-up is capped by the worker count: a round of N reads costs about
`ceil(N / 4)` sequential waits.

## The seven conditions

A call runs concurrently only when **all** of these hold (plan section 3.3):

1. Its name is in `PARALLEL_SAFE_TOOLS`, an explicit allowlist of 15 read-only
   inspection and repository-metadata tools. A test asserts the allowlist is a
   subset of `READ_ONLY_TOOLS` and disjoint from `CONFIRMATION_TOOLS`.
2. The tool is read-only with no implicit mutation.
3. No call in the round can consume another's result — the provider emits them
   together, so this holds structurally.
4. It needs no user confirmation. `_protected_read_targets` is evaluated
   **before** dispatch, so a read of a protected path never reaches a
   concurrent prompt; screening failure is treated as unsafe.
5. Policy and secret checks complete before dispatch, for the same reason.
6. No order-sensitive hook is registered. `_order_sensitive_hooks_present`
   checks both in-process `pre_tool`/`post_tool` hooks and enabled user hooks,
   and assumes hooks are present if inspection fails.
7. Results are returned in the provider's original order, by index.

Only the **leading contiguous run** of the round is grouped. A write, shell
command, test run, or git mutation anywhere in the round ends the group at that
point, so nothing reads state an earlier call in the same round may have
changed.

## What stays serial

The parallel phase computes results only. The existing serial loop still owns
every ordered side effect: printing the call and its result, outcome tracking,
learning events, Telegram notifications, image-block extraction, telemetry, and
appending `tool_result` blocks. An end-to-end test asserts the message history
is byte-identical with the flag on and off.

## Cancellation, failure, and timeouts

An interrupt stops further dispatch and cancels work that has not started. Work
already running is allowed to finish, deliberately: a Python thread cannot be
killed safely, and abandoning one would leave a `tool_use` with no matching
`tool_result` and corrupt the conversation.

A failing call becomes an error result without affecting the others —
`_execute_tool_guarded` already converts crashes. Rate-limit, circuit-breaker,
and budget exceptions still propagate as deliberate stops. Any unexpected
scheduler failure falls back to serial execution for the round.

**There is no wall-clock timeout**, and this departs from plan section 9.2. A
timeout cannot stop a running Python thread; it would only stop *waiting* for
one, orphaning a tool call whose result nothing collects and breaking
`tool_use`/`tool_result` pairing. Cancellation of unstarted work and partial
failure are implemented in full.

## Telemetry

With `RADSIM_PERFORMANCE_TELEMETRY=1`, a grouped round emits
`tool_parallel_round` with the total call count, group size, worker count,
completed count, and duration.

## Verifying

```bash
python -m pytest tests/test_tool_scheduler.py tests/property/test_tool_scheduler_invariants.py -q -p no:randomly
python -m pytest tests/test_agent_harness.py -q -p no:randomly -k Parallel
```
