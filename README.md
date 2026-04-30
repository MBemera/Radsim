# RadSim

RadSim is a local CLI coding agent for developers.

It runs in your terminal, uses your own provider API key, and gives an AI model
controlled access to local tools. It can read files, search code, edit files,
run shell commands, use git, call browser/web tools, keep memory, and run
slash-command workflows.

RadSim is designed for local development workflows. Model requests are sent to
the provider you configure.

Package name: `radsimcli`

Current version in `main`: `1.4.0`

Python: `3.10+`

## Overview

RadSim is a Python package that installs a `radsim` command.

RadSim supports provider selection for:

- `openrouter`
- `openai`
- `claude`

RadSim has an agent loop:

1. You type a task.
2. RadSim sends the conversation, system prompt, and tool definitions to the
   selected provider.
3. The model replies with text or tool calls.
4. RadSim runs approved tools locally.
5. Tool results go back to the model.
6. The loop continues until the task is done or you stop it.

## What It Can Do

- Interactive agent sessions with `radsim`
- One-shot tasks with `radsim "your task"`
- File reads, writes, renames, deletes, and multi-file patches
- Regex search, glob search, symbol lookup, and repo maps
- Shell commands, tests, linting, formatting, and type checks
- Git status, diff, log, branch, add, commit, checkout, and stash
- Browser and web fetch tools
- Docker, SQLite, deploy-readiness, and dependency helpers
- Persistent memory and user skills
- Todo tracking
- Background sub-agent jobs
- Scheduled jobs
- Telegram integration
- Optional MCP server tools
- Runtime custom tools through `add_tool`

## How It Runs

- RadSim runs locally from your terminal.
- RadSim uses the provider account and model you configure.
- Model usage is billed by your selected provider.
- The main agent loop calls the selected provider client directly.
- Review AI-generated changes before using them in production.
- Code that RadSim includes in a prompt is sent to the selected model provider.

## Install

Install from PyPI:

```bash
python3 -m pip install radsimcli
```

Check it:

```bash
radsim --version
```

Install from source:

```bash
git clone https://github.com/MBemera/Radsim.git
cd Radsim
python3 -m pip install -e ".[dev]"
```

Run the CLI after installing:

```bash
radsim
```

## First Run

Start RadSim:

```bash
radsim
```

The setup flow asks for:

- Terms acceptance
- Basic user preferences
- Provider
- Model
- API key

Run setup again:

```bash
radsim --setup
```

Use one-shot mode:

```bash
radsim "Find the failing tests and explain the cause"
radsim "Add input validation to the API handler"
radsim --yes "Format the project and fix lint errors"
```

`--yes` skips many confirmation prompts. Use it only when you are comfortable
with the requested changes.

## Providers

RadSim reads provider config from `~/.radsim/.env`.

```bash
RADSIM_PROVIDER="openrouter"
RADSIM_MODEL="moonshotai/kimi-k2.5"

OPENROUTER_API_KEY="sk-or-..."
OPENAI_API_KEY="sk-..."
ANTHROPIC_API_KEY="sk-ant-..."
```

Provider model lists configured in `main`:

| Provider | Models listed in code |
| --- | --- |
| OpenRouter | `moonshotai/kimi-k2.5`, `anthropic/claude-opus-4.6`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.4`, `openai/gpt-5.3-codex`, `openai/gpt-5.2-codex`, `minimax/minimax-m2.1`, `z-ai/glm-4.7` |
| OpenAI | `gpt-5.4`, `gpt-5.3-codex`, `gpt-5.2`, `gpt-5.2-codex`, `gpt-5-mini` |
| Claude | `claude-opus-4-6`, `claude-sonnet-4-5`, `claude-haiku-4-5` |

OpenRouter can fetch a live model catalogue and cache it under `~/.radsim`.
If that fetch fails, RadSim falls back to the static list above.

Login helpers:

```bash
radsim login openrouter
radsim login openai
radsim login claude
radsim logout openrouter
```

## Configuration Files

RadSim stores user-level state in `~/.radsim`.

| File or directory | Purpose |
| --- | --- |
| `~/.radsim/.env` | Provider, model, and API keys |
| `~/.radsim/settings.json` | Reasoning effort, rate limits, and UI settings |
| `~/.radsim/memory/` | Persistent memory |
| `~/.radsim/schedules.json` | Scheduled jobs |
| `~/.radsim/mcp.json` | MCP server config |
| `~/.radsim/models_cache.json` | Cached OpenRouter model catalogue |

Project-local `.env` files are intentionally ignored for RadSim config.

## Main Commands

| Command | Purpose |
| --- | --- |
| `/help` | Show help |
| `/tools` | List tools |
| `/commands` | List slash commands |
| `/config` | Change provider or API key |
| `/switch` | Switch provider/model |
| `/login` | Save provider credentials |
| `/logout` | Remove provider credentials |
| `/free` | Switch to the configured free OpenRouter option |
| `/ratelimit` | Set API call limit per turn |
| `/clear` | Clear conversation history |
| `/new` | Start fresh context |
| `/memory` | Manage memory |
| `/skill` | Manage custom instructions |
| `/teach` | Toggle teach mode |
| `/settings` | View or change agent settings |
| `/plan` | Plan-confirm-execute workflow |
| `/panning` | Brain-dump processing |
| `/background` | Manage background sub-agent jobs |
| `/job` | Manage scheduled jobs |
| `/mcp` | Manage MCP server connections |
| `/telegram` | Configure Telegram integration |
| `/complexity` | Complexity budget and scoring |
| `/stress` | Adversarial code review |
| `/archaeology` | Find dead code |
| `/exit` | Exit |
| `/kill` | Hard stop |

## Tool Groups

RadSim currently defines 68 built-in tools.

| Group | Examples |
| --- | --- |
| Files | `read_file`, `write_file`, `replace_in_file`, `multi_edit`, `apply_patch` |
| Directories | `list_directory`, `create_directory` |
| Search | `glob_files`, `grep_search`, `search_files`, `repo_map` |
| Code intel | `find_definition`, `find_references`, `analyze_code` |
| Shell | `run_shell_command` |
| Git | `git_status`, `git_diff`, `git_log`, `git_add`, `git_commit` |
| Testing | `run_tests`, `lint_code`, `format_code`, `type_check` |
| Dependencies | `list_dependencies`, `add_dependency`, `pip_install`, `npm_install` |
| Browser/web | `browser_open`, `browser_click`, `browser_type`, `browser_screenshot`, `web_fetch` |
| Memory | `save_memory`, `load_memory`, `forget_memory` |
| Tasks | `todo_read`, `todo_write`, `plan_task`, `delegate_task` |
| Integrations | `send_telegram`, MCP tools when configured |
| Advanced | `run_docker`, `database_query`, `generate_tests`, `refactor_code`, `deploy` |
| Self-extension | `add_tool`, `list_custom_tools`, `remove_tool` |

Browser tools need Playwright browsers installed:

```bash
python3 -m playwright install chromium
```

MCP support is optional:

```bash
python3 -m pip install "radsimcli[mcp]"
```

## Safety

RadSim runs tools on your machine.

RadSim asks before actions that can change your environment. `--yes` and
learned trust rules can auto-confirm selected actions.

Confirmed actions include:

- File writes and deletes
- Shell commands
- Git writes
- Dependency changes
- Formatting
- Database queries
- Deploy commands
- Memory writes
- Scheduled jobs
- Custom tool changes
- Telegram sends

Security:

- API keys are stored in `~/.radsim/.env` with `chmod 600`.
- Known secret paths such as `.env`, `credentials`, and private keys are protected.
- Provider config is read from `~/.radsim/.env`.
- Startup may check GitHub releases. Use `--skip-update-check` to skip release checks.
- OpenRouter model selection may call the OpenRouter model API.
- Anything sent to your selected model provider is subject to that provider's terms.

Disable update checks:

```bash
radsim --skip-update-check
```

## Architecture

Important files:

| Path | Purpose |
| --- | --- |
| `radsim/cli.py` | CLI entry point, argument parsing, startup flow |
| `radsim/agent.py` | Main agent class |
| `radsim/agent_api.py` | API calls, streaming, tool-call loop |
| `radsim/agent_policy.py` | Tool permissions and confirmation policy |
| `radsim/api_client.py` | Claude, OpenAI, and OpenRouter clients |
| `radsim/config.py` | Provider models, defaults, pricing, settings |
| `radsim/tools/` | Tool definitions and implementations |
| `radsim/commands*.py` | Slash command registry and handlers |
| `radsim/safety.py` | Path checks and confirmation helpers |
| `radsim/memory.py` | Persistent memory |
| `radsim/mcp_client.py` | Optional MCP integration |
| `radsim/telegram.py` | Telegram integration |
| `radsim/scheduler.py` | Scheduled jobs |
| `radsim/model_router.py` | Experimental routing utilities |
| `tests/` | Pytest test suite |

## Development

Install dev dependencies:

```bash
python3 -m pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Run lint:

```bash
ruff check .
```

## License

MIT. See [LICENSE](LICENSE).
