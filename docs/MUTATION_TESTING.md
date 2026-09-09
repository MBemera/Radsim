# Mutation and Property Testing

Install the test and mutation dependencies:

```bash
python -m pip install -e ".[dev,mutation]"
```

Run deterministic property tests:

```bash
python -m pytest tests/property -q -p no:randomly
```

Run the Tier 1 mutation set on Linux, macOS, or WSL:

```bash
mutmut run --max-children 4
mutmut export-cicd-stats
python scripts/mutation_ci.py check \
  mutants/mutmut-cicd-stats.json \
  --baseline benchmarks/mutation-tier1-baseline.json
```

Run one module while developing:

```bash
mutmut run 'radsim.performance.*' --max-children 4
mutmut results
```

The score treats survived, no-test, suspicious, timeout, and segfault outcomes
as failures. Skipped or equivalent mutants are excluded. The initial complete
Tier 1 baseline is archived in `benchmarks/mutation-tier1-baseline.json`. The
scheduled job is a ratchet and cannot fall below that score. The long-term Tier
1 target is 80 percent.

CI selects the Tier 1 modules a pull request adds and requires those selected
modules to score at least 87 percent. Modules the pull request only modifies are
left to the nightly ratchet, so pre-existing gaps do not gate a branch. It runs
the complete Tier 1 set nightly or by manual dispatch.

Mutation execution requires process forking, so it runs on Linux and macOS
directly. Use Linux CI or WSL when working from Windows. Generated mutant files
and reports are excluded from Git.

Per-module results for the modules changed by the performance work are archived
in `benchmarks/mutation-changed-modules.json`.

The final Linux optimisation sweep is archived in
`benchmarks/mutation-optimisation-final-linux.json`. Its complete configured
set killed 2,445 of 4,624 mutants for a score of 52.8763%, passing the 15%
ratchet. The 240 timeouts from the earlier high-concurrency pass remain counted
as failures. Focused item 9 reruns used at most four workers and had no
timeouts.

## Current scores

| Module | Score | Origin |
| --- | ---: | --- |
| `radsim/bounded_cache.py` | 98.4% | added by the performance work |
| `radsim/tool_scheduler.py` | 97.4% | added by the performance work |
| `radsim/prompt_cache.py` | 96.8% | added by the performance work |
| `radsim/tool_router.py` | 89.7% | added by the performance work |
| `radsim/learning/buffer.py` | 82.5% | added by the performance work |
| `radsim/performance.py` | 68.5% | pre-existing |
| `radsim/agent_api.py` | 48.8% | pre-existing |
| `radsim/learning/store.py` | 48.3% | pre-existing |
| `radsim/learning/retrieval.py` | 39.4% | pre-existing |

Every module the performance work added meets the 80 percent Tier 1 target.
Four pre-existing modules do not, and they are the largest and most
load-bearing in the codebase: `agent_api.py` is the orchestration core and
`learning/retrieval.py` is the ranking logic behind every learning decision.
Their suites execute the code without detecting faults injected into it. This
is a standing gap, not a regression, and closing it is separate work.

## Triaging survivors

A score is only meaningful once its survivors are classified. Inspect each one
as a diff rather than inferring from the mutant name:

```bash
mutmut results | grep survived
mutmut show 'radsim.tool_scheduler.x_plan_parallel_group__mutmut_15'
```

Across the modules added here, 42 survivors were inspected: 16 were real test
gaps and were killed, and 26 are equivalent mutants — mostly `logger.debug`
message text, plus dead default values that reach the same branch either way.
Two of the real gaps mattered: the parallel scheduler could have passed `None`
instead of a tool name to the confirmation predicate, and its interrupt check
could be neutered without any existing test failing.

The final item 9 review inspected the new result-serialization paths separately.
Of 39 mutants, 35 were killed and four surviving comparison/default changes
were equivalent on every reachable input. The added boundary and metadata
tests killed all 17 meaningful survivors found during triage. The
`radsim.performance` result remained exactly at its archived 124 killed and 57
survived mutants; item 9 only changed its module-level telemetry allowlists, and
a functional test now proves that every permitted count is written without a
raw payload.
