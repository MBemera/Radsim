# Evolve and extension architecture release notes

This release consolidates RadSim's learning path and adds a minimal,
review-gated Python extension boundary.

## Defaults and safety

- The proposal engine remains off by default.
- Self-extension remains off by default.
- Model text alone records an `unknown` task outcome.
- `add_tool`, generated code, and extension activation always require explicit
  approval and are excluded from learned trust.
- Project extensions require trust for the exact project and fingerprints for
  their current files.
- Extensions reuse the existing tool, command, hook, policy, confirmation, and
  undo paths.
- No runtime dependency or permanent background service was added.

Approved Python extensions are trusted local code and run with the user's
permissions. Permission tiers control RadSim's invocation policy; they do not
sandbox malicious Python.

## User-facing changes

- `/evolve` now controls learning collection, proposal analysis, automatic
  proposals, module settings, and reviewed extensions.
- Task outcomes distinguish successful, partial, failed, cancelled, rejected,
  reverted, and unknown work.
- Learning events use one bounded, versioned SQLite store with idempotent
  migration and backups for legacy JSON data.
- Retrieval uses one explainable local TF-IDF scorer.
- Extensions support exact-file approval, project trust, load, reload, unload,
  staged activation, and rollback.

## Engineering comparison

Measured against branch baseline `76b2ec7`:

| Metric | Baseline | This change | Delta |
| --- | ---: | ---: | ---: |
| Production Python files | 108 | 107 | -1 |
| Production Python lines | 37,958 | 40,034 | +2,076 (+5.5%) |
| Learning package modules | 9 | 6 | -3 |
| Learning package lines | 3,162 | 3,272 | +110 (+3.5%) |
| Runtime dependencies | 4 | 4 | 0 |

The production increase is the new extension API and trusted lifecycle layer.
It is offset structurally by deleting seven overlapping learning
implementations and consolidating their responsibilities into four modules.

## Validation

- Ruff passes for `radsim`, `tests`, and `examples`.
- The complete suite passes on Python 3.12: 1,830 tests.
- GitHub CI defines the supported Python 3.10 through 3.14 matrix.
