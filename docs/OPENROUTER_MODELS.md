# OpenRouter model catalogue

RadSim uses OpenRouter's public model endpoint as the source of truth. The full
catalogue is available from the model picker, cached for 24 hours, constrained
to a 5 MB response and 5,000 validated entries, and replaced by the checked-in
curated list only when live and cached catalogues are unavailable.

The curated fallback was verified on 28 August 2026 against
`https://openrouter.ai/api/v1/models`:

- all 25 curated model identifiers were available
- all 25 advertised tool support
- GLM 5.3 became the first-run default
- GLM 5.3 Flash, Claude Opus 5, Claude Sonnet 5, Gemini 3.7 Flash, Grok 4.6,
  Qwen3.8 Max, and Seed 2.0 Code were added
- static context, pricing, sampling, and reasoning metadata was refreshed from
  the same response

The checked-in evidence is
`benchmarks/openrouter-catalogue-2026-08-28.json`. Runtime catalogue pricing
still takes precedence over this dated fallback, and the UI can browse every
live model rather than only this shortlist.

No API key is sent to the public catalogue endpoint, and catalogue fields are
treated as untrusted data: strings, prices, parameters, model counts, response
bytes, and cache files all pass explicit validation and size limits.
