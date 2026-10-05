# OpenRouter caching and cost review

Reviewed: 2026-09-30. Scope: report only; implementation unchanged. No account settings, billing history, credentials or paid requests were accessed.

RadSim already enables its explicit cache planner by default. That does not establish a cache hit or prove the chosen model/provider is the cheapest for a completed task. Actual account configuration and savings remain unverified.

## Current implementation

| Area | Verified behavior | Source |
| --- | --- | --- |
| Switch | `RADSIM_PROMPT_CACHING` defaults on; `0`, `false`, `no`, `off` disable RadSim's markers. This switch does not disable upstream automatic caching. | `radsim/prompt_cache.py:65` |
| Models | Explicit markers are restricted to names containing `claude` or `anthropic/`. Other models receive ordinary messages. | `radsim/prompt_cache.py:72` |
| Prefix | Stable repository policy precedes runtime layers; estimated tokens use characters divided by four. Current static policy estimate: 2,974 tokens. | `radsim/prompt_cache.py:90` |
| OpenRouter | Marks the stable system block only. It does not mark conversation history or include tool-schema tokens in the eligibility estimate. | `radsim/api_client.py:919` |
| Routing | No explicit session ID, provider ordering, price sorting, parameter requirement or price ceiling is sent by this client. Reasoning effort is passed when supported. | `radsim/api_client.py:866` |
| Accounting | Records reported cost, cache reads/writes, routed provider and response model. Estimates require available price fields. | `radsim/usage.py:13`; `radsim/pricing.py:101` |

## Findings

The model threshold lookup uses dash-separated family names. A direct local probe returned 1,024 for `anthropic/claude-opus-4.7`, versus 2,048 for `claude-opus-4-7`. OpenRouter currently documents 4,096 for Opus 4.7. The planner can therefore label an undersized prefix eligible. The 2,974 estimate covers policy alone: upstream tool schemas may bring the complete prefix above the minimum, so this does not prove cache misses. Exact token counts and response usage are required. [OpenRouter cache requirements](https://openrouter.ai/docs/guides/best-practices/prompt-caching)

OpenRouter supports automatic caching for many models and explicit Claude breakpoints. Its default stickiness derives from opening messages; a stable `session_id` pins successful requests sooner. Manual provider ordering overrides stickiness. Changing runtime system content can change the default conversation key. [OpenRouter caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching)

For Claude Opus 4.7, five-minute writes cost 1.25 times ordinary input, reads 0.1 times; one-hour writes cost twice ordinary input. Newer Claude families have different read rates. [Anthropic cache pricing](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

Default routing favors healthy, cheaper providers using price-weighted selection; it does not guarantee the cheapest endpoint. `provider.sort="price"` requests price ordering, `require_parameters=true` excludes incompatible endpoints, and `max_price` imposes ceilings. Account preferences can further affect eligibility; these were not inspected. [OpenRouter provider selection](https://openrouter.ai/docs/guides/routing/provider-selection)

## Cost decision

Illustrative calculation using the Opus 4.7 rates above, not measured billing: six identical prefix uses within one five-minute cache window cost `1.25 + 5 × 0.1 = 1.75` ordinary-prefix units, versus six without caching: about 70.8% less for that reused portion. Output, reasoning, changing input, retries and other fees remain additional costs. A five-minute write pays back with one read; a one-hour write needs two reads under those rates.

## Recommended next steps

1. Normalize model IDs and refresh thresholds from provider documentation. Test dot/dash aliases and undersized prefixes. Include tool schemas in the planner estimate where request construction permits it.
2. Add a stable, non-secret session ID for each agent conversation. Evaluate compatible Claude conversation breakpoints without changing tool-call pairing or prompt content.
3. Compare existing routing with price ordering and parameter enforcement. Keep fallbacks; measure total cost per successfully completed task alongside latency and failures.
4. Use reported cost and cache counters to verify repeated-turn savings. Do not apply one generic cache price to every model: current OpenRouter documentation reports write charges for newer OpenAI families too. [Model-specific cache pricing](https://openrouter.ai/docs/guides/best-practices/prompt-caching)

These are proposals. No caching/routing changes or paid experiment were performed. A billing experiment requires the user's explicit approval for `OPENROUTER_API_KEY` through the secrets wrapper.
