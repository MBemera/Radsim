<p align="center">
  <img src="docs/assets/radsim_banner.png" alt="RadSim — radically simple agents" width="520">
</p>

# RadSim

RadSim (`radsimcli` on PyPI) is a coding agent that runs in your terminal. You
configure a provider API key, type a task, and the agent edits files, runs
commands, uses git, and reports back. The model never holds your code — it
sits on your machine, calls a model over the network, and sends back tool
results until the task is done.

It works on Python 3.10+, macOS, Linux, and Windows. The current version on
`main` is `1.4.1`.

## Why RadSim exists

Most AI coding tools are tuned for impressive demos. The output runs once and
then becomes a maintenance burden — clever one-liners, deep nesting, abstractions
invented for problems that aren't there. RadSim was built around the opposite
default: **the simplest version of a thing that actually works.** That rule
applies in two places:

1. **The code RadSim writes for you.** The system prompt and built-in skills
   push the model toward flat control flow, descriptive names, single-purpose
   functions, and standard patterns that any other agent (or a junior developer)
   can read on the first pass. There is a slash command, `/stress`, that runs an
   adversarial review against those rules.

2. **RadSim itself.** The agent loop is short, the file layout is flat, the
   provider clients are thin wrappers, and the tool registry is a dictionary.
   When something breaks, you can find it.

It is also local-first. There is no server-side account, no project upload, no
"cloud workspace." Your code is read from disk, sent to the model you chose,
and the response goes through tool calls that run on your machine. If you
revoke the API key, RadSim stops working — there's nowhere else for it to go.

## How the agent loop works

1. You type a task — either as a single argument (`radsim "fix the failing test"`)
   or interactively after `radsim`.
2. RadSim sends three things to your provider: the conversation so far, a
   system prompt, and the list of tool definitions the model is allowed to call.
3. The model replies with text, with tool calls, or both.
4. For each tool call, RadSim either runs it immediately (read-only operations)
   or asks you to confirm (anything that mutates state).
5. The tool result goes back to the model.
6. Steps 3–5 repeat until the model has nothing left to do or you stop the loop
   with `Ctrl+C` / `/kill`.

Two design choices fall out of this:

- **The model never executes code directly.** Everything that touches your
  machine goes through a named tool with a defined schema. That's what lets
  RadSim show you a diff before writing a file, or a command before running it.

- **Confirmations are policy, not friction.** The model can request a destructive
  action, but you decide whether it happens. Trust patterns are learned per
  action type so the prompts get less chatty over time without removing the
  guardrail.

## Why OpenRouter is the default provider

RadSim supports `openrouter`, `openai`, and `claude` directly. OpenRouter is the
recommended starting point because:

- **One key, many models.** You can switch between Kimi K2.5, Claude Sonnet,
  GPT-5 variants, and others by changing a single string. No second signup, no
  second billing relationship.
- **Cheap models are practical for daily use.** Kimi K2.5 is currently the
  configured default at `$0.14` input / `$0.28` output per million tokens. A
  full coding session usually costs less than a coffee, which makes "let it
  rerun" a reasonable choice instead of a budget event.
- **Live model catalogue.** OpenRouter publishes the full list of available
  models with their context windows and capabilities. RadSim caches that under
  `~/.radsim/models_cache.json` and falls back to a static list if the fetch
  fails.

If you already pay for Anthropic or OpenAI directly, those providers are first-
class — there's no degraded path. The provider layer is the same code shape;
OpenRouter is just the most flexible starting point.

## Install

From PyPI:

```bash
python3 -m pip install radsimcli
```

From source (recommended if you want to read the code or send PRs):

```bash
git clone https://github.com/MBemera/Radsim.git
cd Radsim
python3 -m pip install -e ".[dev]"
```

Verify:

```bash
radsim --version
```

## First run

Run `radsim` with no arguments. The setup wizard asks for:

- Terms acceptance.
- A provider (`openrouter`, `openai`, or `claude`).
- A model from that provider's list.
- An API key, which is written to `~/.radsim/.env` with `chmod 600`.

You can re-enter the wizard at any time with `radsim --setup`. Once configured:

```bash
# Interactive mode
radsim

# One-shot mode
radsim "Find the failing tests and explain the cause"
radsim "Add input validation to the API handler"

# Skip confirmation prompts (use deliberately)
radsim --yes "Format the project and fix lint errors"
```

## Where RadSim looks for `.env`

In priority order, highest first:

1. `RADSIM_ENV_FILE` if it points at a real file.
2. A `preferred_env_file` saved as a memory preference.
3. `.env` in your **current working directory**.
4. The `.env` next to the installed RadSim source (used during development).
5. `~/.radsim/.env` (the global config).

Earlier files win on conflicting keys. This means you can drop a `.env` in any
project to override the global one without touching `~/.radsim`.

## Slash commands

Slash commands exist because there are workflows you'll reach for often enough
that typing them as a prompt would be wasteful. They all work mid-session.

| Command | What it does |
| --- | --- |
| `/help`, `/commands` | Show help, list slash commands. |
| `/tools` | List the tools the model can currently call. |
| `/switch`, `/free` | Change provider/model now (and persist to `~/.radsim/.env`). `/free` jumps to the cheapest OpenRouter model. |
| `/login`, `/logout` | Save or remove provider credentials. |
| `/config`, `/settings` | Re-run the setup wizard or inspect agent settings. |
| `/ratelimit` | Cap how many tool calls the model can make per turn. |
| `/clear`, `/new` | Forget the current conversation; start fresh. |
| `/memory` | Inspect or edit persistent memory. |
| `/skill` | Manage your custom-instruction skill files. |
| `/teach` | Toggle teach mode (annotated diffs, slower pace). |
| `/plan`, `/panning` | Plan-then-execute and brain-dump processing workflows. |
| `/background`, `/job` | Start sub-agent jobs and scheduled jobs. |
| `/mcp`, `/telegram` | Connect to MCP servers; configure Telegram remote control. |
| `/complexity`, `/stress`, `/archaeology` | Score complexity, run adversarial review, find dead code. |
| `/exit`, `/kill` | Quit normally; emergency-stop the loop. |

## Tools, explained simply

The model gets 68 tools by default, grouped by what they let it do:

- **Look at your code.** `read_file`, `list_directory`, `glob_files`,
  `grep_search`, `repo_map`, plus symbol-level helpers like `find_definition`
  and `find_references`. None of these mutate anything; they don't ask for
  confirmation.

- **Change your code.** `write_file`, `replace_in_file`, `multi_edit`,
  `apply_patch`. Each one shows you a diff before running.

- **Run things.** `run_shell_command`, `run_tests`, `lint_code`, `format_code`,
  `type_check`. These prompt for confirmation by default; learned trust can
  auto-confirm safe variants.

- **Use git.** Status, diff, log, branch, add, commit, checkout, stash. Reads
  are free; writes confirm.

- **Manage dependencies.** `pip_install`, `npm_install`, `add_dependency`,
  `list_dependencies`. Always confirms.

- **Talk to the web.** `web_fetch` for HTTP, plus a Playwright-driven browser
  (`browser_open`, `browser_click`, `browser_type`, `browser_screenshot`).
  Browser tools need `python3 -m playwright install chromium` first.

- **Remember things across sessions.** `save_memory`, `load_memory`,
  `forget_memory`. Memory is sanitized before write — anything that looks like
  an API key gets replaced with `[REDACTED_SECRET]`.

- **Stay organized.** `todo_read`, `todo_write`, `plan_task`, `delegate_task`
  for in-session tracking and farming work out to a sub-agent.

- **Heavier operations.** `run_docker`, `database_query`, `generate_tests`,
  `refactor_code`, `deploy`. All confirm.

- **Add more tools at runtime.** `add_tool` lets the model register a new
  tool by name, schema, and Python body. The new tool is appended to
  `radsim/tools/custom_tools.py` and hot-loaded into the live registry — no
  restart needed. `list_custom_tools` and `remove_tool` manage the result.

If you ask "can you do X?" and the answer is no, the right follow-up is often
"add a tool that does X" — that's a single `add_tool` call, not a code change.

MCP support is opt-in:

```bash
python3 -m pip install "radsimcli[mcp]"
```

## Safety

RadSim's safety model is simple: **anything that touches your machine confirms
unless you've trained the trust system to allow it.**

Confirmations cover file writes and deletes, shell commands, git mutations,
dependency changes, code formatting, database queries, deploys, memory writes,
scheduled jobs, custom-tool registration, and outbound Telegram messages.

A few hard rules don't bend even with `--yes`:

- API keys live in `~/.radsim/.env` with `chmod 600`.
- The agent cannot **write** to `.env`, credentials files, or known private-key
  paths. It can read them when you ask.
- Anything you include in a prompt gets sent to the provider you chose. That's
  how the model works; pick a provider whose data policy matches your context.

You can disable the GitHub release check at startup with `--skip-update-check`.

## Configuration files

Everything user-level lives under `~/.radsim`:

| Path | Purpose |
| --- | --- |
| `~/.radsim/.env` | Provider, model, and API keys. |
| `~/.radsim/settings.json` | Reasoning effort, rate limits, UI preferences. |
| `~/.radsim/memory/` | Persistent memory store. |
| `~/.radsim/schedules.json` | Scheduled jobs. |
| `~/.radsim/mcp.json` | MCP server config. |
| `~/.radsim/models_cache.json` | Cached OpenRouter model catalogue. |

## Architecture

For contributors. Files are flat under `radsim/`:

| Path | Purpose |
| --- | --- |
| `radsim/cli.py` | CLI entry point and startup flow. |
| `radsim/agent.py`, `agent_*.py` | Main agent class and conversation/policy mixins. |
| `radsim/api_client.py` | Provider clients (OpenAI, Anthropic, OpenRouter). |
| `radsim/config.py` | Provider lists, defaults, pricing, settings, env loading. |
| `radsim/tools/` | Tool definitions and implementations. |
| `radsim/commands*.py` | Slash command registry and handlers. |
| `radsim/safety.py` | Path checks and confirmation prompts. |
| `radsim/memory.py` | Persistent memory plus secret sanitization. |
| `radsim/mcp_client.py` | Optional MCP integration. |
| `radsim/telegram.py` | Telegram bridge. |
| `radsim/scheduler.py` | Scheduled jobs. |
| `tests/` | Pytest suite. |

## Development

```bash
python3 -m pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT. See [LICENSE](LICENSE).
