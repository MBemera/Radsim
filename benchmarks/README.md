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
