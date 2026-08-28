# Mutation and Property Testing

Install the test and mutation dependencies:

```bash
python -m pip install -e ".[dev,mutation]"
```

Run deterministic property tests:

```bash
python -m pytest tests/property -q -p no:randomly
```

Run the Tier 1 mutation set on Linux or WSL:

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

CI selects changed Tier 1 modules for pull requests and requires those selected
modules to kill every checked mutant. It runs the complete Tier 1 set nightly
or by manual dispatch.

Mutation execution requires process forking. Use Linux CI or WSL when working
from Windows. Generated mutant files and reports are excluded from Git.
