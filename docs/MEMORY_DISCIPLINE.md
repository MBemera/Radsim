# Memory discipline and soak gate

RadSim now applies explicit process-lifetime bounds to every mutable collection
identified by performance-plan item 9. The limits are deliberately simple and
observable.

| State | Bound | Release behaviour |
| --- | ---: | --- |
| Retained conversation messages | 400 | Evicts the oldest complete exchange without splitting tool-use/result pairs |
| Serialized tool-result text | 100,000 characters | Replaces overflow with valid JSON containing a preview and truncation metadata |
| Per-turn outcome evidence | 200 tool results | Retains aggregate success, failure, and failed-verification state |
| Finished background jobs | 100 | Evicts the earliest finished job; running work is never evicted |
| Injected background-job identifiers | 100 | Reconciles identifiers against retained jobs at collection time |
| Pending user shell contexts | 32 | Drops the oldest context before the next model turn |
| Repository symbol cache | 512 | Shared LRU eviction and counters |
| Skill documentation cache | 32 | Shared LRU eviction and counters |

Processed image bytes are replaced with a small history marker after a turn.
This keeps the model-visible result for the current request while avoiding
base64 payload retention for the life of the session.

The rest of the item-9 checklist was verified without another storage layer:

- extension reloads deactivate owned hooks and remove the previous module from
  `sys.modules`; a repeated-reload test proves that only the current module is
  retained
- undo checkpoints already keep 20 entries per project and delete old snapshot
  files; patch parser metadata remains request-local
- normalized provider response dictionaries remain request-local; only bounded
  message content is retained
- runtime project, prompt, schema, and user-hook caches were already bounded and
  now report alongside repository and skill-cache statistics

## Reproduce the release gate

```bash
python3 -m benchmarks.memory_soak --turns 1000 --warmup-turns 1000
```

The 28 August 2026 macOS run passed every check. After warm-up, resident memory
grew 1.0755%, live Python allocations fell 6.0753%, and file descriptors,
threads, subprocesses, and SQLite connection counts did not increase. Its
machine-readable evidence is stored in
`benchmarks/memory-soak-1000-turns.json`.

The 29 August 2026 Linux run on Python 3.12.13 also passed every check. After
warm-up, resident memory grew 0.8374%, live Python allocations fell 6.1106%, and
the file-descriptor count stayed at four. Threads, subprocesses, SQLite
connections, messages, background jobs, injected identifiers, and every
exercised cache stayed within their limits. Its evidence is stored in
`benchmarks/memory-soak-linux-python312.json`.

The soak uses mocked provider turns and tool results. It proves process-state
retention, not live provider SDK behaviour or every operating system. Native
Windows evidence remains to be collected in a Windows environment.

## Security and rollback

Retention telemetry records counts only. It never records prompts, tool
arguments, tool output, image bytes, secrets, or file content. Skill names are
validated before path construction so a lookup cannot escape the packaged
skills directory.

Rollback is a normal revert of the item-9 commit. There is no hidden feature
flag because the limits prevent resource exhaustion and preserve protocol-safe
tool exchanges; disabling them would restore known unbounded state.
