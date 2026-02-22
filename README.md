# RadSim — Radically Simple Code Generator

<p align="center">
  <img src="docs/screenshots/screenshot-3-interactive.png" alt="RadSim interactive session" width="700">
</p>

<p align="center">
  <a href="https://pypi.org/project/radsim/"><img src="https://img.shields.io/pypi/v/radsim?color=blue&label=version" alt="PyPI version"></a>
  <a href="https://pypi.org/project/radsim/"><img src="https://img.shields.io/pypi/pyversions/radsim" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="https://github.com/MBemera/Radsim/releases"><img src="https://img.shields.io/badge/version-1.1.0-blue" alt="Version"></a>
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey" alt="Platforms">
</p>

<p align="center">
  <strong>Your own AI coding agent. Run it with your API key.<br>
  Write, edit, search, and ship code from the terminal.</strong>
</p>

---

## What is RadSim?

RadSim is a **standalone CLI coding agent** — like Claude Code or GitHub Copilot CLI — that runs locally using your own API key. Connect to any major AI provider and get a full-featured agent with file operations, search, shell execution, git tools, and more.

**Built on the Radical Simplicity philosophy:** Write code so simple that ANY agent, ANY editor, and ANY developer can understand it immediately.

### Key Features

| Feature | Description |
|---------|-------------|
| **5 AI providers** | Claude, OpenAI, Gemini, Vertex AI, OpenRouter |
| **20+ built-in tools** | File I/O, search, shell, git, web fetch, browser automation |
| **Interactive + single-shot** | Full REPL session or one-off commands |
| **Automatic failover** | Falls back to cheaper models if primary is unavailable |
| **Learning system** | Learns your coding style and preferences over time |
| **Teach mode** | Explains code as it writes it (`/teach`) |
| **Secure by default** | Sandboxed file access, confirmation prompts, chmod 600 keys |

---

## Installation

**Requirements:** Python 3.10+

### macOS / Linux

```bash
git clone https://github.com/MBemera/Radsim.git
cd radsim
./install.sh
```

<img src="docs/screenshots/screenshot-1-install.png" alt="Linux install" width="680">

### Windows (PowerShell)

```powershell
git clone https://github.com/MBemera/Radsim.git
cd radsim
.\install.ps1
```

<img src="docs/screenshots/screenshot-6-windows.png" alt="Windows install" width="680">

### Cross-Platform (Python installer — works on all OS)

```bash
python install.py
```

### With Optional Extras

```bash
# macOS / Linux
./install.sh --extras all

# Windows
.\install.ps1 -WithExtras all

# Python (all platforms)
python install.py --extras all
```

| Extra | What it adds |
|-------|-------------|
| `openai` | OpenAI GPT models |
| `gemini` | Google Gemini + Vertex AI |
| `browser` | Browser automation (Playwright) |
| `memory` | Vector memory (ChromaDB) |
| `all` | Everything above |

### Verify Installation

```bash
radsim --version
# RadSim 1.1.0
```

### Uninstall

```bash
./uninstall.sh        # macOS / Linux
pip uninstall radsim  # All platforms
```

---

## Quick Start

### First Run — Setup Wizard

On first launch, RadSim walks you through setup:

```bash
radsim
```

<img src="docs/screenshots/screenshot-2-setup.png" alt="RadSim setup wizard" width="680">

1. Choose a provider (Claude, OpenAI, Gemini, Vertex AI, or OpenRouter)
2. Pick a model
3. Enter your API key — saved securely to `~/.radsim/.env` (chmod 600)
4. Start coding

Re-run setup anytime: `radsim --setup`

---

### Single-Shot Mode

Run one task and exit:

```bash
radsim "Create a Python function to validate email addresses"
radsim "Find all TODO comments in the codebase"
radsim "Run the test suite and fix any failures"
radsim --yes "Refactor src/utils.js"   # auto-confirm writes
```

<img src="docs/screenshots/screenshot-4-singleshot.png" alt="Single-shot mode" width="680">

---

### Interactive Mode

Full REPL session:

```bash
radsim
```

<img src="docs/screenshots/screenshot-3-interactive.png" alt="Interactive mode" width="680">

```
RadSim > Build a REST API with Flask
[Agent creates files, asks for confirmation]

RadSim > Add JWT authentication
[Agent modifies existing files]

RadSim > Run pytest
[Agent executes tests]

RadSim > /switch
[Switch provider or model mid-session]

RadSim > exit
```

---

## Supported Providers & Models

RadSim supports **5 providers** with automatic failover.

### Claude (Anthropic)

| Model | Description | Input / Output |
|-------|-------------|---------------|
| `claude-opus-4-6` | Most capable, extended thinking | $15 / $75 per 1M tokens |
| `claude-sonnet-4-5` | **Recommended** — great balance | $3 / $15 per 1M tokens |
| `claude-haiku-4-5` | Fast & cheap | $0.80 / $4 per 1M tokens |

Get your API key: [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)

### OpenAI

| Model | Description | Input / Output |
|-------|-------------|---------------|
| `gpt-5.2` | **Recommended** — latest flagship | $5 / $15 per 1M tokens |
| `gpt-5.2-codex` | Agentic coding specialist | $5 / $15 per 1M tokens |
| `gpt-5-mini` | Fast & cheap | $1 / $4 per 1M tokens |

Get your API key: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

### Gemini (Google)

| Model | Description | Input / Output |
|-------|-------------|---------------|
| `gemini-3-pro` | Most capable | $1.25 / $5 per 1M tokens |
| `gemini-3-flash` | **Recommended** — fast & cheap | $0.10 / $0.40 per 1M tokens |
| `gemini-2.5-pro` | Large context (2M tokens) | $1.25 / $5 per 1M tokens |

Get your API key: [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### Vertex AI (Google Cloud)

Uses GCP Application Default Credentials — no API key needed.

```bash
gcloud auth application-default login

# Add to ~/.radsim/.env:
GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
```

Console: [console.cloud.google.com/vertex-ai](https://console.cloud.google.com/vertex-ai)

### OpenRouter

| Model | Description | Input / Output |
|-------|-------------|---------------|
| `moonshotai/kimi-k2.5` | **Recommended** — capable & cheap | $0.14 / $0.28 per 1M tokens |
| `minimax/minimax-m2.1` | Fast responses | $0.20 / $0.55 per 1M tokens |

Get your API key: [openrouter.ai/keys](https://openrouter.ai/keys)

---

## Configuration

RadSim reads from `.env` files in priority order:

1. Local `.env` in current directory (project-specific)
2. Global `~/.radsim/.env` (user-wide)
3. System environment variables

```bash
# Copy the template and fill in your key
cp .env.example ~/.radsim/.env
chmod 600 ~/.radsim/.env
```

### Key Variables

```bash
RADSIM_PROVIDER="claude"              # claude, openai, gemini, vertex, openrouter
RADSIM_MODEL="claude-sonnet-4-5"

ANTHROPIC_API_KEY="sk-ant-..."        # Claude
OPENAI_API_KEY="sk-..."              # OpenAI
GOOGLE_API_KEY="AIza..."             # Gemini
OPENROUTER_API_KEY="sk-or-..."       # OpenRouter
GOOGLE_CLOUD_PROJECT="my-project"    # Vertex AI
```

Full template: [.env.example](.env.example)

---

## Commands Reference

<img src="docs/screenshots/screenshot-5-help.png" alt="RadSim /help command" width="680">

### Provider & Model

| Command | Description |
|---------|-------------|
| `/switch` | Quick switch provider and model |
| `/config` | Full configuration setup |
| `/free` | Switch to cheapest OpenRouter model |

### Conversation

| Command | Description |
|---------|-------------|
| `/clear` | Clear conversation history |
| `/new` | Fresh conversation + reset rate limits |

### Learning & Feedback

| Command | Description |
|---------|-------------|
| `/good` | Mark last response as good |
| `/improve` | Mark last response for improvement |
| `/stats` | Show learning statistics |
| `/report` | Export detailed learning report |
| `/preferences` | Show learned code style preferences |
| `/evolve` | Review self-improvement proposals |

### Customization

| Command | Description |
|---------|-------------|
| `/skill add <text>` | Add a custom coding instruction |
| `/skill list` | List active skills |
| `/teach` | Toggle Teach Me mode (explains code while writing) |
| `/settings` | View/change agent settings |

### Session

| Command | Description |
|---------|-------------|
| `/exit` | Exit RadSim |
| `/kill` | EMERGENCY: Immediately terminate the agent |
| `/setup` | Re-run the setup wizard |
| `/help` | Show full help menu |

---

## Available Tools

RadSim includes 20+ tools matching Claude Code and GitHub Copilot CLI.

### File Operations

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents (supports offset/limit for large files) |
| `read_many_files` | Read up to 20 files at once |
| `write_file` | Create or overwrite files (with confirmation) |
| `replace_in_file` | Edit specific text within files |
| `delete_file` | Delete files (requires confirmation) |

### Search

| Tool | Description |
|------|-------------|
| `glob_files` | Find files by pattern (`**/*.py`, `src/**/*.ts`) |
| `grep_search` | Search file contents with regex |
| `find_definition` | Find where a symbol is defined |
| `find_references` | Find all references to a symbol |

### Shell & Git

| Tool | Description |
|------|-------------|
| `run_shell_command` | Execute bash/PowerShell commands |
| `git_status` | Repository status |
| `git_diff` | View staged/unstaged changes |
| `git_log` | Commit history |

### Web & Browser

| Tool | Description |
|------|-------------|
| `web_fetch` | Fetch and parse content from URLs |
| `browser_open` | Open a URL in headless browser (Playwright) |
| `browser_screenshot` | Take screenshots |

---

## Architecture

```
radsim/
├── agent.py             # Agent loop — conversation and tool orchestration
├── api_client.py        # Multi-provider API clients (Claude, OpenAI, Gemini, Vertex, OpenRouter)
├── config.py            # Configuration, model lists, pricing
├── commands.py          # Slash command registry
├── onboarding.py        # First-time setup wizard
├── model_router.py      # Cost-aware routing with automatic failover
├── tools/               # Sandboxed tool implementations
├── skills/              # Just-in-time skill documentation
├── learning/            # Preference learning and self-improvement
├── hooks.py             # Event hook system (pre/post tool, on error)
├── task_logger.py       # SQLite audit logging
└── modes.py             # Mode system (teach mode, etc.)
```

---

## Safety & Security

- **Sandboxed**: Cannot access files outside the project directory
- **Confirmation required**: All write, edit, delete, and shell operations ask first
- **Keys secured**: Stored in `~/.radsim/.env` with chmod 600 (owner read/write only)
- **Never logged**: API keys never appear in logs or error messages
- **Emergency stop**: `Ctrl+C` twice or `/kill` to immediately terminate

---

## RadSim Coding Philosophy

> **"Write code so simple that ANY agent, ANY editor, and ANY developer can understand it immediately."**

### The 6 Core Principles

1. **Extreme Clarity Over Cleverness** — No magic tricks, just obvious code
2. **Self-Documenting Names** — `calculate_user_age()` not `calc()`
3. **One Function, One Purpose** — Each function does ONE thing (max 20-30 lines)
4. **Flat Over Nested** — Use early returns, max 2-3 nesting levels
5. **Explicit Over Implicit** — No hidden side effects or global state
6. **Standard Patterns Only** — AI-recognizable patterns, language built-ins

```python
# BAD — what does this even do?
def p(d): return sum([x['a'] if x['t']=='s' else -x['a'] for x in d])

# GOOD — RadSim style
def calculate_total_profit(transactions):
    total_profit = 0
    for transaction in transactions:
        if transaction['type'] == 'sale':
            total_profit += transaction['amount']
        else:
            total_profit -= transaction['amount']
    return total_profit
```

Use `/radsim` in Claude Code to apply these principles to any code.

Full philosophy: [RADSIM_DOCUMENTATION.md](RADSIM_DOCUMENTATION.md)

---

## Project Files

| File | Description |
|------|-------------|
| [README.md](README.md) | This file |
| [RADSIM_QUICK_START.md](RADSIM_QUICK_START.md) | 2-minute quick start |
| [RADSIM_DOCUMENTATION.md](RADSIM_DOCUMENTATION.md) | Complete RadSim philosophy (14 rules) |
| [RADSIM_QUICK_START.md](RADSIM_QUICK_START.md) | 2-minute quick start |
| [.env.example](.env.example) | Environment variable template |
| [install.sh](install.sh) | macOS / Linux installer |
| [install.ps1](install.ps1) | Windows PowerShell installer |
| [install.py](install.py) | Cross-platform Python installer |

---

## Changelog

### v1.1.0 (2026-02-09)

- Universal Tool Bridge with standardized response format
- Dynamic Skill Registry for just-in-time context loading
- Event Hooks system (pre/post tool, pre/post API, on error)
- SQLite task logging and audit trail
- Cost-effective model routing with automatic failover
- Learning system with preference tracking
- Self-improvement proposals (`/evolve`)
- Teach Me mode (`/teach`)
- Custom skills (`/skill add`)
- Agent configuration system (`/settings`)
- **New provider: Vertex AI** — GCP-hosted Gemini and Claude models

### v1.0.0 (2026-01-31)

- Initial release with 4 providers: Claude, OpenAI, Gemini, OpenRouter
- 20+ built-in tools
- Interactive and single-shot modes
- Onboarding wizard

---

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Follow RadSim coding principles
4. Run tests: `pytest`
5. Submit a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## License

**MIT License** — Copyright (c) 2024-2026 Matthew Bright

Free to use, modify, and distribute. See [LICENSE](LICENSE), [DISCLAIMER.md](DISCLAIMER.md), and [NOTICE](NOTICE) for full terms.

---

<p align="center"><strong>RadSim — Because simplicity scales.</strong><br>
Maintained by <a href="https://github.com/emera-digital">EMERA DIGITAL TOOLS</a></p>
