# ChatGPT subscription access in RadSim

Researched 2026-09-06. Base: `050381e`.

## Finding

ChatGPT subscription access is feasible through Codex authentication. OpenAI
distinguishes ChatGPT sign-in from separately billed Platform API-key access.
`codex login` starts the browser sign-in flow. Adding an API key to RadSim does
not select subscription billing. Account entitlement and remaining quota still
need verification after the user signs in. [OpenAI authentication](https://learn.chatgpt.com/docs/auth)

This branch contains research and an implementation plan. Subscription login
and inference are **not implemented or live-tested** in RadSim.

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

## Acceptance and security checks

Required tests: successful/cancelled login, expiry, revoked access, missing
binary, malformed/oversized messages, timeout, child-process exit, interrupted
stream, denied file/shell actions, workspace escape attempts, unknown tool calls,
quota exhaustion without API fallback, and session resume without duplicate
tool execution. Use synthetic fixtures with no real credential strings.

Standards check for this research change: plain documentation only; no runtime,
dependency, network exposure or permission changes. No credentials were requested
or read and no model requests were made. Proposed controls map to NIST SSDF/CSF
verification, OWASP input/access controls, CIS least privilege and SLSA/OpenSSF
dependency/version provenance; this is not a certification or completed audit.
Dependency audit and runtime tests are not applicable to these documentation
changes. The integration's controls remain planned and unverified.

## Verified limits

- Local branch created; existing unrelated `radsim.md` edit preserved.
- Repository source and official product documentation inspected.
- Codex version/help/schema generation succeeded. CLI emitted a sandbox PATH
  alias warning; it did not prevent schema generation.
- Account plan, sign-in, available models, quota and end-to-end inference:
  **Not verified**. No installed RadSim replacement or publication performed.
- Branch starts at the inspected local optimisation tip; remote freshness was
  not checked and no fetch, pull or merge was performed.
