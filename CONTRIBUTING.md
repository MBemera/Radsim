# Contributing to RadSim

Thank you for your interest in contributing to RadSim.

## Getting Started

```bash
git clone https://github.com/emera-digital/radsim.git
cd radsim
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest
```

## Code Style

RadSim follows the **Radical Simplicity** philosophy. Before submitting:

- [ ] Every function does ONE thing (max 20-30 lines)
- [ ] Variable and function names are self-explanatory — no abbreviations
- [ ] No nesting deeper than 2-3 levels — use early returns
- [ ] No hidden side effects or global state mutations
- [ ] Standard patterns only — no clever tricks

Run the linter before committing:

```bash
ruff check radsim/
```

## Pull Request Process

1. Fork the repo and create a feature branch
2. Write tests for any new functionality
3. Run `pytest` — all tests must pass
4. Submit a PR with a clear description of what changed and why

## Reporting Issues

Use the GitHub issue templates:
- **Bug report** — Something is broken
- **Feature request** — Something you want added

Please include your OS, Python version, and provider when reporting bugs.
