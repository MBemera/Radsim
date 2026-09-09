<p align="center">
  <img src="docs/assets/radsim_banner.png" alt="RadSim — radically simple agents" width="520">
</p>

# RadSim

> Radically simple by default — a coding agent that stays out of its own way.

RadSim (`radsimcli` on PyPI) is a coding agent that runs in your terminal. You
configure a provider API key, type a task, and the agent edits files, runs
commands, uses git, and reports back. The model never holds your code — it
sits on your machine, calls a model over the network, and sends back tool
results until the task is done.

It works on Python 3.10+, macOS, Linux, and Windows. The current version on
this branch is `1.6.2`.

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

- **One key, many models.** The curated selector includes GLM 5.3, Claude 5,
  GPT-5.6, Kimi K3, Gemini 3.7 Flash, Grok 4.6, Qwen3.8 Max, and other current
  models.
- **Your model choice persists.** RadSim reuses the provider and model you most
  recently selected instead of resetting each new instance. GLM 5.3 is the
  OpenRouter first-run fallback when no preference exists.
- **Live model catalogue.** OpenRouter publishes the full list of available
  models with their context windows and capabilities. RadSim caches that under
  `~/.radsim/models_cache.json` and falls back to a static list if the fetch
  fails.
- **Reasoning controls match the model.** RadSim reads each OpenRouter model's
  supported effort levels and sends the selected value as
  `reasoning.effort`. Mandatory-reasoning models use only the effort levels
  their live catalogue metadata advertises.

If you already pay for Anthropic or OpenAI directly, those providers are first-
class — there's no degraded path. The provider layer is the same code shape;
OpenRouter is just the most flexible starting point.

## Install

RadSim installs with [pipx](https://pipx.pypa.io), which puts it in its own
isolated environment. You never create or activate a virtualenv, and it avoids
the `externally-managed-environment` error (PEP 668) that modern macOS and Linux
raise when you `pip install` into the system Python.

Pick your platform, copy-paste the block, then **restart your terminal** so the
updated `PATH` takes effect and run `radsim`.

### Quick install (macOS & Linux, one line)

Auto-detects your distro, sets up pipx, and installs RadSim:

```bash
curl -fsSL https://raw.githubusercontent.com/MBemera/Radsim/main/install.sh | bash
```

Prefer to do it by hand? Use the per-platform blocks below.

### macOS

```bash
# With Homebrew (recommended)
brew install pipx
pipx ensurepath
pipx install radsimcli
```

No Homebrew? Install pipx with pip instead:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
python3 -m pipx install radsimcli
```

### Ubuntu / Debian / Kubuntu / Mint / Pop!_OS

```bash
# Ubuntu 22.04+ or Debian 12+
sudo apt update
sudo apt install pipx
pipx ensurepath
pipx install radsimcli
```

Older releases (Ubuntu 20.04, Debian 11) have no `pipx` package — use pip:

```bash
sudo apt update && sudo apt install python3-pip
python3 -m pip install --user pipx
python3 -m pipx ensurepath
python3 -m pipx install radsimcli
```

### Fedora / RHEL / Rocky / Alma

```bash
# Fedora, and RHEL / Rocky / Alma 9+
sudo dnf install pipx
pipx ensurepath
pipx install radsimcli
```

On RHEL / Rocky / Alma 8 (no `pipx` package), use pip:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
python3 -m pipx install radsimcli
```

### Arch / Manjaro

```bash
sudo pacman -S python-pipx
pipx ensurepath
pipx install radsimcli
```

### openSUSE

```bash
sudo zypper install python3-pipx
pipx ensurepath
pipx install radsimcli
```

### Alpine

```bash
sudo apk add pipx
pipx ensurepath
pipx install radsimcli
```

### Windows (PowerShell)

Needs Python 3.10+ (install from python.org with "Add Python to PATH", or use
the `py` launcher as shown):

```powershell
py -3 -m pip install --user pipx
py -3 -m pipx ensurepath
py -3 -m pipx install radsimcli
```

Or let the bundled installer set it up for you:

```powershell
.\install.ps1
```

Notes: `py -3 -m radsim` runs RadSim even before `PATH` is refreshed. Config and
credentials live under `%USERPROFILE%\.radsim`. Scheduled jobs use Windows Task
Scheduler; `winget`, Chocolatey, and Scoop are auto-detected for optional tool
installs, but none is required.

### Verify

Restart your terminal first, then:

```bash
radsim --version
```

### From source

For reading the code or sending PRs:

```bash
git clone https://github.com/MBemera/Radsim.git
cd Radsim
pipx install -e ".[dev]"     # or: python3 -m pip install -e ".[dev]"
```

On Windows PowerShell:

```powershell
git clone https://github.com/MBemera/Radsim.git
Set-Location .\Radsim
py -3 -m pip install -e ".[dev]"
py -3 -m pytest -q
```

### Plain pip (alternative)

If your Python isn't externally managed (older distros, an activated venv, or
Windows), you can skip pipx entirely:

```bash
python3 -m pip install --user radsimcli
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
| `/evolve` | Inspect or control learning, proposals, and reviewed extensions. |
| `/skill` | Manage your custom-instruction skill files. |
| `/teach` | Toggle teach mode (annotated diffs, slower pace). |
| `/plan`, `/panning` | Plan-then-execute and brain-dump processing workflows. |
| `/subagent` | Choose the sub-agent model and manage capability profiles. |
| `/background`, `/job` | Start sub-agent jobs and scheduled jobs. |
| `/mcp`, `/telegram` | Connect to MCP servers; configure Telegram remote control. |
| `/complexity`, `/stress`, `/archaeology` | Score complexity, run adversarial review, find dead code. |
| `/exit`, `/kill` | Quit normally; emergency-stop the loop. |

## Tools, explained simply

The model gets 72 tools by default, grouped by what they let it do:

- **Look at your code.** `read_file`, `list_directory`, `glob_files`,
  `grep_search`, `repo_map`, plus symbol-level helpers like `find_definition`
  and `find_references`. None of these mutate anything; they don't ask for
  confirmation.

- **Change your code.** `write_file`, `replace_in_file`, `multi_edit`,
  `apply_patch`. Each one shows you a diff before running.

- **Run things.** `run_shell_command`, `run_tests`, `lint_code`, `format_code`,
  `type_check`. In auto mode (`--yes`), a local request classifier approves
  recognised project inspection and verification commands. Destructive and
  unclassified shell/test requests are refused without an approval pause;
  RadSim can continue independent work. Manual mode keeps shell confirmation.

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
  for in-session tracking and farming work out to a sub-agent. Sub-agents run
  under locked capability profiles on a model you choose separately — see
  [Sub-agents](#sub-agents) below.

- **Heavier operations.** `run_docker`, `database_query`, `generate_tests`,
  `refactor_code`, `deploy`. All confirm.

- **Add reviewed extensions.** `/evolve extensions on` enables the extension
  capability after a typed warning. Approved extensions can register tools,
  slash commands, and observe-only hooks through RadSim's existing registries.
  Generated Python and extension activation always require explicit approval.

The extension capability and proposal engine are both off by default. See
[Evolve and extensions](docs/EVOLVE_AND_EXTENSIONS.md) for the manifest,
trust, reload, rollback, and API contracts.

MCP support is opt-in:

```bash
python3 -m pip install "radsimcli[mcp]"
```

## Sub-agents

RadSim can farm bounded work out to a sub-agent. Three things decide what a
sub-agent can do, and they are kept deliberately separate.

**The model is yours to choose.** Sub-agents run on their own saved provider
and model, picked with `/subagent model` and stored in
`~/.radsim/agent_config.json`. It is independent of your main model: `/switch`,
`/free`, `/clear`, and restarting all leave it alone, and the agent cannot
change it — `delegate_task` has no model argument at all. Until you pick one,
the first delegation stops and asks. Nothing silently falls back to a cheaper
model.

**The profile decides permissions, not the model.** Each sub-agent runs under
one locked capability profile:

| Profile | Can do | Background |
| --- | --- | --- |
| `explore` | Read and search the project | yes |
| `review` | `explore` plus static analysis | yes |
| `research` | Fetch web pages — no project file reads | yes, after you approve outbound access |
| `verify` | Run tests, lint, and type checks | no |
| `implement` | Read plus edit project files through the file tools | no |

No profile combines arbitrary project reads with outbound network access —
that pairing is the exfiltration path, so `research` trades file access away
for the network. No profile gets a shell, deletes, git writes, dependency
changes, deploys, memory writes, or `delegate_task`, so a sub-agent cannot
spawn another sub-agent. An unknown profile name is an error, never a
permissive default.

**Every tool call is brokered.** Sub-agent tool calls do not reach the tool
registry directly. They pass through a policy broker that re-checks the
profile allowlist, your `/settings` tool switches, path validation, and
protected-credential rules, and refuses anything it cannot positively approve.
Foreground calls additionally run through the same confirmation and hook path
as the main agent. Background jobs cannot change files or run project code at
all, and cancelling one stops the work rather than just relabelling it.

**Custom profiles add instructions, never permissions.** `/subagent create`
saves an instruction profile on top of one locked base profile, in
`~/.radsim/subagents.json`. Instructions refine how the sub-agent works; they
cannot add tools, change the model, widen paths, or bypass a confirmation.

Sub-agent output comes back labelled as untrusted evidence. It is bounded,
terminal-escaped, and never presented to the main agent as a system message —
verify a claim before relying on it.

## Safety

RadSim's safety model is simple: **anything that touches your machine confirms
unless you've trained the trust system to allow it.**

Confirmations cover file writes and deletes, shell commands, git mutations,
dependency changes, code formatting, database queries, deploys, memory writes,
scheduled jobs, custom-tool registration, and outbound Telegram messages.

A few hard rules don't bend even with `--yes`:

- Auto mode refuses destructive and privileged shell commands and file deletion,
  even when session-wide approval or disabled confirmations are configured.
  Direct Git tools also refuse commit amendment, file restoration that discards
  edits, and stash push/pop/drop in auto mode. Automatic staging requires explicit
  files and a repository `working_dir`; whole directories and nested repository
  pointers are refused. Automatic commits check the staged paths first.
  Manual mode uses the existing confirmation settings. Configured command
  restrictions and catastrophic-command blocks still apply in either mode.
- API keys live in `~/.radsim/.env` with `chmod 600`.
- The agent cannot **write** to `.env`, credentials files, or known private-key
  paths. It can read them when you ask.
- Anything you include in a prompt gets sent to the provider you chose. That's
  how the model works; pick a provider whose data policy matches your context.

### Auto-mode request classifier

Start with `radsim --yes` (or `radsim -y`). No extra model, API key, or dependency
is needed. Routine commands such as `git status --short`, `git diff --stat`,
`python -m pytest tests -q`, `ruff check .`, and `ruff format --check .` run
without repeated approval. Explicit project-file reads such as `cat README.md`
and `rg -n pattern src/main.py` are also recognised. Shell `git diff` commands
are automatic only for summaries (`--stat`, `--name-only`, or `--name-status`);
content diffs and `--check` are refused in auto mode because they can print
protected file contents. Scoped metadata commands such as `git -C nested status --short`,
`git -C nested rev-parse --show-toplevel`, and `git show --raw HEAD` are supported.
Git revision/path operands such as
`HEAD:credentials.json` are also refused.

The classifier checks every chained command, supported options, the working
directory, and literal file targets. Unknown executables, custom wrappers,
output redirection, wildcard paths (including bracket globs), recursive content
searches, secret files, and paths outside the project are refused in auto mode.
Windows shell requests are refused in auto mode because the classifier currently
supports POSIX shell syntax only. Session `all` and disabled confirmation settings
do not override auto-mode classification; they retain their manual-mode behavior.

Options after `--` are treated as filenames: `ruff format -- --check file.py`
is refused in auto mode. File reads resolve the complete filename, including
literal `::` characters; only pytest targets interpret `::` as a test node ID.
Custom and auto-detected test commands classify the appended test path as part of
the command. Recognised test runners include pytest, npm test, Jest, Vitest run,
Mocha, Go test, and Cargo test, with a limited set of supported options.

Pipes can consume the output of earlier checked commands, for example
`cat README.md | head -n 10 | wc -l`. Every stage must pass; `&&`, `||`, and `;`
start a new command without granting pipeline input. Nested shells and command
substitution remain blocked. A refusal returns a tool result, not a user
cancellation: RadSim can choose a supported non-destructive alternative or
continue independent work without an approval prompt. It must not retry a blocked
operation through a different tool or wrapper. Three permission refusals stop the
turn, even when interspersed with successful reads. Earlier successful operations
are not rolled back. Other tool-specific approval rules
(for example, installations or explicit protected reads) are unchanged.

Classification alone cannot see past the command string. An approved
`pytest -q` still executes whatever the tests contain, and a fixture calling
`shutil.rmtree` never produces a command for any rule to match. On macOS, auto
mode therefore runs shell, test and native Git commands inside the seatbelt sandbox
(`sandbox-exec`), which confines filesystem **writes** to the working directory,
the temp directory, and known build caches (`~/Library/Caches`, `~/.cache`,
`~/.npm`, `~/.cargo`, `~/.rustup`, `~/.gradle`, `~/.m2`, `~/go/pkg/mod`). Reads,
network access and process execution are unrestricted, so verification commands
behave normally.

The sandbox is on by default in auto mode and can be switched off in `/settings`
under "Sandbox shell commands in auto mode (macOS)". The setting is read from
your configuration, never from tool input, so no tool call can request an
unconfined command. Manual mode is unaffected: you approve each command there
yourself. Docker and deploy helpers remain outside this sandbox. Native file
tools cannot write your `~/.radsim` settings, and the sandbox denies writes there
even if the workspace is your home directory.
When sandboxing is requested but unavailable, commands are refused; they do not
silently run unconfined. This includes non-macOS platforms with the setting on.

Auto mode still trusts project verification code. The sandbox stops writes
outside the project; it does not stop a test from reading files, making network
calls, or corrupting the project itself. Use it in projects you trust.
Classification decisions are logged with a reason, without recording command
arguments or file contents.

You can disable the GitHub release check at startup with `--skip-update-check`.

## Configuration files

Everything user-level lives under `~/.radsim`:

| Path | Purpose |
| --- | --- |
| `~/.radsim/.env` | Provider, model, and API keys. |
| `~/.radsim/settings.json` | Reasoning effort, rate limits, UI preferences. |
| `~/.radsim/agent_config.json` | Tool switches, security level, sub-agent model. |
| `~/.radsim/subagents.json` | Custom sub-agent instruction profiles. |
| `~/.radsim/memory/` | Persistent memory store. |
| `~/.radsim/learning/` | Bounded canonical learning events and migration log. |
| `~/.radsim/extensions/` | Explicitly approved global extensions. |
| `~/.radsim/extension_storage/` | Bounded storage namespaced by extension ID. |
| `~/.radsim/jobs.json` | Scheduled jobs. |
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
| `radsim/learning/` | Canonical events, store, retrieval, preferences, and proposals. |
| `radsim/extension_api.py` | Stable adapter over the live registries. |
| `radsim/extension_loader.py` | Manifest validation, trust, reload, unload, and rollback. |
| `radsim/prompts.py`, `prompt_fragments/` | Composed system prompt and its checked-in fragments. |
| `radsim/sub_agent.py` | Sub-agent runner (the only one). |
| `radsim/sub_agent_policy.py` | Broker every sub-agent tool call passes through. |
| `radsim/sub_agent_profiles.py` | Locked capability profiles and custom instruction profiles. |
| `radsim/safety.py` | Path checks, core-policy boundary, confirmation prompts. |
| `radsim/memory.py` | Persistent memory plus secret sanitization. |
| `radsim/mcp_client.py` | Optional MCP integration. |
| `radsim/telegram.py` | Telegram bridge. |
| `radsim/jobs.py` | Scheduled jobs. |
| `radsim/scheduler.py` | `schedule_task` / `list_schedules` tools over `jobs.py`. |
| `tests/` | Pytest suite. |

## Development

```bash
python3 -m pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT. See [LICENSE](LICENSE).

### OpenRouter spend

`/usage` shows session tokens and provider-reported cost. Missing cost stays
unknown; partial coverage is labelled. The OpenRouter status bar uses these
reported costs instead of repricing the session at the currently selected model.
`/usage browser` opens https://openrouter.ai/activity in your default browser for
account-wide spend. It passes no API key or session content to the browser; use
your normal browser sign-in. This command is available locally, not via Telegram.
