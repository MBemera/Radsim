# RadSim Performance Benchmarks

Install the development dependencies and run:

```bash
mkdir -p benchmark-results
python -m pytest benchmarks -q \
  --benchmark-only \
  --benchmark-json=benchmark-results/baseline.json
```

The suite measures warm prompt construction, tool-schema processing, learning
ranking at representative corpus sizes, SQLite write transaction boundaries,
and disabled telemetry overhead. Provider and real tool latency are excluded.

Benchmark JSON is generated as a CI artifact. Results should only be compared
when Python, operating system, processor class, and benchmark settings match.

Run the long-session memory release gate separately:

```bash
python3 -m benchmarks.memory_soak --turns 1000 --warmup-turns 1000
```

This records resident memory, Python allocations, cache sizes, file descriptors,
threads, subprocesses, SQLite connections, retained messages, and background
job state after the process has reached its configured bounds.

Re-run the optional Rust admission profile with:

```bash
python3 -m benchmarks.profile_local_processing --iterations 500 --events 2000
```

Rust remains out of scope unless one stable Python kernel reaches 15% of the
representative local profile and every later admission gate can also be met.
