# Tool-Schema Routing

RadSim registers 72 tools. Sending every schema on every request costs about
7,448 estimated input tokens before any conversation content. Routing sends a
core set plus the capability groups a turn actually indicates.

Routing is opt-in and off by default.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `RADSIM_TOOL_SCHEMA_ROUTING` | unset (off) | `1`, `true`, `yes`, or `on` enables routing |
| `RADSIM_TOOL_SCHEMA_BUDGET_TOKENS` | `4000` | Maximum estimated tokens for routed schemas, floored at 1000 |

## How a turn is routed

1. `process_message` routes once, before the first provider call, so the schema
   set is stable for the whole turn and does not invalidate cached prefixes.
2. The core set is always sent: the plan's common capability tools plus
   `submit_completion`, `todo_read`, and `todo_write`, which the agent loop
   itself depends on. Core costs 1,675 estimated tokens.
3. A capability group is selected when the request contains one of its curated
   keywords or names one of its tools. Matching is on whole words, so
   "recommitment" does not select the git group.
4. MCP and extension tools are unclassified and form the `external` group. They
   load only when the request names them or mentions `mcp`, `server`, or
   `integration`.
5. If the selection exceeds the token budget, groups are dropped from the lowest
   declaration priority upward. Core tools are never dropped.

## Fallback recovery

The model can still name a tool whose schema was routed away. Routing never
blocks execution: the call runs through the unchanged permission path, and the
tool's whole group is restored for the rest of the turn. Each recovery emits a
`tool_routing_recovery` telemetry event, so the plan's "under 2 percent of turns
need a routing recovery" target is measurable.

## Failing open

Routing returns the full registry unchanged when a schema has no name or two
schemas share a name. The `tool_routing` event records `routing_failed` so a
misclassified registry is visible rather than silently narrowing the tool
surface.

## Security

Routing filters provider-facing schemas only. Permission tiers, confirmation
prompts, secret checks, and policy checks in `_execute_with_permission` are
untouched, and no tool becomes executable that was not executable before.

## Telemetry

With `RADSIM_PERFORMANCE_TELEMETRY=1`, each turn records:

- `tool_routing`: selected groups, dropped groups, routed tool count, estimated
  schema tokens, budget, and whether routing failed open
- `tool_routing_recovery`: the recovered tool, its group, and the new tool count

## Verifying the reduction

```bash
python -m pytest tests/test_tool_router.py tests/property/test_tool_router_invariants.py -q -p no:randomly
python -m pytest benchmarks -q -p no:randomly --benchmark-json=routing.json
```
