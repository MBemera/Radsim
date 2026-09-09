# ChatGPT subscription inside RadSim

<<<<<<< HEAD
Researched 2026-09-06. Base: `050381e`.
=======
The ChatGPT subscription is a normal RadSim provider. RadSim owns the agent
loop, tool dispatch, confirmations, memory, conversation and slash commands.
Only model inference goes to the subscription endpoint. Codex's app server
manages sign-in, token refresh, model discovery and account quota; it does not
run the coding session.
>>>>>>> 72225ba (Fix ChatGPT streaming inside the RadSim harness)

## Use it

```bash
radsim login chatgpt
radsim
```

Sign-in remembers the subscription and the account's default model. You can
also select it explicitly with `radsim --provider chatgpt`, or use `/switch`
inside an existing RadSim session and choose ChatGPT subscription, then
"Use the subscription in this session". No separate runtime or restart is needed.

```bash
radsim status chatgpt
radsim models chatgpt
radsim logout chatgpt
```

The same account actions are available in the `/switch` menu. Standard RadSim
commands remain available. A model can be selected with `--model`; model names
from another provider are not silently reused for the subscription.

## Implementation

| Module | Responsibility |
| --- | --- |
| `chatgpt_client.py` | Convert RadSim messages/tools to Responses requests and streamed output back to RadSim blocks; subscription endpoint only, no API fallback. |
| `chatgpt_tokens.py` | Read RadSim's Codex sign-in and request refresh through Codex when needed. |
| `codex_transport.py` | Bounded stdio JSON-RPC with deadlines and process cleanup for account operations. |
| `codex_connection.py` | Private state, scrubbed child environment and tested Codex version check. |
| `codex_auth.py`, `codex_cli.py` | Sign-in, sign-out, account quota and model list. |
| `config.py`, `commands_core.py`, `agent_conversation.py` | Normal provider startup and live switching; construct a usable client before changing active configuration. |

The earlier implementation used Codex-owned sessions. Matt rejected that
architecture; it was replaced in commit `e7f3620`. `codex_runtime.py` and
`codex_approvals.py` were deleted. Tests and controls for that deleted runtime
are not evidence for the current RadSim tool loop.

## Verification and compatibility

The September 7 review reproduced two blockers missed by mocked provider tests:

- OpenAI 1.109.1 crashes decoding Responses streams on Python 3.14 with an
  AttributeError involving `typing.Union.__discriminator__`. The integration
  now requires OpenAI >=2.29.0,<3.0; `requirements.txt` pins tested 2.29.0.
- Live subscription streams contain complete function calls and text in
  `response.output_item.done`, but may have empty final response output.
  RadSim retains those completed items instead of dropping tool calls.

A live synthetic test completed two subscription requests through the real
`RadSimAgent`: the model requested `read_file`, RadSim read the fixture, and the
model streamed its exact contents back. No personal documents were used.

`tests/test_chatgpt_harness.py` uses the real OpenAI SDK with an HTTP mock
transport and the real RadSim loop, tools, history, usage and approval policy.
It covers streaming and non-streaming display and a rejected file write.
Provider tests also cover failed/incomplete streams, early termination,
credential changes and logout during an existing session, and stream cleanup.
See [the current handoff](../uptodate.md) for final check/install/commit status.

## Security and limits

- RadSim's sign-in is under `~/.radsim/chatgpt/codex/`, separate from API keys.
  Tokens stay local and are sent only as authentication to the fixed HTTPS
  subscription endpoint. Token values must never appear in logs or reports.
- Credentials are checked before every model request, so expiry can refresh and
  logout prevents an already-running client from making another request.
- Failed client construction preserves the original provider/client together.
  Switching to the subscription preserves saved API keys for later explicit use.
- No automatic API-billing fallback and no hidden SDK request retries.
- Incomplete/failed streams cannot dispatch partial tools. Finished items are
  bounded by output index, and the stream closes on completion or cancellation.
- Existing RadSim permission checks, turn rate limits and session budgets apply.
  Authentication/authorization, input validation, error handling and auditability
  are tested at relevant boundaries; no new server, database or listener is added.
- The subscription endpoint is not a documented public API. Its contract can
  change; it requires streaming and rejects `max_output_tokens`, so a model-side
  output-token ceiling is unavailable. The Codex CLI pin only checks account
  protocol compatibility, not future backend behavior.
- Primary-provider support does not add subscription support to RadSim's
  independently configured subagents. Codex account operations require 0.153.4.

These checks map to NIST SSDF/CSF verification, OWASP input/access controls,
CIS least privilege and SLSA/OpenSSF dependency provenance. This is a scoped
engineering check, not certification or a full security audit. OpenAI's
[official SDK documentation](https://developers.openai.com/api/docs/libraries)
identifies the supported Python library; live subscription behavior above is
based on the local integration test, not a public API support guarantee.
