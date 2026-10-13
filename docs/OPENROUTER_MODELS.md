# OpenRouter model catalogue

RadSim uses OpenRouter's public model endpoint as the source of truth. The full
catalogue is available from the model picker, cached for 24 hours, constrained
to a 5 MB response and 5,000 validated entries, and replaced by the checked-in
complete bundled snapshot when live and cached catalogues are unavailable.

The bundled catalogue was verified on 13 October 2026 against
`https://openrouter.ai/api/v1/models`:

- all 459 returned model identifiers are bundled in `radsim/openrouter_catalogue.json`
- 315 support interactive text and tool calling and appear in the full picker,
  ordered newest first; batch and incompatible models remain in the catalogue
- all 25 curated shortcuts are available and support tools, including GPT-6.1 Sol,
  GPT-6 Astra, Claude 5.5, Muse Wonder, Step 5 Preview, Mistral Large 4,
  Gemini 3.8 Flash and Grok 4.7
- context, pricing, cache rates, sampling and reasoning metadata come from the
  same response; GLM 5.3 remains the first-run default

Live and cached catalogues take precedence over the bundled snapshot. Offline
prices from the snapshot are labelled `bundled-catalogue`, with their fetch time
and a stale flag. Context limits also prefer catalogue metadata over the older
static table. If the bundled file is missing or invalid, the curated emergency
fallback remains available. The August evidence in
`benchmarks/openrouter-catalogue-2026-08-28.json` is historical.

Primary and subagent model validation uses the full compatible catalogue, so
selecting a model outside the 25 curated shortcuts does not reject it.

No API key is sent to the public catalogue endpoint, and catalogue fields are
treated as untrusted data: strings, prices, parameters, model counts, response
bytes, and cache files all pass explicit validation and size limits.
