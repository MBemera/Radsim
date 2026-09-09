# RadSim Optimisation Handoff

Date: 2026-08-28 (Australia/Melbourne)

## Working copy

- Repository: `/Users/brighthome/Desktop/RadSim/radsim-optimisation`
- Branch: `optimisation`
- Remote branch before this work: `origin/optimisation` at `cd61bd8`
- Implementation commits prepared from this work:
  - `217f3ab perf: bound long-lived agent state`
  - `32aeef2 feat: refresh OpenRouter model catalogue`
- The branch is intended to be pushed to `origin/optimisation` for transfer to another device. No pull request was created.

## Completed work

### Item 9: bound long-lived memory

- Finished background jobs are capped at 100 and pruned without removing running jobs.
- Injected background-job IDs are reconciled with retained jobs.
- Conversation history is capped at 400 messages without splitting tool-use/tool-result pairs.
- Processed image and base64 message blocks are released after a turn.
- Serialized tool results are capped at 100,000 characters while remaining valid JSON.
- Learning tool-result tracking is capped at 200 entries while preserving aggregate success and failure evidence.
- Pending direct-shell contexts are capped at 32.
- Repository-symbol caching is capped at 512 entries.
- Skill-document caching is capped at 32 entries, skill discovery is capped at 256 entries, and skill names are validated before path construction.
- Runtime cache statistics and clearing now include repository-symbol and skill-document caches.
- Count-only memory telemetry was added without logging prompts, tokens, paths, or other sensitive payloads.
- Extension reload tests confirm stale hook-module references are removed.

The reproducible soak test performs 1,000 warm-up turns followed by 1,000 measured mocked turns. Latest archived result:

- RSS: 38,084,608 to 38,494,208 bytes, growth 1.0755% (target below 10%)
- Tracemalloc current: 4,601,664 to 4,322,098 bytes, change -6.0753%
- File descriptors: 4 to 4
- Threads: 1 to 1
- Python subprocess objects: 0 to 0
- SQLite connections: 0 to 0
- Retained messages: 400
- Retained injected job IDs: 100
- Retained finished jobs: 100
- All configured caches remained within their bounds
- Result: passed

Evidence:

- `benchmarks/memory_soak.py`
- `benchmarks/memory-soak-1000-turns.json`
- `docs/MEMORY_DISCIPLINE.md`
- `tests/test_memory_bounds.py`

### OpenRouter model refresh

The public OpenRouter catalogue was checked on 2026-08-28 using `https://openrouter.ai/api/v1/models`. No credentials were used.

- Live catalogue size: 387 models
- Curated RadSim catalogue size: 25 models
- Curated models missing from OpenRouter: none
- Curated models without tool support: none
- Default model changed to `z-ai/glm-5.3`
- Added current curated options for GLM 5.3 Flash, Claude Opus 5, Claude Sonnet 5, Gemini 3.7 Flash, Grok 4.6, Qwen3.8 Max, and Seed 2.0 Code
- Refreshed context sizes, static pricing, reasoning-effort metadata, and request-parameter support
- Kept existing curated models for compatibility

Evidence:

- `benchmarks/openrouter-catalogue-2026-08-28.json`
- `docs/OPENROUTER_MODELS.md`
- `radsim/config.py`
- `radsim/openrouter_models.py`

### Item 10: Rust admission gate

No Rust dependency or build tooling was added. A standard-library `cProfile` workload showed the largest Python self-time kernel at 4.0814%, below the plan's 15% admission threshold. Adding PyO3 or maturin would therefore add supply-chain and maintenance cost without evidence of a worthwhile gain.

Evidence:

- `benchmarks/profile_local_processing.py`
- `benchmarks/rust-admission-profile.json`
- `docs/RUST_ADMISSION_GATE.md`

`py-spy`, `scalene`, and `pytest-benchmark` were not installed, so the profile used Python's standard-library profiler and added no dependency.

## Verification completed

- `python3 -m ruff check .`: passed
- `python3 -m pytest -q`: 2,613 passed in 92.52 seconds
- `git diff --check`: passed
- `python3 benchmarks/memory_soak.py`: passed
- Live OpenRouter comparison: 25 curated models present, all 25 tool-capable
- No dependency was added or changed

The soak result is proven on macOS only. Linux and Windows CI/runtime soak verification remains outstanding.

## Mutation-test checkpoint

Mutmut version: 3.7.0

Command used:

```bash
python3 -m mutmut run --max-children 4
```

The clean-test prerequisite passed and mutmut generated 3,665 mutants across every module configured in `pyproject.toml`. The run was stopped cleanly for this handoff at:

- Evaluated: 3,135 of 3,665 (85.54%)
- Killed: 1,786
- Survived: 1,298
- Timed out: 42
- Uncovered: 9
- Suspicious: 0
- Skipped: 0
- Remaining: 530

This is a partial run, so there is no final mutation score or baseline-gate result yet. The large survivor count includes the pre-existing weak modules documented in `HANDOFF_CODEX.md`; do not describe it as a regression without the completed per-module comparison.

Mutmut state is stored in the ignored `mutants/` working directory. If that directory is present tomorrow, the same run command should reuse completed classifications. The ignored directory is not transferred through GitHub, so a checkout pulled onto another device should expect to run the full suite again unless `mutants/` is copied separately.

Do not edit mutation-scoped source while mutmut is running. Source changes invalidate the active run.

## Remaining tasks for tomorrow

1. Confirm the checkout before continuing:

   ```bash
   pwd
   git branch --show-current
   git status --short --branch
   ```

2. Finish the complete configured mutation run:

   ```bash
   python3 -m mutmut run --max-children 4
   python3 -m mutmut export-cicd-stats
   python3 scripts/mutation_ci.py check mutants/mutmut-cicd-stats.json --baseline benchmarks/mutation-tier1-baseline.json
   python3 -m mutmut results
   ```

3. Inspect every survivor in the two mutation-scoped modules changed in this work: `radsim/agent_api.py` and `radsim/performance.py`. Kill meaningful survivors with focused tests or document genuinely equivalent mutants. Then rerun the affected mutation target before trusting the full result.

4. Distinguish new regressions from the handoff's known baseline debt. The prior weak modules were `performance`, `agent_api`, `learning/store`, and `learning/retrieval`; the prior detailed scores are in `benchmarks/mutation-changed-modules.json`.

5. If tests or source change during survivor work, rerun:

   ```bash
   python3 -m ruff check .
   python3 -m pytest -q
   python3 benchmarks/memory_soak.py
   git diff --check
   ```

6. Validate the archived JSON evidence and perform the final security/standards review. Confirm no secrets or sensitive payloads appear in source, tests, docs, logs, generated evidence, or the commit diff. Dependencies did not change, so a new dependency audit is not required; if the environment supports it, an additional `python3 -m pip_audit` check is still useful.

7. Run the soak on Linux and Windows when those environments are available. Record any platform-specific file-descriptor, thread, subprocess, or RSS differences.

8. Do not add Rust unless a later representative profile meets every admission gate in `docs/RUST_ADMISSION_GATE.md`.

9. Recheck OpenRouter immediately before a later release because the provider catalogue and pricing are dynamic. Keep the dated snapshot rather than silently changing model metadata.

10. Keep work local unless Matt explicitly asks to push or create/update a pull request.

## Security and design notes

- No secrets, tokens, credentials, or private user data were required for the OpenRouter refresh.
- Memory telemetry exposes counts only.
- Cache and retention limits are explicit and bounded.
- Job pruning never removes running work.
- Tool-result truncation preserves valid JSON.
- Skill-name validation fails closed before filesystem access.
- No new package or build-system dependency was introduced.
- Authentication, CORS, database exposure, and rate limiting were not changed by this work.
- The implementation follows the RadSim preference for small, named limits, early returns, explicit state, and reusable bounded-cache infrastructure.

## Useful starting files

- `HANDOFF_CODEX.md`
- `radsim-performance-optimisation-plan.md`
- `TBDCODEX.md`
- `docs/MEMORY_DISCIPLINE.md`
- `docs/OPENROUTER_MODELS.md`
- `docs/RUST_ADMISSION_GATE.md`
- `benchmarks/mutation-changed-modules.json`
- `benchmarks/mutation-tier1-baseline.json`
