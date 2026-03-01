# RadSim Quick Start Guide

Get started with RadSim in 2 minutes.

---

## What is RadSim?

**RadSim** = Radical Simplicity = A CLI coding agent that writes, edits, and manages code using AI.

It also follows a coding philosophy: code so simple that anyone (human or AI) can understand it instantly.

---

## Install & Run

```bash
# Install
git clone https://github.com/MBemera/Radsim.git
cd radsim
pip install ".[all]"

# Run (first launch starts the setup wizard)
radsim
```

The wizard walks you through:
1. Answer a few personalization questions
2. Choose a provider (default: OpenRouter)
3. Pick a model
4. Enter your API key (saved securely)

---

## Usage

### Single-Shot

```bash
radsim "Create a Python function to validate emails"
radsim "Find all TODO comments in the codebase"
radsim "Run the tests"
```

### Interactive

```bash
radsim

> Build a REST API in Python with Flask
[Agent creates files]

> Add authentication
[Agent modifies files]

> /switch
[Switch provider/model mid-session]

> exit
```

---

## Supported Providers

| # | Provider | Best For | Pricing |
|---|----------|----------|---------|
| 1 | **Claude** (Anthropic) | Coding, reasoning | $0.80-15/M tokens |
| 2 | **GPT-5** (OpenAI) | Versatile, multimodal | $1-15/M tokens |
| 3 | **Gemini** (Google) | Huge context, docs | $0.075-5/M tokens |
| 4 | **Vertex AI** (Google Cloud) | GCP-hosted Gemini + Claude | $0.075-15/M tokens |
| 5 | **OpenRouter** | Recommended (cheapest, most models) | $0.14-0.50/M tokens |

Switch anytime with `/switch` or `/free`.

---

## Key Commands

```
/help       Show help menu
/switch     Change provider/model
/free       Switch to cheapest model
/teach      Toggle Teach Me mode (explains code as it works)
/clear      Clear conversation
/new        Fresh conversation + reset limits
/settings   View/change agent settings
/exit       Exit RadSim
```

---

## Configuration

Add your API key to `~/.radsim/.env`:

```bash
# For Claude
RADSIM_PROVIDER="claude"
ANTHROPIC_API_KEY="sk-ant-..."

# For OpenAI
RADSIM_PROVIDER="openai"
OPENAI_API_KEY="sk-..."

# For Gemini
RADSIM_PROVIDER="gemini"
GOOGLE_API_KEY="AIza..."

# For Vertex AI (uses GCP credentials, not an API key)
RADSIM_PROVIDER="vertex"
GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
GOOGLE_CLOUD_LOCATION="us-central1"
# Also run: gcloud auth application-default login

# For OpenRouter
RADSIM_PROVIDER="openrouter"
OPENROUTER_API_KEY="sk-or-..."
```

---

## The RadSim Philosophy

Use `/radsim` in Claude Code to apply these principles:

### The One Rule

> "If a junior developer can't understand your code in 30 seconds, it's too complex."

### 6 Core Rules

1. **Clarity over cleverness** — No magic, no tricks
2. **Self-documenting names** — `calculate_user_age()` not `calc()`
3. **One function, one purpose** — Do ONE thing, max 20-30 lines
4. **Flat over nested** — Use early returns, max 2-3 levels
5. **Explicit over implicit** — No side effects
6. **Standard patterns** — async/await, REST conventions

### Example

```python
# BAD
def p(d): return sum([x['a'] if x['t']=='s' else -x['a'] for x in d])

# GOOD
def calculate_total_profit(transactions):
    total_profit = 0
    for transaction in transactions:
        if transaction['type'] == 'sale':
            total_profit += transaction['amount']
        else:
            total_profit -= transaction['amount']
    return total_profit
```

---

## The Checklist

Before committing code, ask:

- [ ] Can a junior dev understand this in 30 seconds?
- [ ] Can an AI agent modify this safely?
- [ ] Are all names self-explanatory?
- [ ] Is there only ONE way to interpret this?
- [ ] Can I test this easily?
- [ ] Will this scale without a rewrite?

If any answer is "no", **simplify more**.

---

## Full Documentation

- **Complete Guide:** [README.md](README.md)
- **Full Philosophy:** [RADSIM_DOCUMENTATION.md](RADSIM_DOCUMENTATION.md)
- **Integration Setup:** [RADSIM_INTEGRATION_SETUP.md](RADSIM_INTEGRATION_SETUP.md)
- **Env Template:** [.env.example](.env.example)

---

**RadSim - Because the best code is code anyone can understand.**
