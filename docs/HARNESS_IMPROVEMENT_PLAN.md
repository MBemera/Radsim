# RadSim Harness Improvement Plan — reviewed

**Target repo:** `~/Radsim` @ `706752a` (v1.6.2, branch `main`)
**Working branch:** `improve/harness-engineering`
**Model:** `z-ai/glm-5.2` via OpenRouter (already RadSim's default)
**Date:** 2026-08-04
**Status:** amended after source review; cost targets remain provisional until
the instrumented baseline is captured

## Progress

- 2026-08-04: created `improve/harness-engineering` from `706752a` in a
  dedicated worktree and completed item 1. The same 20-run fresh-process
  benchmark (`python -S -c "import radsim"`) improved from 176.20 ms median /
  272.38 ms p95 to 49.33 ms median / 73.65 ms p95. Importing `radsim` no longer
  loads `importlib.metadata`; 49 focused tests, the full 2,102-test suite and
  Ruff passed.
- 2026-08-04: completed Phases 0 and 1 as separate reviewable commits. The eval
  now has preflight bounds, immutable artifacts, normalized usage, honest A/B
  statistics, provider-aware pricing, bounded trust evidence and pinned
  sampling controls.
- 2026-08-04: completed §5.2 offline. Provider requests now use canonical tool
  schemas, active prompt modes are ordered deterministically, the first scored
  run per candidate primes the natural prefix before fan-out, and results
  record cache, provider/route/model and latency evidence.
- 2026-08-04: began §5.3 by correcting eval parity from 18 offered tools to all
  72 checked-in production schemas and recording schema-size and privacy-safe
  confusion evidence. No stored eval artifacts were present, so descriptions
  remain unchanged until bounded development and holdout runs can justify a
  measured edit.
- 2026-08-04: completed §5.4. Pruning no longer uses raw 80%/70% percentages of
  the advertised model window. `radsim/context_budget.py` resolves one explicit
  input cap as the narrowest of provider context minus output reserve, the
  configured `max_context_input_tokens` (default 80,000) and any unspent session
  input budget. Usage now counts the fixed system-prompt and canonical
  tool-schema prefix, pruning runs before every provider request rather than
  only on user turns, the same reserve is sent as `max_tokens`, and a request
  that still cannot fit fails closed with `BudgetExceeded` before provider I/O.
- 2026-08-04: completed §6.1. `radsim/task_logger.py` is removed together with
  its package exports, tests and doc references after the owner confirmed no
  Python-import compatibility promise at beta. The latent unsanitized
  `~/.radsim/logs/` sink is gone; hardened redaction stays in
  `radsim/learning/store.py`.
- No paid live eval or credential-bearing action has been run. The empirical
  cache target and release baseline remain intentionally unset pending explicit
  spend authorization. §5.4's live quality/latency sweep is deferred with it;
  the offline boundary contracts are proven by tests.

## Scope

Fix the defects found during review, correct cost reporting, make the harness
faster and cheaper to run, and improve the user-facing experience.

This revision treats the harness as production test infrastructure. It adds
four requirements missing from the first draft: hermetic execution, immutable
run provenance, hard time/token/cost budgets, and statistically honest
comparisons. Security gates remain separate from quality averages and always
fail closed.

**Explicitly out of scope:** reinforcement learning, reinforcement fine-tuning,
model training or distillation, and building a verifiable-task RL environment.
Those were discussed and set aside. The eval matrix appears here only as a
regression gate for the changes below, not as a training objective.

**Standards basis:** NIST AI RMF / NIST AI 600-1 for measured and monitored AI
risk, NIST SSDF for secure development evidence, OWASP Top 10 for Agentic
Applications for prompt injection, excessive agency, memory poisoning and
traceability risks, and OpenTelemetry GenAI semantic names where they are
stable enough to reuse. These are engineering mappings, not a certification
claim.

---

## 1. Verified facts this plan rests on

Everything in this section was measured or fetched, not recalled.

### 1.1 Harness measurements

| Quantity | Value | How measured |
|---|---|---|
| Static system prompt | 11,151 chars ≈ **2,787 tokens** | `len(get_static_prompt())` |
| Tool schemas (72 tools) | 31,501 chars ≈ **7,875 tokens** | `json.dumps` of the definitions list |
| **Fixed prefix per API call** | **≈ 10,662 tokens** | sum of the two above |
| `import radsim` | **98 ms**, of which **94 ms** is `importlib.metadata` | `python3 -X importtime` |
| Cold CLI startup (`--version`) | **0.215 s** | `time python3 -c ...` |
| Eval matrix size | 29 cases × 2 candidates × 3 reps = **174 runs** | `tests/evals/cases.py`, `run_evals.py` |
| Rubric-graded cases | 17 | `grep -c "rubric=True"` |
| Iteration ceiling | `DEFAULT_MAX_ITERATIONS = 7` | `tests/evals/harness.py:24` |
| Output ceiling | `EVAL_MAX_OUTPUT_TOKENS = 1500` | `tests/evals/harness.py:28` |

### 1.2 Corrections found during repository review

- Candidate A is pinned at `76b2ec7`, but a remote model result is not
  deterministic merely because commit, model and effort are pinned. Provider
  routing, model snapshots and scoring code can drift; `seed` is best-effort.
- `radsim.task_logger` is exported through `radsim.__all__` and has direct tests.
  Removing it without deprecation is a public API change, not routine dead-code
  deletion. **Decision (2026-08-04, owner):** no compatibility promise is made
  for Python-level imports at this beta stage, so the module was removed
  outright rather than deprecated. See §6.1.
- `Scheduler` is used by `tests/test_security_injection.py` as well as its own
  tests. Removal must migrate the security cases to the live `jobs.py` path.
- `tests/evals/README.md` still says four request/tool rounds while the code uses
  seven. Documentation and executable defaults must use one source of truth.
- `get_model_pricing(model)` currently has no provider or billing-mode argument.
  Live-catalogue-first pricing cannot be implemented safely until provider and
  provenance are explicit.

### 1.3 OpenRouter pricing and capabilities (fetched live)

Verified again on 2026-08-04 against the official
[models API](https://openrouter.ai/api/v1/models),
[prompt-caching documentation](https://openrouter.ai/docs/guides/best-practices/prompt-caching)
and [usage-accounting documentation](https://openrouter.ai/docs/cookbook/administration/usage-accounting).

| Model | Input $/M | Output $/M | **Cache read $/M** | Context |
|---|---|---|---|---|
| `z-ai/glm-5.2` | 0.76 | 2.42 | **0.14** | 1,048,576 |
| `z-ai/glm-4.7-flash` | 0.06 | 0.40 | 0.01 | 202,752 |
| `z-ai/glm-4.5-air` | 0.13 | 0.85 | 0.025 | 131,072 |

Two findings from the capability payload that change the plan materially:

1. **`input_cache_read` is $0.14/M against $0.76/M prompt — an 81.6% discount —
   and there is no `input_cache_write` price listed.** Caching on this model is
   automatic prefix caching with no write premium. There are no `cache_control`
   breakpoints to place; identical prefixes are cached implicitly. This is the
   single biggest cost lever and it requires no API-shape change.

2. **`supported_parameters` for `glm-5.2` includes `seed`, `temperature`,
   `top_p`, `top_k`, `min_p`, `logprobs`, `reasoning_effort`,
   `parallel_tool_calls`, `structured_outputs`, `response_format`, `stop`.**
   Controlled sampling is available today. The gap is RadSim-side plumbing in
   `api_client`; even with a seed, live-provider replay is best-effort rather
   than bit-for-bit reproducible.

> **Correction to earlier review notes.** Two things I stated during review were
> incomplete. (a) `reasoning_effort` *is* plumbed through RadSim —
> `create_client(..., reasoning_effort=)` maps to `{"reasoning": {"effort": ...}}`
> for OpenRouter, gated by `model_supports_reasoning`. Only `temperature`/
> `top_p`/`seed` are missing. (b) `seed` is supported by the provider, so
> variance can be reduced, but a remote model and route can still drift.

---

## 2. Cost model: estimated $7.04 baseline → measured budget

### 2.1 Assumptions

Stated so they can be corrected once real telemetry exists:

- **3.5 average iterations per case run** against the ceiling of 7 → ~610 API calls
  for the full matrix.
- **~500 average output tokens** against the ceiling of 1,500.
- **~2,300 average conversation tokens** per call on top of the fixed prefix.
- Rubric grading: ~1.5k input / ~600 output per grading call, 102 calls.

These are modelled, not measured. **Phase 0 replaces them with real numbers.**
No absolute cost target becomes a release gate until that baseline records the
provider-reported cost and the full token breakdown.

### 2.2 Current cost (assuming no cache hits realised)

| Line | Tokens | Rate | Cost |
|---|---|---|---|
| Input (610 calls × ~13k) | 7.93 M | $0.76/M | $6.03 |
| Output | 0.305 M | $2.42/M | $0.74 |
| Rubric grading on `glm-5.2` | 0.214 M | mixed | $0.27 |
| **Total** | | | **≈ $7.04** |

Automatic caching may already be producing partial hits, so the true baseline
may be lower. Nobody knows, because cached-token counts are not currently
captured. That is itself a defect (§4.1).

### 2.3 Scenario cost after the changes in this plan

**Profile A — full release gate (both candidates, 3 reps):**

| Line | Tokens | Rate | Cost |
|---|---|---|---|
| Fixed prefix, cold writes (2) | 0.017 M | $0.76/M | $0.01 |
| Fixed prefix, cached reads (608) | 5.05 M | $0.14/M | $0.71 |
| Conversation, ~50% cached | 1.43 M | mixed | $0.64 |
| Output | 0.305 M | $2.42/M | $0.74 |
| Rubric grading on `glm-4.7-flash` | 0.214 M | mixed | $0.03 |
| **Total** | | | **≈ $2.14** |

**Profile B — per-commit signal (candidate B only, candidate A reused from a
compatible stored run):**

| Line | Cost |
|---|---|
| Fixed prefix (1 write + 304 reads) | $0.35 |
| Conversation | $0.32 |
| Output | $0.37 |
| Rubric grading | $0.02 |
| **Total** | **≈ $1.06** |

### 2.4 Where the saving comes from

| Lever | Saving | Confidence |
|---|---|---|
| Realise automatic prefix caching (81.6% off 6.5 M tokens) | ~$4.2 | High — pricing verified |
| Tool-schema description trim (~30%) | ~$0.20 | Medium — depends how much is trimmable |
| Rubric grading moved to `glm-4.7-flash` | ~$0.24 | High — `--grader-model` flag already exists |
| Reuse candidate A for routine signals | ~$1.1 | Medium — only valid with exact provenance and a freshness limit |

Candidate A is the prompt as it shipped at commit `76b2ec7`, but its score can
still change as provider routing, model snapshots, cases, tool schemas or the
grader changes. Reuse is allowed for routine feedback only when the complete
artifact digest matches and the result is within the configured maximum age.
The release gate reruns A and B in interleaved pairs to control temporal drift.

### 2.5 The one thing that could push cost back up

Phase 0.1 passes `reasoning_effort` into the eval harness so it tests the shipping
configuration. GLM 5.2 defaults to `"high"` in RadSim's config, and reasoning
tokens bill as completion tokens at $2.42/M. **Making the eval honest may
increase output cost.** If output tokens double, Profile A goes from ~$2.14 to
~$2.88.

Mitigations, in order: measure the delta explicitly during the effort sweep;
prefer `high` over `xhigh` unless the sweep justifies the difference; fall back
to Profile B for routine signals. Do not "fix" this by reverting to an eval that
tests a configuration you do not ship.

### 2.6 Budget rule

Before any live run, print the maximum possible requests, tokens and estimated
cost, then require an explicit `--max-cost-usd` for release runs. Stop scheduling
new work when the cap is reached. In-flight calls may finish, so the report must
show both the configured cap and final provider-reported cost. A cost estimate
is never labelled actual spend.

---

## 3. Phase 0 — Make the measurement trustworthy

Nothing else in this plan can be verified until this is done.

### 0.0 Add a hermetic preflight and immutable run manifest

**Fix:** validate candidates, cases, provider capabilities, grader selection,
worker count, request timeout and budget before the first paid call. Each case
already uses a temporary project and fake tools; keep all shell, network,
credential, messaging and sub-agent effects simulated. Pass only the selected
provider credential to the client and never persist it.

Write a schema-versioned manifest containing the full Git SHA and dirty flag,
candidate prompt digests, case-set digest, tool-schema digest, scoring-code
digest, provider/model/grader identifiers, resolved sampling parameters,
reasoning effort, worker count, timestamps and Python/RadSim versions. Persist
request IDs and sanitized errors, never credentials, environment dumps, raw
headers or real user/project content.

**Acceptance:** preflight fails before network access on an invalid or missing
budget/configuration; an offline test proves real tools cannot be reached; two
different prompt/tool/case inputs produce different artifact digests.

**Effort:** ~half day.

### 0.1 Pass `reasoning_effort` into the eval harness

**Defect:** `tests/evals/run_evals.py:74` calls
`create_client(provider, api_key, model)` with no `reasoning_effort`, so the
matrix runs at the provider default. The product resolves effort via
`resolve_reasoning_effort` / `load_reasoning_effort` and lands on `"high"` for
GLM 5.2. **The eval currently tests a configuration RadSim does not ship.**

**Fix:** thread `reasoning_effort` through `build_client` and add an explicit
`--effort` setting. Release and commit profiles pin the resolved value; they do
not silently inherit mutable user-global configuration. A `shipping` value may
resolve the model's shipping default, but the concrete result is recorded.

**Acceptance:** offline contract tests prove the exact effort reaches both the
candidate and grader clients; the run manifest and console show the resolved
value. Do not require two stochastic live runs to have different token counts.

**Effort:** ~1 hour.

### 0.2 Capture cached-token counts

**Defect:** RadSim tracks `input_tokens` / `output_tokens` but not cached
tokens. With cache reads at 5.4× less than full-price input, cost cannot be
computed correctly, and the caching work in §5.2 cannot be verified.

**Fix:** normalize provider usage into explicit input, output, cache-read,
cache-write and reasoning-token fields plus provider-reported cost, estimated
cost, latency and request ID where available. OpenRouter's
`usage.prompt_tokens_details` is the source for `cached_tokens` and
`cache_write_tokens`; cached input remains part of total input and must not be
double-counted. Surface the same structure in eval results and `/usage`.

**Acceptance:** offline parser tests cover complete, partial, malformed and
missing usage objects for streaming and non-streaming responses. A bounded live
smoke records observed cache counts but does not fail merely because the remote
provider returned a cache miss.

**Effort:** ~2 hours.

### 0.3 Store eval results per commit

**Defect:** `run_evals` writes `eval_results.json` and clobbers it every run, so
there is no history to compare against.

**Fix:** write each run atomically to
`eval_results/<UTC timestamp>-<short SHA>-<artifact digest>.json`. Store the
manifest beside the scores and transcripts. Use a small atomic `latest.json`
pointer/copy for portability; do not rely on symlinks on Windows. Result files
are private by default, redacted before persistence, size-bounded and governed
by a documented retention policy.

**Acceptance:** two runs never clobber each other; interrupted writes leave no
partial JSON; incompatible manifests cannot be reused as a baseline.

**Effort:** ~1 hour.

### 0.4 Make comparisons statistically honest

Interleave A/B by case and repetition rather than running all of A then all of
B. Record retry attempts and exclude infrastructure failures from quality rates
while still failing the run for insufficient coverage. Report sample counts and
confidence intervals. Keep zero-tolerance security gates exact. Maintain a small
holdout case set that is not used for prompt/schema tuning.

**Acceptance:** paired ordering is deterministic from the harness seed; missing
or errored samples cannot silently improve a rate; the report names reused,
live, failed and ungraded samples separately.

**Effort:** ~half day.

**Baseline capture:** with 0.0–0.4 in place, run the full matrix once and record
request/retry counts, latency distribution, input/output/reasoning/cache tokens,
cache-hit rate, provider-reported cost and estimated cost. Every number in §2 is
a scenario until this run replaces it.

---

## 4. Phase 1 — Correctness defects

### 4.1 Model pricing is wrong and structurally fragile

**Defect:** `radsim/config.py:181` —
`"z-ai/glm-5.2": (0.2646, 0.8316)` against OpenRouter's live $0.76 / $2.42.
`/cost` and `/usage` under-report GLM 5.2 spend by ~2.9×. Units are confirmed
correct (`openai/gpt-5.6-terra` sits at `(2.50, 15.00)` in the same table).

**Before changing the number:** determine whether `0.2646 / 0.8316` is a Z.ai
subscription rate rather than the OpenRouter rate. `radsim/login.py:13` defaults
to this model, so a subscription path plausibly exists. If both billing modes
are live, a single static tuple cannot be correct for both.

**Fix, in order of preference:**

1. For OpenRouter responses, use the provider-reported `usage.cost` as actual
   spend when present. It accounts for route-specific pricing, cache reads,
   cache writes and other billable units better than a local table can.
2. Replace the untyped tuple with a validated `ModelPricing` value containing
   provider, billing mode, input, output, cache-read, cache-write, source and
   fetched-at fields. Reject negative, non-finite or implausible remote values.
3. Use one immutable catalogue snapshot for an eval run. The live 24-hour cache
   is the estimate source for OpenRouter; the static table is an explicitly
   labelled stale fallback, never silently mixed into a running session.
4. If a subscription rate applies, key pricing by provider and billing mode
   rather than model alone. Unknown pricing stays `n/a`, never zero or free.

**Acceptance:** provider-reported spend is displayed as actual; estimated spend
on fixed token fixtures matches hand calculations exactly, including cached
reads/writes; stale or malformed catalogue data fails safely to a labelled
fallback.

**Effort:** ~2–3 hours.

### 4.2 Trust bandit reinforces its own decisions

**Defect:** `radsim/trust_bandit_integration.py` — `confirm_with_bandit` calls
`record_outcome(..., accepted=True)` on an auto-confirm the user was never asked
about. `radsim/safety.py:281` does the same for writes via
`_record_write_decision(file_path, True, config)`. Once an arm crosses the 0.80
mean-trust floor it accumulates positive evidence from its own decisions, and
only the 30-day decay pulls back. Negative signal arrives only on interrupt
(`agent_api.py:354`) or explicit rejection.

**Fix:**

1. Stop recording an outcome on the auto-confirm path. Nobody was asked, so
   there is no evidence. Record an audit event with zero learning weight if the
   decision must be observable.
2. Assign a decision ID to every prompted or auto-confirmed action. `/undo` may
   add negative evidence only when it can prove which decision produced the
   reverted write; an unrelated undo must not poison another arm.
3. Keep destructive, credential, permission, external-message, install,
   publish/deploy and other high-impact actions outside learned auto-confirm,
   regardless of trust score. `auto_confirm` remains an explicit user mode, not
   an inferred permission escalation.
4. Bound and version the learning store, validate it as untrusted persisted
   input, and log policy decisions without tool arguments that may contain
   secrets.

**Acceptance:** an auto-confirm repeated N times leaves α unchanged; a matched
revert decreases only the originating arm's mean trust; a forged/stale decision
ID and every high-impact class fail closed.

**Effort:** ~half day including tests.

### 4.3 Sampling parameters absent from `api_client`

**Defect:** `radsim/api_client.py` passes only `max_tokens` (plus reasoning
effort). `temperature`, `top_p`, and `seed` are absent, so eval variance is
uncontrolled despite the provider supporting all three.

**Fix:** introduce one explicit request-options value and thread supported
`temperature`, `top_p` and `seed` fields through `chat` / `stream_chat`. Keep
normal product defaults unchanged. The eval profile pins its options and the
manifest records them. Provider capability lookup is validated and cached; an
unsupported field is omitted rather than retried after a paid failure.

**Acceptance:** offline request-shape tests prove supported values are passed
unchanged and unsupported values are omitted. Live runs report variance; they
do not claim that a seed guarantees identical tool-call sequences.

**Effort:** ~half day.

---

## 5. Phase 2 — Speed

Ordered by measured impact per hour of work.

### 5.1 Lazy-import `importlib.metadata` — best ratio on this list

**Defect:** `radsim/version.py` imports `importlib.metadata` at module top, and
`radsim/__init__.py:9` imports `version` eagerly. **94 ms of the 98 ms package
import is this one import**, paid on every invocation — `radsim --help`, shell
tab-completion, everything. Cold CLI startup is 0.215 s, so this is ~44% of it.

**Fix:** move `from importlib.metadata import ...` inside
`get_radsim_version()`. Behaviour identical; the module docstring's "no imports
from the rest of RadSim" property is preserved.

**Acceptance:** a fresh-process benchmark reports median and p95 over at least
20 runs and shows that importing `radsim` no longer imports
`importlib.metadata`. `--version` still reports installed metadata when present
and falls back to `__version__` from a checkout. Record absolute timings, but
gate on the removed import and a meaningful relative improvement rather than a
machine-specific 10 ms threshold.

**Effort:** ~10 minutes. Do this first.

### 5.2 Realise prefix caching

**Opportunity:** ~10,662 tokens of identical prefix on every call. Caching is
automatic on this model with no write premium and an 81.6% read discount, so
there is nothing to configure — but there *are* ways to accidentally defeat it.

**Fix — audit for cache-defeating patterns in prompt assembly:**

- Anything time- or session-varying rendered into the system prompt. Check the
  layers built by `_build_prompt_layers` (`radsim/prompts.py:261`), especially
  the memory and skills layers, which are user- and repo-derived.
- Non-deterministic tool-schema ordering. The 72 schemas must serialise
  identically every call — sort by name if they do not already.
- Any per-request identifier that lands ahead of the conversation.

**Fix — natural cache priming:** `run_evals` currently fans out to four workers,
so concurrent first requests may all miss. Do not spend an unscored call solely
to warm a cache. Run and score the first selected case for a prefix before the
remaining fan-out, then record route/provider identity, cache-read tokens and
latency. If stable provider routing is required for cache affinity, make it an
explicit profile option and record the privacy/availability trade-off.

**Acceptance:** stable request serialization is covered offline. A bounded live
run reports the cached fraction after the first request and clearly says
"not observed" when the remote route does not provide a hit; the release gate
uses an empirical target set after baseline rather than assuming 90%.

**Effort:** ~1 day including the audit.

### 5.3 Tool-schema diet

**Opportunity:** 72 tools, 31,501 chars, ~7,875 tokens on every request. Even
cached this is ~$0.71 of a full matrix run, and verbose overlapping descriptions
also drive tool-choice errors.

**Fix:** mine failed `tool_choice_correct` runs from the stored eval results
(now available thanks to 0.3) to find which tools get confused with which, then
trim descriptions targeting those first. Do not remove tools from the eval
harness — it deliberately sends the real schemas, and cutting the set would
invalidate what it measures.

**Acceptance:** schema size falls by a measured amount without a statistically
meaningful regression in tool choice, task completion or any security case on
both the development and holdout sets. The original 25% is a goal, not a gate
chosen before evidence exists.

**Effort:** ~1 day, measurement-led.

### 5.4 Retune context pruning against explicit budgets

**Defect:** `check_and_prune(threshold=80)` → `prune_session(target_percentage=70)`
(`radsim/agent_conversation.py:211`, `:101`). These constants were chosen against
a far smaller context window. GLM 5.2 advertises 1,048,576 tokens, but a large
window is not a reason to retain nearly 80% of it: long context also raises
cost, latency, retrieval noise and cache invalidation risk.

**Fix:** replace raw percentages with a model-aware effective budget capped by
the configured cost and output reserve. Sweep pruning policy against long-form
cases and measure quality, latency, turns, cache usage and peak memory together.
Never exceed the provider's effective route limit merely because the catalogue
advertises a larger model maximum.

**Acceptance:** completion rate not lower, average turns per case not higher,
cache-hit rate not lower, p95 latency and estimated cost stay within their
budgets, and boundary tests prove pruning occurs before the effective limit.

**Effort:** ~1 day.

---

## 6. Phase 3 — Remove dead weight

### 6.1 Deprecate or remove `radsim/task_logger.py` safely

**Defect:** 328 lines. No production caller was found, but the module is exposed
through the package's public lazy exports and has direct tests. Three separate
problems remain:

- Its `_sanitize_for_logging` (line 35) is never called, **including by its own
  `_save_entry`** — so if anything ever wired it up, it would write unsanitised
  tool inputs, messages, and errors to `~/.radsim/logs/`.
- `_save_entry` rewrites the **entire** JSON entry list to disk on every call
  (O(n²) writes over a session) and opens a fresh SQLite connection per entry.
- It duplicates observability that `radsim/learning/` already provides properly,
  with secret scrubbing and a size bound.

**Fix:** first decide and document whether top-level imports such as
`from radsim import log_tool` are supported API. If yes, deprecate in a minor
release and remove in the next breaking release. If no compatibility promise is
made for this beta API, record that decision and remove the module, exports and
tests together. Until removal, do not wire it into production; if it must be
retained, sanitize before every persistence sink and bound retention.

**Do not "fix by wiring it up."** If session-level observability is wanted later,
build it deliberately against the `learning` store's already-hardened patterns.

**Acceptance:** the compatibility decision is explicit; no unsanitized sink is
reachable; removal, if chosen, leaves no package export, docs or tests referring
to the module and the suite remains green.

**Effort:** ~30 minutes.

**Resolved 2026-08-04 — removed.** The owner confirmed no compatibility promise
is owed on `from radsim import log_tool`: `pyproject.toml` declares
`Development Status :: 4 - Beta`, and the only stability commitment in
`CONTRIBUTING.md` covers the tool interface, not Python imports. Deleted
`radsim/task_logger.py`, its five `_MODULE_EXPORTS` entries, its
`tests/test_task_logger.py` suite, and the `radsim.task_logger` references in
`tests/test_lazy_loading.py` and `generate_docs_pdf.py`. This removes the
unsanitized `~/.radsim/logs/` sink and the O(n²) whole-file JSON rewrite.
Redaction and bounded retention remain covered by `radsim/learning/store.py`
(`_sanitize_metadata`) under
`tests/test_evolve_architecture.py::test_learning_store_is_idempotent_bounded_and_redacted`,
so no unique security coverage was lost.

### 6.2 Retire the legacy `Scheduler` class

`radsim/scheduler.py`'s `Scheduler` class is not on the primary command path,
but it is still covered by `tests/test_scheduler.py` and
`tests/test_security_injection.py`. Removing it without migrating those abuse
cases would reduce security coverage.

**Fix:** inventory public imports, migrate equivalent injection, rollback and
fail-closed tests to `jobs.py`, then deprecate/remove the legacy storage path in
a separately reviewable change. Do not combine this with eval telemetry work.

**Effort:** separate half-day compatibility/security task.

### 6.3 Split the known long functions

From the earlier cleanup pass, still outstanding: `_handle_delegate_task` (210
lines), `_cmd_job` (191), `_cmd_plan` (181), `step_user_profile` (183),
`_handle_write_file` (166). Each violates the one-function-one-purpose rule.

Keep these out of the harness branch unless a touched function must be split to
make the requested change testable. Broad opportunistic refactors obscure
regression attribution and should use separate branches.

---

## 7. Phase 4 — User experience

### 7.1 Reasoning effort reachable from `/settings`

**Defect:** `_maybe_prompt_reasoning_effort` (`radsim/commands_core.py:224`)
only fires during model selection. GLM 5.2 exposes `high` and `xhigh` — a real
quality/latency/cost dial the user cannot touch afterwards without redoing model
selection.

**Fix:** add effort to the `/settings` menu, reusing the arrow-key `toggle_menu`
pattern from the security switches. Show the current value and the model's
supported set (from the capability table / OpenRouter catalogue), and grey out
models that do not support it.

**Constraints:**

- Bare invocation must open a menu. No subcommand may print a usage error — this
  is a standing rule after the `/hook remove` incident.
- Every command needs a `HELP_DETAILS` entry or `test_command_audit` fails.

**Acceptance:** effort changeable with zero typed arguments; persists across
sessions; `/settings` shows the active value.

**Effort:** ~half day.

### 7.2 Honest cost reporting

Once 4.1 and 0.2 land, `/cost` and `/usage` become trustworthy — including
cached-read billing. Show cached vs uncached input tokens separately so the user
can see caching working. Label provider-reported spend as actual and catalogue
math as estimated, including source age. Currently these commands under-report
the known OpenRouter GLM 5.2 rates by ~2.9×, which is worse than showing nothing.

**Effort:** folded into 4.1 and 0.2.

### 7.3 Two documented eval profiles

Expose the cost split from §2.3 as first-class options:

- `--profile release` — both candidates interleaved, 3 reps, full gates
  (scenario estimate ~$2.14 before reasoning-token measurement).
- `--profile commit` — candidate B only with candidate A loaded from stored
  compatible results, 3 reps (scenario estimate ~$1.06). This is a routine
  signal, not equivalent release evidence.

Store candidate A's results under the complete artifact digest from 0.0 and a
maximum age. Invalidate on any candidate, case, tool, scorer, grader, provider,
model, route, effort, sampling or harness change.

**Acceptance:** `--profile commit` marks reused data, age and provenance and
calls its comparison provisional. `--profile release` refuses a reused baseline
and a missing explicit cost cap.

**Effort:** ~half day.

---

## 8. Sequencing

| # | Item | Phase | Effort | Blocks |
|---|---|---|---|---|
| 1 | Branch/worktree, clean baseline and `version.py` lazy import | 2 | 1 h | — |
| 2 | Hermetic preflight, explicit spend cap and run manifest | 0 | 4 h | every paid run |
| 3 | Eval effort passthrough and pinned profile options | 0 | 1–2 h | honest baseline |
| 4 | Normalized usage/cost parsing with offline contracts | 0 | 3–4 h | pricing, caching |
| 5 | Atomic result storage and compatibility validation | 0 | 3 h | reuse, history |
| 6 | Paired ordering, coverage accounting and intervals | 0 | 4 h | release comparison |
| 7 | **Bounded baseline matrix** with explicit user-approved cap | 0 | measured | replaces §2 scenarios |
| 8 | Provider-aware pricing and actual-vs-estimated UI | 1 | 4–6 h | honest display |
| 9 | Trust-bandit feedback-loop fix | 1 | 2 h | immediate safety |
| 10 | Decision IDs and matched revert evidence | 1 | 4–6 h | safe learning |
| 11 | Sampling request options and profile pinning | 1 | 4 h | lower variance |
| 12 | Prefix stability audit and natural cache priming | 2 | 1 d | cost reduction |
| 13 | Eval profiles and compatible routine baseline reuse | 4 | 4 h | routine cost |
| 14 | Reasoning effort in `/settings` | 4 | 4 h | user control |
| 15 | Tool-schema diet using development plus holdout cases | 2 | 1 d | measured efficiency |
| 16 | Context-budget/pruning experiment | 2 | 1 d | measured efficiency |
| 17 | **Fresh paired release matrix** | — | measured | final regression evidence |
| 18 | `task_logger` / `Scheduler` compatibility work | 3 | separate changes | no harness blocker |

Do not commit generated live transcripts or credentials. Keep the implementation
in small reviewable slices, with offline tests after each slice. A paid matrix
run is never implied by this plan: its printed maximum and explicit cost cap
require user approval first.

---

## 9. Risks and open questions

| Risk | Impact | Handling |
|---|---|---|
| `0.2646 / 0.8316` is a real Z.ai subscription rate | Pricing "fix" would be wrong | Confirm the billing path before editing; key pricing by mode if both are live |
| Passing `reasoning_effort` raises output tokens | Scenario cost may reach ~$2.88 or more | Measure reasoning tokens; use the shipping setting and explicit budgets |
| Automatic caching does not behave as the pricing implies | Main cost lever weakens | Record provider/route and cache metrics before setting a cache gate |
| Remote model/provider drift | Cached baseline becomes misleading | Full provenance, maximum age, paired release runs; seed is best-effort |
| Concurrent retries exceed spend cap | Surprise cost | Stop scheduling at the cap, bound workers/retries, report in-flight overrun |
| Eval artifacts expose secrets or private code | Data disclosure | Synthetic fixtures, redaction, private permissions, retention limits, no environment dumps |
| Rubric grader is biased or injected | False pass/fail | Structured parsing, untrusted-data boundary, deterministic checks first, grader version in manifest |
| Pruning retune conflicts with caching | Cache-hit rate drops as pruning changes | 5.4 measures both together, not separately |
| Removing exported legacy APIs breaks users | Compatibility regression | Deprecate or document beta break; move to separate changes |
| Eval cases overfit prompt/schema tuning | Inflated quality | Versioned holdout cases and fresh paired release evidence |
| Current cases score behaviour more than end-state correctness | Incomplete task-success evidence | Add a small deterministic end-state set; this is evaluation, not RL training |

---

## 10. Standards and security verification map

| Baseline | Applied control and evidence |
|---|---|
| [NIST AI RMF / GenAI Profile](https://www.nist.gov/itl/ai-risk-management-framework) | Versioned cases, measured risk gates, pre-deployment evals, monitored cost/latency/security outcomes and documented residual risk |
| [NIST SSDF SP 800-218](https://csrc.nist.gov/pubs/sp/800/218/final) | Reviewable changes, abuse-case tests, dependency audit, protected secrets, reproducible evidence and root-cause fixes |
| [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) | Prompt/tool-output injection cases, least agency, fail-closed approval policy, bounded memory learning and traceable decisions |
| [OpenTelemetry GenAI conventions](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) | Align token/cache/reasoning/request names where useful; do not add a telemetry dependency solely for naming, and never record sensitive content by default |
| [SLSA 1.2](https://slsa.dev/spec/v1.2/) / OpenSSF | Pin CI actions by full SHA, audit dependencies when they change, keep lock/build inputs reviewable, and retain artifact provenance for releases |

Before each deliverable: run Ruff, focused tests, the full offline suite,
security tests and `pip-audit` when dependencies change. Scan diffs and generated
artifacts for secrets. Verify network exposure, CORS, auth, database access and
rate limiting as not applicable unless this work introduces those surfaces.

## 11. Definition of done

- [ ] `import radsim` no longer imports `importlib.metadata`; median/p95 startup
      and import improvements are recorded without a machine-specific hard gate.
- [ ] Every live run has an immutable manifest, unique atomic result file,
      explicit timeout/retry/worker bounds and a caller-supplied cost cap.
- [ ] Usage separates total input, uncached input, cache reads, cache writes,
      output and reasoning tokens without double-counting.
- [x] Provider-reported spend is labelled actual; catalogue-derived spend is
      labelled estimated with provider, billing mode, source and age.
- [ ] Cost and cache targets are set from the measured baseline. Scenario values
      such as $2.20, $1.20 and 90% are not release claims until observed.
- [x] Evals pin and report the concrete reasoning/sampling configuration; `seed`
      is documented as best-effort.
- [ ] Release runs compare fresh interleaved A/B samples, report coverage and
      confidence intervals, and never substitute a cached baseline.
- [ ] Hard-security failures remain zero-tolerance; incomplete/errored coverage
      fails closed rather than improving quality rates.
- [x] Trust learning records no positive evidence from its own auto-confirms;
      matched reverts affect only the originating decision; high-impact actions
      cannot gain learned auto-approval.
- [ ] Eval artifacts contain no credentials or real private project content and
      have private permissions, bounds, redaction and retention behavior tested.
- [ ] Reasoning effort is changeable from `/settings` with zero typed arguments
      and persists explicitly.
- [ ] Offline suite, security suite and Ruff pass. Dependency audit passes when
      dependencies change; otherwise record that no dependency changed.
- [ ] Release gates still pass: zero hard-security failures, tool choice ≥95%,
      rubric ≥90%, and completion within 5pp of the fresh paired baseline.
