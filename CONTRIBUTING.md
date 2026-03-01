# Contributing to RadSim

Thank you for your interest in contributing. RadSim has a high quality bar — every PR is reviewed against the standards below. Please read this entire document before submitting.

---

## Before You Start

**Check first.** Open an issue or discussion before writing code for:
- New features or tools
- Architectural changes
- Anything touching `agent.py`, `api_client.py`, `safety.py`, or `prompts.py`

Small bug fixes and typo corrections don't need prior discussion.

---

## Development Setup

```bash
git clone https://github.com/MBemera/Radsim.git
cd radsim
pip install -e ".[dev]"
```

Verify everything works:

```bash
pytest                    # All 879+ tests must pass
ruff check radsim/        # Zero lint errors
radsim --version          # Confirms install
```

---

## Code Standards

RadSim follows **Radical Simplicity**. Code that doesn't meet these standards will be rejected.

### Hard Requirements (PR will be closed if violated)

- **All tests pass.** Run `pytest` before submitting. PRs with failing tests are auto-rejected.
- **Zero lint errors.** Run `ruff check radsim/` before submitting.
- **No hardcoded secrets.** No API keys, tokens, or credentials in source code. Ever. Use `os.getenv()`.
- **No new dependencies without discussion.** If your change adds a package to `pyproject.toml`, open an issue first to discuss why it's necessary. RadSim has only 2 hard dependencies (`anthropic`, `rich`) — keep it lean.
- **No breaking changes to the tool interface.** Tools are the contract between RadSim and AI providers. Changing tool names, removing parameters, or altering response formats breaks every model's ability to use RadSim.

### Code Style (PR will be sent back for revision)

| Rule | What It Means |
|------|--------------|
| **One function, one purpose** | Max 20-30 lines per function. If it has "and" in the name, split it. |
| **Self-documenting names** | `calculate_user_age()` not `calc()`. No abbreviations unless universal (http, api, url). |
| **Flat over nested** | Max 2-3 nesting levels. Use early returns. |
| **Explicit over implicit** | No hidden side effects, no global state mutations, pass dependencies explicitly. |
| **Standard patterns only** | No custom frameworks, no clever one-liners, no magic. Use language built-ins. |
| **No unnecessary additions** | Don't add docstrings, comments, type annotations, or refactoring to code you didn't change. |

```python
# This will be rejected:
def p(d): return sum([x['a'] if x['t']=='s' else -x['a'] for x in d])

# This will be accepted:
def calculate_total_profit(transactions):
    total_profit = 0
    for transaction in transactions:
        if transaction['type'] == 'sale':
            total_profit += transaction['amount']
        else:
            total_profit -= transaction['amount']
    return total_profit
```

### File Organization

- Source goes in `radsim/`
- Tests go in `tests/` and mirror the source structure (`radsim/foo.py` → `tests/test_foo.py`)
- New tools go in `radsim/tools/` with a matching definition in `radsim/tools/definitions.py`
- Skill docs go in `radsim/skills/`

---

## Testing Requirements

Every PR must include tests for new functionality. No exceptions.

```bash
# Run full suite
pytest

# Run specific test file
pytest tests/test_your_feature.py -v

# Run with coverage (optional but appreciated)
pytest --tb=short
```

### What to test

- **New functions**: Unit tests covering normal input, edge cases, and error cases
- **New tools**: Test tool execution, input validation, and response format
- **Bug fixes**: Add a regression test that fails without your fix
- **Modified behavior**: Update existing tests to match the new behavior

### What NOT to test

- Don't test third-party libraries (they have their own tests)
- Don't test private helper functions unless they have complex logic
- Don't write tests that depend on network access or real API keys

---

## Pull Request Process

### 1. Branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b feature/your-feature-name
```

Use descriptive branch names: `feature/`, `fix/`, `docs/`.

### 2. Make your changes

- Keep PRs focused — one feature or fix per PR
- Small PRs get reviewed faster. If your change is large, split it into multiple PRs.

### 3. Self-review checklist

Before submitting, verify ALL of the following:

- [ ] `pytest` — all tests pass
- [ ] `ruff check radsim/` — zero lint errors
- [ ] New functionality has tests
- [ ] No hardcoded secrets, API keys, or tokens
- [ ] No new dependencies added without prior discussion
- [ ] Code follows Radical Simplicity principles (readable, obvious, no magic)
- [ ] Commit messages are clear and describe the "why" not the "what"
- [ ] PR targets the `main` branch

### 4. Submit with a clear description

Your PR description must include:
- **What** changed (1-2 sentences)
- **Why** it changed (the problem or motivation)
- **How to test** (steps a reviewer can follow to verify)

### 5. Review process

- A maintainer will review your PR against the standards above
- Expect revision requests — this is normal and not personal
- PRs that don't meet standards will be sent back, not merged with fixes
- Abandoned PRs (no response for 14 days) will be closed

---

## Common Rejection Reasons

These are the most frequent reasons PRs get sent back or closed:

| Reason | Fix |
|--------|-----|
| Tests not included | Add tests before resubmitting |
| Tests failing | Run `pytest` locally first |
| Lint errors | Run `ruff check radsim/` and fix |
| Over-engineered | Simplify — do the minimum needed |
| Unrelated changes mixed in | Split into separate PRs |
| Modified files you didn't need to | Revert unrelated changes |
| Added comments/docstrings to existing code | Only modify code relevant to your change |
| No description on PR | Explain what, why, and how to test |
| Breaks existing tool interface | Tools are a stable contract — don't change signatures |

---

## Reporting Issues

Use the GitHub issue templates:

- **[Bug report](../../issues/new?template=bug_report.md)** — Something is broken
- **[Feature request](../../issues/new?template=feature_request.md)** — Something you want added

For bugs, always include: OS, Python version, RadSim version (`radsim --version`), provider, and the full error output.

---

## Security Vulnerabilities

**Do NOT open a public issue for security vulnerabilities.**

Email security concerns directly to the maintainer. Include:
- Description of the vulnerability
- Steps to reproduce
- Impact assessment

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
