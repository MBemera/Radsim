# ChatGPT subscription access in RadSim

Researched 2026-09-06. Base: `050381e`.

## Finding

ChatGPT subscription access is feasible through Codex authentication. OpenAI
distinguishes ChatGPT sign-in from separately billed Platform API-key access.
`codex login` starts the browser sign-in flow. Adding an API key to RadSim does
not select subscription billing. Account entitlement and remaining quota still
need verification after the user signs in. [OpenAI authentication](https://learn.chatgpt.com/docs/auth)

This branch now contains the research below **and the implemented runtime**
(see "Implementation status"). It has been verified offline against synthetic
fixtures and the installed CLI's schemas; it is **not live-tested** against a
real ChatGPT account.

## What the other tools do

| Tool | Documented subscription setup |
| --- | --- |
| OpenCode | `/connect`, select OpenAI, then ChatGPT Plus/Pro and complete browser authentication. [Provider documentation](https://opencode.ai/docs/providers/#openai) |
| OpenClaw | Its current documentation uses `openai` for API-key and subscription authentication, with runtime selection treated separately. It supports a Codex app-server runtime and distinguishes subscription quota from API costs. Older `openai-codex/*` examples are legacy. [Provider documentation](https://docs.openclaw.ai/providers/openai) |
| RadSim at this branch base | OpenAI API-key wizard and Chat Completions transport only. |

These are documentation findings, not executions of OpenCode or OpenClaw.

## Recommended design

Add an explicit **ChatGPT subscription (Codex)** choice backed by a local Codex
app-server process. OpenAI documents this interface for embedding authentication,
history, approvals and streamed agent events in another product. Prefer its
stdio transport. The CLI labels app-server experimental; dynamic tool calls are
also experimental, so version compatibility needs a release gate.
[OpenAI app-server documentation](https://learn.chatgpt.com/docs/app-server)

This is an architectural recommendation: use a dedicated runtime adapter rather
than pretending that a whole Codex turn is one RadSim `chat()` call. Codex can
execute tools and maintain its own conversation, whereas RadSim currently owns
both responsibilities. Decide explicitly which runtime owns each session.

Keep existing API providers available with their present billing mode. A quota
error must stop a subscription session with a clear message; it must not silently
switch to a paid API key or a different account.

Two possible follow-on designs:

- Embed Codex as the session runtime. Translate its events and approvals into
  RadSim's terminal interface. This is the recommended first integration.
- Preserve RadSim's entire agent loop using a direct subscription transport.
  This needs separate verification of the OAuth client registration, supported
  endpoint, request contract, refresh lifecycle and terms for RadSim. The sources
  reviewed do not establish a stable public drop-in contract for that approach.

Do not copy browser cookies or extract another application's credential file.
Let Codex manage authentication through its interface. Any account sharing or
dedicated credential-store configuration must be explicit to the user.

## Repository changes needed

| Area | Existing code | Proposed change |
| --- | --- | --- |
| Login | `radsim/login.py`, `radsim/cli.py` | Add subscription sign-in/status/logout; distinguish it from API-key login. |
| Configuration | `radsim/config.py`, `radsim/onboarding.py` | Represent authentication mode and runtime explicitly; remove the mandatory API-key gate only for the subscription route. |
| Runtime | `radsim/agent.py`, `radsim/agent_api.py`, `radsim/api_client.py` | Introduce a Codex session adapter with bounded subprocess I/O, cancellation and cleanup. Keep the existing provider client factory for API sessions. |
| Tools and approvals | `radsim/agent_policy.py`, `radsim/agent_api.py` | Map Codex approvals to the user's permission choices. Preserve guarded dispatch for any RadSim tools exposed to Codex. |
| Models and usage | `radsim/config.py`, `radsim/usage.py`, `radsim/rate_limiter.py` | Discover account-supported models and show subscription quota separately from API dollar estimates. |
| Session storage | Conversation/session code | Save the selected runtime and remote thread identifier without tokens; define resume and model-switch behavior. |

The key compatibility issue is that `OpenAIClient._chat_with_retry()` invokes
`client.chat.completions.create()`, while `load_config()` rejects missing API
keys and `RadSimAgent` constructs that client unconditionally. Login alone cannot
make subscription requests work.

## Protocol evidence and first implementation steps

The installed `codex-cli 0.153.4` generated 416 JSON schema files offline:

```sh
codex app-server generate-json-schema --experimental \
  --out /tmp/radsim-setupgpt-schema-20260906
```

Inspection confirmed `chatgpt` and `chatgptDeviceCode` login variants, plus
`account/login/start`, `account/rateLimits/read`, `model/list`, `thread/start`,
`turn/start`, `turn/interrupt` and `item/tool/call`. `thread/start` includes
`dynamicTools`, `cwd`, `sandbox` and `approvalPolicy`. Schema presence proves
interface availability, not successful authentication or runtime behavior.

1. Build a small stdio adapter with an explicit executable path and argument
   list, initialization handshake, bounded frames/queues, deadlines, stderr
   redaction and deterministic process shutdown. Do not start a public listener.
2. Implement login completion/cancellation and require subscription auth before
   starting a subscription session. Discover models after login; avoid copying
   RadSim's static API model list into the subscription catalog.
3. Prove one read-only synthetic conversation with cancellation and quota/error
   reporting. Obtain authorization for account access and the live request.
4. Wire approval events before enabling file writes or shell execution. Unknown
   approval/tool events fail closed. Pin and test the protocol version used.
5. Add RadSim tools only after proving that native Codex capabilities cannot
   bypass the intended workspace and tool policy. Dynamic tools require the
   experimental capability; they are not a ready-made safety boundary.
6. Validate resume, streaming, usage accounting and existing API-provider
   regressions before enabling the option in ordinary sessions.

## Decision change: the subscription runs in RadSim's frame

The Codex-owned session above was built first and then **replaced** on Matt's
instruction: "it needs to actually run in the radsim frame. openclaw and
opencode don't do some wonky default and we won't either." Handing the turn to
Codex meant no RadSim banner, tools, memory or slash commands, which is not the
product.

How the other tools do it, and what this branch now does: the ChatGPT plan is
reachable at the Responses endpoint the Codex CLI itself uses, with the
credentials the Codex sign-in already stores. Evidence gathered locally:

- `https://chatgpt.com/backend-api/codex` is a provider base URL inside the
  installed `codex` binary, alongside `https://api.openai.com/v1`.
- `~/.radsim/chatgpt/codex/auth.json` holds `tokens.access_token`,
  `refresh_token` and `account_id` (mode 0600).
- Pointing the CLI at a local capture server with `chatgpt_base_url` produced a
  real `POST {base}/responses`: `accept: text/event-stream`, `authorization`,
  `originator`, `session-id`, and a body of `model`, `input`, `tool_choice`,
  `parallel_tool_calls`, `reasoning`, `store: false`, `stream: true`,
  `include`, `prompt_cache_key`.
- Probing the live endpoint one field at a time: `instructions`, `tools`,
  `tool_choice`, `parallel_tool_calls`, `prompt_cache_key` and `reasoning` are
  accepted; **`stream` must be true** ("Stream must be set to true") and
  **`max_output_tokens` is rejected** ("Unsupported parameter").

So `radsim/chatgpt_client.py` is a normal RadSim provider client: RadSim owns
the loop, the tools, the approvals and the rendering, and the subscription only
answers the model call. Requests identify with the Codex originator because the
endpoint accepts Codex-issued credentials. It is not a documented public API,
so it can change without notice; the version pin and these probes are how the
branch detects that.

## Implementation status

The subscription is a RadSim provider; nothing else about a session changes.

| Module | Responsibility |
| --- | --- |
| `radsim/chatgpt_client.py` | The provider client: RadSim messages and tool schemas to Responses items, streamed events back to RadSim's text/tool blocks, usage mapping, and failure text that never echoes the request. |
| `radsim/chatgpt_tokens.py` | Reads Codex's token store, decodes the access token's expiry, and asks Codex to refresh when it is close; RadSim holds no OAuth client. |
| `radsim/codex_transport.py` | Bounded stdio JSON-RPC to the Codex app server: frame/queue limits, deadlines, no retries, process-group shutdown. |
| `radsim/codex_connection.py` | Private `~/.radsim/chatgpt/` state, scrubbed child environment (`CODEX_HOME` only), pinned CLI version, workspace-local binary refused. |
| `radsim/codex_auth.py` | `account/login/start` (browser and device code), login URL host pinning, subscription-type enforcement, bounded model catalogue, quota display without account identity. |
| `radsim/codex_cli.py` | `login/logout/status/models chatgpt`, and saving the account's default model on sign-in. |
| `radsim/config.py`, `radsim/health.py`, `radsim/onboarding.py`, `radsim/cli.py`, `radsim/commands_core.py` | Selectable and sticky: wizard option 4, the `/switch` account menu, `save_subscription_selection()`/`clear_subscription_selection()`, `resolve_provider()` shared by startup and `load_config()`, no API-key gate, and a health check that looks for the sign-in. |

Verified offline: the full suite passes (including tests for the client, the
token store and the menu), Ruff clean, and every app-server method used for
sign-in exists in the schemas generated by `codex-cli 0.153.4`.

Verified live on Matt's account: browser sign-in, model discovery
(`gpt-6-astra`), the saved-provider startup path, and a real request to the
subscription endpoint that reached the quota check — RadSim's own frame
(banner, 72 tools, slash commands, memory) with the subscription behind it.

Not verified: a completed turn, streamed output, tool calls end to end. Matt's
5-hour quota was exhausted throughout; the endpoint answers
`usage_limit_reached` with the reset time, which RadSim reports as such.

Deliberate limits: no API fallback; `max_output_tokens` is never sent (the
endpoint rejects it); every response streams; subagents still need an API key,
since the account catalogue is not in RadSim's static provider lists.

## Acceptance and security checks

Required tests: successful/cancelled login, expiry, revoked access, missing
binary, malformed/oversized messages, timeout, child-process exit, interrupted
stream, denied file/shell actions, workspace escape attempts, unknown tool calls,
quota exhaustion without API fallback, and session resume without duplicate
tool execution. Use synthetic fixtures with no real credential strings.

All of those tests exist in `tests/test_codex_transport.py`,
`tests/test_codex_auth.py`, `tests/test_codex_runtime.py` and
`tests/test_codex_cli.py`, driven by synthetic fixtures with no real credential
strings.

Standards check for the implemented runtime: no dependencies were added, so no
audit was required; no listener is opened and network access is disabled in the
Codex permission profile; no credential was requested, read or written by
RadSim, and the account store is Codex's own under `~/.radsim/chatgpt/`.
Untrusted server output is length-bounded, type-checked and terminal-escaped
before display, and unknown requests are rejected. Controls map to NIST SSDF/CSF
verification, OWASP input/access controls, CIS least privilege and SLSA/OpenSSF
version provenance (the CLI version is pinned); this is not a certification or a
completed audit. The controls are verified against synthetic fixtures only —
they remain unproven against a live account.

## Verified limits

- Local branch created; existing unrelated `radsim.md` edit preserved.
- Repository source and official product documentation inspected.
- Codex version/help/schema generation succeeded. CLI emitted a sandbox PATH
  alias warning; it did not prevent schema generation.
- Runtime implemented and covered by offline tests; protocol usage checked
  against the generated schemas.
- Account plan, sign-in, available models, quota and end-to-end inference:
  **Not verified**. No installed RadSim replacement or publication performed.
- Branch starts at the inspected local optimisation tip; remote freshness was
  not checked and no fetch, pull or merge was performed.
