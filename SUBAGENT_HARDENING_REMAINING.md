# Sub-agent hardening: remaining work

**Status:** Phases 0-5 complete and merged to `claude/branch-implementation-tests-linting-kng4a4`. Phase 6 partially complete.
**Plan:** `RADSIM_PROMPT_SUBAGENT_HARDENING_PLAN.md`
**Baseline:** `main` at `76b2ec7`

This note records what the hardening plan asked for that is **not** in the branch,
so nobody has to re-derive it by diffing the plan against the code.

## 1. Blocking: behavioural evals (plan section 9)

Not implemented. This is the largest remaining item and it gates release.

The plan specifies 28 behavioural cases run against two fixed prompt candidates
(current vs. proposed), at least three times each, across a representative
provider family. That needs live model calls, which the implementation
environment could not make. No `tests/evals/` directory or fixtures exist.

Missing cases, by group:

| Group | IDs | What they check |
| --- | --- | --- |
| Planning and consent | P01-P05 | Planning-only stays read-only, ambiguous consent stops, rejection is not retried |
| Injection and secrets | S01-S09 | README/tool-output/background-result injection, protected reads, self-modification |
| Tool discipline | T01-T03 | No invented tools, dedicated tool preferred, failures reported honestly |
| Delegation | A01-A08 | Least-privilege profile, no needless delegation, fail-closed, persistence, cancellation |
| Communication | C01-C04 | Trade-off framing, pushback, stated uncertainty, result-first answers |

**What is already covered structurally.** The invariants behind S01-S09, A03-A08,
and P05 have unit tests in `tests/test_subagent_security.py`,
`tests/test_sub_agent_policy.py`, and `tests/test_sub_agent_profiles.py` — 188
tests total. Those prove the *runtime* fails closed. They do not prove the
*model* behaves well, which is what the evals measure.

**Release gates that therefore remain unmeasured** (plan section 9.3):

- Correct tool or no-tool choice: at least 95%
- Task completion non-regression vs. current prompt: no more than 5pp lower
- Personality and clarity rubric: at least 90%

Gates that **are** met and verified: static prompt size (11,151 ≤ 12,000),
static prompt reduction (39.3% ≥ 35%), and the fail-closed / persistence /
primary-drift gates, all covered by unit tests.

To build this: use fake tools and temporary directories per section 9.1, import
the pinned prompt at `76b2ec7` as Candidate A, and score hard security failures
separately from style. Any hard security failure blocks release regardless of
averages.

## 2. Manual verification not performed

Unit-tested, but never exercised against a live provider or a real terminal:

- **First-run onboarding** into first delegation (the model picker flow).
  `_prompt_subagent_model` is covered only through mocked `interactive_menu`.
- **Telegram mode.** `_require_subagent_selection` returns an instruction to run
  `/subagent model` in the terminal instead of prompting. Logic is tested; the
  actual Telegram path is not.
- **All three providers.** Selection and key resolution are catalogue- and
  env-level tested. No live call has been made through `claude`, `openai`, or
  `openrouter` as a sub-agent provider.
- **Restart persistence.** Tested by constructing a second `AgentConfigManager`
  against the same directory, not by restarting the process.

## 3. Known gaps in the shipped code

**Profile `max_tokens` is declared but never applied.** Each profile in
`sub_agent_profiles.py` carries a `max_tokens` value (2048-4096) and
`SubAgentTask` has a `max_tokens` field, but neither reaches the provider:
`api_client.py` hardcodes `max_tokens: 16000` for every call and its `chat()`
signature does not accept an override.

This is pre-existing — the old `MODEL_TIERS` declared `max_tokens` per tier and
`resolve_task_config` returned it, but `execute_subagent_task` never passed it
either. It was carried forward rather than introduced.

It was left alone deliberately: wiring it means changing `api_client.chat()`,
which the primary agent also uses, and the plan's first non-negotiable invariant
is that the primary path does not change. Pick one before release:

1. Thread an optional `max_tokens` through `chat()`/`stream_chat()`, defaulting
   to today's 16000 so the primary path is unchanged; or
2. Drop `max_tokens` from the profile records, since a declared limit that has
   no effect misleads anyone reading the module.

Option 2 is smaller and honest. Option 1 is what the profiles imply. Either is
defensible; leaving it as-is is not.

Sub-agent output is separately bounded at 20,000 characters by
`MAX_RESULT_CHARS`, so this is a cost and latency question, not a safety one.

## 4. Scope decisions worth re-reviewing

Both are departures from a literal reading of the plan. Flagged for a
maintainer to confirm or reverse.

**`capable` is rejected, not remapped.** Plan section 10 says `capable` "requires
foreground `implement` and explicit approval". The branch raises an error naming
the alternatives instead of remapping. Rationale: `capable` meant the full
72-tool registry, and any silent mapping carries that over-permission forward
under a new name. A user who typed `capable` should have to choose. `fast` maps
to `explore` as specified; both mappings expire after one release.

**Parallel fan-out is limited to non-confirming profiles.** Not in the plan.
`implement` and `verify` cannot run as `parallel_tasks` even in the foreground,
because several worker threads reaching the confirmation prompt at once produce
interleaved questions and a user cannot tell which change they are approving.
Uses the same predicate as the background rule: no mutation, no project-code
execution.

## 5. Deliberately not carried over

Recorded so their absence reads as a decision rather than an omission.

- `quick_task()` and `list_available_models()` — removed from the public API.
  Both hardcoded OpenRouter and Haiku, which is exactly the silent-fallback
  behaviour the plan removes.
- `SubAgent(SubAgentMixin, RadSimAgent)` and `radsim/agent_subtasks.py` — deleted
  after confirming nothing constructed them. Plan section 4 asked for one runner.
- `resolve_model_name()`, `MODEL_TIERS`, `TOOL_SUBSETS`, `get_tools_for_tier()`,
  `resolve_task_config()` — replaced by profile resolution that fails closed.
- `is_core_prompt_intact()` — kept as defence in depth behind the new
  path-based `is_core_policy_path()`, not removed.

## 6. Suggested order

1. Decide the `max_tokens` question (section 3) — small, and it changes the
   profile records the evals will exercise.
2. Build `tests/evals/` and run the section 9 matrix (section 1).
3. Manual first-run, Telegram, and three-provider passes (section 2).
4. Confirm or reverse the two scope decisions (section 4).
5. Release as a minor version once section 9.3 gates pass.
