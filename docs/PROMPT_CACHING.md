# Prompt Caching

Anthropic renders a request as tools, then system, then messages, and caches by
exact prefix match. RadSim marks two breakpoints so the fixed part of a request
is billed at cache-read rates instead of full input rates.

Caching changes cost and latency only. Prompt text, the tool set, and every
permission decision are unchanged.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `RADSIM_PROMPT_CACHING` | on | `0`, `false`, `no`, or `off` sends every request uncached |

## Where the breakpoints go

1. **End of the static policy.** `get_static_prompt()` is the repository-controlled
   surface — the base policy plus the checked-in markdown fragments — and
   `_build_prompt_layers` already emits it first. Marking its last block caches
   the routed tool schemas and the policy together, because tools render before
   system.
2. **Last conversation block.** Marked only when the final message's content is
   a block list, which is the shape of every tool-result message. A plain-string
   message is left alone rather than reshaped, so tool-use pairing is never
   rewritten to win a cache entry.

Runtime layers — modes, skills, `custom_prompt.txt`, project memory — sit after
the first breakpoint. Toggling a mode invalidates the conversation entry but
leaves the tools-plus-policy entry intact.

Two breakpoints, against a provider maximum of four.

## When caching is skipped

`plan_system_cache` returns a reason rather than marking blocks:

| Reason | Meaning |
| --- | --- |
| `disabled` | `RADSIM_PROMPT_CACHING` is off |
| `no_system_prompt` | Nothing stable to cache |
| `unsupported_model` | The model is not an Anthropic Claude model; `cache_control` does not apply |
| `below_minimum` | The prefix is shorter than the provider's minimum, which would silently not cache |

Minimums are model-specific: 512 tokens on Opus 5 / Fable 5 / Mythos 5, 1024 on
Opus 4.8 and Sonnet 5, 2048 on Opus 4.7, 4096 on Opus 4.6 and Haiku 4.5.
Unrecognised models fall back to 1024; if that guess is low the provider simply
does not create an entry, at no extra cost.

## Providers

- **Anthropic direct** — both breakpoints.
- **OpenRouter, Anthropic models** — the system breakpoint only. OpenRouter
  forwards `cache_control` to Anthropic upstreams, but conversation block
  placement differs per upstream, so RadSim does not guess.
- **Everything else** — untouched. OpenAI caches automatically and has no
  `cache_control` field.

## The trade-off

A cache write costs 1.25× the base input rate; a read costs 0.1×. Modelled
against a 4,640-token prefix (1,675 routed schema tokens plus 2,965 policy
tokens), in `benchmarks/prompt-cache-baseline.json`:

| Provider requests in a turn | Change in billed prefix tokens |
| ---: | ---: |
| 1 | +25% |
| 3 | −52% |
| 5 | −67% |
| 8 | −76% |

A turn that calls any tool issues at least two requests, and the 5-minute
ephemeral TTL means a follow-up turn reads the entry the previous turn wrote.
Only a session of exactly one tool-free turn, or turns more than five minutes
apart, pays the write premium — which is why caching is on by default rather
than opt-in. Set `RADSIM_PROMPT_CACHING=0` for one-shot batch usage.

## Prompt deduplication — not applied

Plan section 7.3 pairs caching with removing duplicated prompt prose. It was
attempted and reverted. Two findings:

1. **The available saving is negligible.** The only genuine non-safety duplicate
   is the "lead with the answer" rule, stated in both `personality.md` and
   `response_style.md`. Folding it into one place saves 9 estimated tokens out of
   2,974 — 0.3% of the static policy. Every other apparent overlap is a security,
   authority, or permission statement, where repetition is deliberate.
2. **The repository already gates prompt edits.** `tests/test_prompt_eval_gate.py`
   requires the shipped prompt to match a digest cleared by a live eval matrix
   run, because a prompt edit that passed the entire offline suite once still made
   the model read `.env` and disclose a password. Changing prompt text means
   re-running that matrix against real models and regenerating
   `tests/evals/prompt_attestation.json`.

Nine tokens does not justify a live eval run. If a future change makes the
deduplication worthwhile, `test_static_policy_keeps_its_load_bearing_safety_rules`
asserts the load-bearing safety rules survive it, and the eval matrix must clear
the result before it ships.

## Measuring the result

Cache activity is already accounted for. `/cost` shows cache reads, cache writes,
and their share of input, and `usage.py` normalises both the Anthropic
(`cache_creation_input_tokens`, `cache_read_input_tokens`) and OpenAI-style
(`prompt_tokens_details.cached_tokens`) shapes.

With `RADSIM_PERFORMANCE_TELEMETRY=1`, each request records a `prompt_cache`
event with the applied flag, prefix tokens, provider minimum, and skip reason;
`provider_response` already carries `cache_read_input_tokens` and
`cache_write_input_tokens` for hit-rate calculation.

```bash
python -m pytest tests/test_prompt_cache.py tests/property/test_prompt_cache_invariants.py -q -p no:randomly
```
