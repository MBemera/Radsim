# Rust admission-gate result

Plan item 10 remains intentionally unimplemented. A post-FTS5, post-batching,
post-cache profile did not find a qualifying Python kernel.

The reproducible local workload performs 500 iterations of FTS5 candidate
retrieval over 2,000 learning events, final ranking, tool-schema routing,
canonicalisation, and provider-payload measurement:

```bash
python3 -m benchmarks.profile_local_processing --iterations 500 --events 2000
```

The profile recorded 2.668 seconds of local work. The largest self-time share
for any RadSim Python function was 4.0814%, in bounded-text sanitisation. Final
learning ranking was 1.4047% and FTS5-backed `search_events` Python self-time
was 1.3891%. No stable Python compute kernel reached the plan's 15% gate.

Because the first admission condition failed, adding PyO3, maturin, native
wheels, fallback code, and a second mutation tool would add supply-chain and
maintenance cost without evidence of an end-to-end benefit. No Rust dependency
or native code was added. Machine-readable evidence is stored in
`benchmarks/rust-admission-profile.json`.

Re-run the gate if a future representative profile identifies a different
stable workload. A new proposal must still satisfy every remaining gate:
batch-oriented boundary, under-5% conversion overhead, at least 3x kernel
speedup, at least 10% end-to-end or 30% peak-memory improvement, cross-platform
wheels, and a tested Python fallback.
