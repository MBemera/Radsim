# RadSim (Radical Simplicity) - Complete Documentation

**Version:** 1.1
**Created:** 2026-01-31 | **Updated:** 2026-02-15
**Purpose:** Universal coding philosophy for maximum readability, AI-agent compatibility, and scalability

---

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Core Philosophy](#core-philosophy)
4. [The 14 Universal Rules](#the-14-universal-rules)
5. [Usage with Claude Code](#usage-with-claude-code)
6. [System Prompts](#system-prompts)
7. [Examples](#examples)
8. [Integration Guide](#integration-guide)

---

## Overview

**RadSim** (Radical Simplicity) is a coding philosophy that prioritizes:

- **Human Readability**: Code that any developer can understand immediately
- **AI Agent Comprehension**: Optimized for Claude, GPT, Copilot, and other AI tools
- **Cross-Editor Compatibility**: Works seamlessly in VS Code, Vim, Cursor, Neovim, etc.
- **Scalability Through Simplicity**: Code that scales without major rewrites

### Why RadSim?

Traditional code often optimizes for:
- Brevity (fewer lines)
- Cleverness (showing off skills)
- Performance (premature optimization)

RadSim optimizes for:
- **Clarity** (obvious intent)
- **Maintainability** (easy to change)
- **Collaboration** (humans + AI working together)

---

## Installation

### RadSim CLI Agent

RadSim is also a standalone CLI coding agent. See [README.md](README.md) for full installation and usage.

```bash
pip install .
radsim
```

The agent supports 5 providers: **Claude**, **OpenAI**, **Gemini**, **Vertex AI**, and **OpenRouter**.

### For Claude Code

1. The skill is already installed at:
   ```
   .claude/commands/radsim.md
   ```

2. Use it with the command:
   ```
   /radsim
   ```

3. Claude Code will automatically apply RadSim principles when invoked.

---

## Core Philosophy

### The Golden Rule

**"Write code so simple that ANY agent, ANY editor, and ANY developer can understand it immediately."**

### Three Pillars

1. **Clarity**: Code should be obvious, not clever
2. **Consistency**: Patterns should be predictable
3. **Scalability**: Simple code scales better than complex code

### The Simplicity Test

Ask yourself:
- Can a junior developer understand this in 30 seconds?
- Can an AI agent modify this without breaking it?
- Will I understand this 6 months from now without context?

If any answer is "no", simplify further.

---

## The 14 Universal Rules

### 1. Extreme Clarity Over Cleverness

❌ **Avoid:**
```python
result = [x for x in map(lambda y: y**2, filter(lambda z: z%2==0, range(10)))]
```

✅ **Prefer:**
```python
numbers = range(10)
even_numbers = [num for num in numbers if num % 2 == 0]
result = [num ** 2 for num in even_numbers]
```

### 2. Self-Documenting Code

❌ **Avoid:**
```python
def proc_usr(u, d):
    return u.get(d)
```

✅ **Prefer:**
```python
def get_user_by_id(user_id, database_connection):
    return database_connection.fetch_user(user_id)
```

### 3. One Function, One Purpose

❌ **Avoid:**
```python
def fetch_and_process_and_save_user_data(user_id):
    data = api.fetch(user_id)
    processed = transform(data)
    db.save(processed)
    send_email(user_id)
    return processed
```

✅ **Prefer:**
```python
def fetch_user_data(user_id):
    return api.fetch(user_id)

def process_user_data(raw_data):
    return transform(raw_data)

def save_user_data(processed_data):
    return db.save(processed_data)

def notify_user(user_id):
    return send_email(user_id)
```

### 4. Flat Over Nested

❌ **Avoid:**
```python
def process_order(order):
    if order:
        if order.is_valid():
            if order.has_items():
                if order.user.is_verified():
                    return order.process()
```

✅ **Prefer:**
```python
def process_order(order):
    if not order:
        return "No order"
    if not order.is_valid():
        return "Invalid order"
    if not order.has_items():
        return "No items"
    if not order.user.is_verified():
        return "User not verified"
    return order.process()
```

### 5. Explicit Over Implicit

❌ **Avoid:**
```javascript
let globalCounter = 0;
function incrementCounter() {
    globalCounter++;  // Hidden side effect
}
```

✅ **Prefer:**
```javascript
function incrementCounter(counter) {
    return counter + 1;  // Pure function
}
```

### 6. Standard Patterns Only

✅ **Use well-known patterns:**
- REST APIs: `GET /users/:id`, `POST /users`
- Async: `async/await` (not callbacks)
- Error handling: `try/catch`, `if/else` validation
- Database: Standard SQL or common ORM patterns

### 7. Consistent Structure Everywhere

```
project/
├── src/
│   ├── models/          # Data structures
│   ├── services/        # Business logic
│   ├── controllers/     # Request handlers
│   ├── utils/           # Helper functions
│   └── config/          # Configuration
├── tests/               # Mirror src/ structure
├── .env.example
├── .env
└── README.md
```

### 8-14. See [CLAUDE.md](../.claude/CLAUDE.md) for complete details

---

## Usage with Claude Code

### Invoke the Skill

```bash
# In Claude Code session
/radsim
```

### What Happens

1. Claude loads the RadSim philosophy
2. All code generation/review follows RadSim principles
3. Code is checked against the Simplicity Checklist

### Example Session

```
You: /radsim

Claude: RadSim mode activated. I'll apply Radical Simplicity principles.
        Send code to review or describe what you want to build.

You: Review this function:
     def calc(a,b,t): return a*b*(1+t)

Claude: This violates RadSim principles:
        - Cryptic variable names (a, b, t)
        - Unclear purpose
        - One-liner obscures logic

        Here's the RadSim version:

        def calculate_total_price_with_tax(price_per_item, quantity, tax_rate):
            subtotal = price_per_item * quantity
            total = subtotal * (1 + tax_rate)
            return total

        Improvements:
        ✅ Self-documenting function name
        ✅ Explicit variable names
        ✅ Each step is clear
        ✅ Easy to test and modify
```

---

## System Prompts

### Complete System Prompt

Copy this into any AI assistant or agent configuration to apply RadSim principles:

```
You are a coding assistant that follows Radical Simplicity (RadSim) principles. Your mission is to write and review code that is maximally readable, AI-agent friendly, and scalable.

CORE PRINCIPLES:

1. EXTREME CLARITY OVER CLEVERNESS
   - No clever one-liners or magic tricks
   - Use obvious, straightforward code
   - If it needs a comment to explain WHAT it does, it's too complex

2. SELF-DOCUMENTING NAMES
   - Variables and functions explain themselves completely
   - Function names: verb + noun (get_user_data, calculate_total)
   - No abbreviations unless universal (http, api, url, id)

3. ONE FUNCTION, ONE PURPOSE
   - Each function does ONE thing only
   - Max 20-30 lines per function
   - If name has "and", split into multiple functions

4. FLAT OVER NESTED
   - Max 2-3 nesting levels
   - Use early returns to reduce nesting
   - Extract nested logic into separate functions

5. EXPLICIT OVER IMPLICIT
   - Always explicit about what's happening
   - No hidden side effects or global state
   - Pass dependencies explicitly

6. STANDARD PATTERNS ONLY
   - Use well-known patterns AI agents recognize
   - Prefer language built-ins over custom libraries
   - async/await over callbacks

THE SIMPLICITY CHECKLIST:

Before accepting any code, verify:
☐ Can a junior developer understand this immediately?
☐ Can an AI agent read and modify this without confusion?
☐ Are all names self-explanatory?
☐ Is there only ONE way to interpret this code?
☐ Can this be tested easily?
☐ Can this scale without complete rewrite?

RESPONSE FORMAT:

When reviewing code:
1. Identify violations of radical simplicity
2. Rewrite using the principles above
3. Explain what changed and why it's better
4. Validate against the simplicity checklist

When writing code:
1. Start with the simplest solution
2. Use self-documenting names
3. Keep functions small and focused
4. Validate against the checklist

EXAMPLES:

BAD (Complex):
def proc_usr(u,d): return u.get(d) if u else None

GOOD (Simple):
def get_user_from_database(user_data, database_connection):
    if not user_data:
        return None
    return database_connection.get_user(user_data)

BAD (Nested):
if x:
    if y:
        if z:
            return result

GOOD (Flat):
if not x:
    return None
if not y:
    return None
if not z:
    return None
return result

Remember: Simple code is easier to read, test, debug, scale, and for AI agents to understand and modify. Complexity is the enemy of maintainability.

Always apply RadSim principles to every piece of code you generate or review.
```

### Short Version for Token Limits

If you have token/context limits, use this condensed version:

```
Apply Radical Simplicity (RadSim) to all code:

RULES:
1. Clarity over cleverness - no tricks, just obvious code
2. Self-documenting names - variables/functions explain themselves
3. One function, one purpose - max 20-30 lines
4. Flat over nested - early returns, max 2-3 levels
5. Explicit over implicit - no side effects
6. Standard patterns only - AI-recognizable patterns

CHECK:
☐ Can junior dev understand immediately?
☐ Can AI agent modify safely?
☐ Are names self-explanatory?
☐ One way to interpret?
☐ Easy to test?
☐ Scales without rewrite?

Always rewrite complex code to be radically simple.
```

---

## Examples

### Example 1: Function Simplification

**Before (Complex):**
```python
def p(d):
    return sum([x['amt'] if x['type']=='sale' else -x['amt'] for x in d])
```

**After (RadSim):**
```python
def calculate_total_profit(transactions):
    total_profit = 0

    for transaction in transactions:
        if transaction['type'] == 'sale':
            total_profit += transaction['amount']
        else:
            total_profit -= transaction['amount']

    return total_profit
```

**Improvements:**
- ✅ Clear function name explains purpose
- ✅ Explicit variable names
- ✅ Simple loop instead of complex comprehension
- ✅ Easy to debug and test
- ✅ AI agents can easily understand and modify

---

### Example 2: Database Query

**Before (Complex):**
```python
def q(u): return db.exec(f"SELECT * FROM usr WHERE id={u}") if u else []
```

**After (RadSim):**
```python
def get_user_by_id(user_id, database_connection):
    if not user_id:
        return None

    query = "SELECT * FROM users WHERE user_id = ?"
    result = database_connection.execute(query, [user_id])

    return result
```

**Improvements:**
- ✅ Self-documenting function name
- ✅ Parameterized query (SQL injection safe)
- ✅ Explicit early return
- ✅ Clear variable names
- ✅ Easy to test with mock database

---

### Example 3: API Endpoint

**Before (Complex):**
```javascript
app.post('/api/u',(req,res)=>db.find(req.body.id)?res.json(db.get(req.body.id)):res.status(404).send())
```

**After (RadSim):**
```javascript
app.post('/api/users', async (request, response) => {
    const user_id = request.body.id;

    if (!user_id) {
        return response.status(400).json({
            error: "User ID is required"
        });
    }

    const user_exists = await database.find(user_id);

    if (!user_exists) {
        return response.status(404).json({
            error: "User not found"
        });
    }

    const user_data = await database.get(user_id);

    return response.json(user_data);
});
```

**Improvements:**
- ✅ Clear endpoint path
- ✅ Explicit variable names
- ✅ Early returns with proper status codes
- ✅ Error messages for debugging
- ✅ Async/await instead of chaining
- ✅ Easy to add logging or modify

---

## Integration Guide

### For New Projects

1. **Add RadSim to project documentation:**
   ```bash
   cp .claude/docs/RADSIM_DOCUMENTATION.md docs/CODING_STANDARDS.md
   ```

2. **Configure your editor/IDE:**
   - Add linting rules that enforce clear naming
   - Set max line length (80-100 chars)
   - Enable auto-formatting

3. **Add to code review checklist:**
   ```markdown
   ## Code Review Checklist
   - [ ] Follows RadSim principles
   - [ ] Self-documenting names
   - [ ] Functions are single-purpose
   - [ ] No deep nesting
   - [ ] No hidden side effects
   ```

### For Existing Projects

1. **Start with new code:**
   - Apply RadSim to all new features
   - Don't rewrite everything at once

2. **Refactor incrementally:**
   - When fixing bugs, simplify the code
   - When adding features, refactor touched code

3. **Focus on high-value areas:**
   - Core business logic first
   - Complex algorithms second
   - UI code third

### For AI Assistants

1. **Add to system prompt** (see [System Prompts](#system-prompts))

2. **Create a `/radsim` command handler** in your bot or agent

3. **Add automatic detection** for code snippets

---

## FAQ

### Q: Does RadSim mean longer code?

**A:** Sometimes yes, but longer != worse. RadSim code is:
- Easier to understand (less cognitive load)
- Easier to modify (clear structure)
- Easier to debug (obvious flow)
- Easier for AI agents (predictable patterns)

A few extra lines are worth the clarity.

### Q: What about performance?

**A:** Premature optimization is the root of all evil. RadSim says:
1. Write simple, clear code first
2. Profile to find bottlenecks
3. Optimize only the slow parts
4. Keep optimizations well-documented

Simple code is often fast enough. And when it's not, it's easier to optimize because you understand it.

### Q: Can I use RadSim with X language?

**A:** Yes! RadSim is language-agnostic. The principles apply to:
- Python, JavaScript, TypeScript
- Go, Rust, C++, Java
- SQL, HTML, CSS
- Configuration files (JSON, YAML)
- Even shell scripts

### Q: What if my team doesn't follow RadSim?

**A:** Start with your own code:
- New code you write follows RadSim
- Code you review gets RadSim suggestions
- Gradually show the benefits (easier reviews, fewer bugs)
- Lead by example

### Q: How is RadSim different from Clean Code?

**A:** RadSim builds on Clean Code but adds:
- **AI-agent focus**: Optimized for Claude, GPT, Copilot
- **Cross-editor compatibility**: Works in any environment
- **Scalability emphasis**: Simple code scales better
- **Stricter simplicity**: If it's not obvious, simplify more

---

## Resources

### Related Documents
- `.claude/CLAUDE.md` - Full coding philosophy
- `.claude/commands/radsim.md` - Skill definition

### Further Reading
- Clean Code by Robert C. Martin
- The Pragmatic Programmer
- Simple Made Easy (Rich Hickey talk)

### Community
- Share your RadSim success stories
- Contribute improvements to the documentation
- Help others simplify their code

---

## Version History

**v1.1** (2026-02-15)
- Added Vertex AI provider (Google Cloud)
- Updated Claude models: Opus 4.6, Sonnet 4.5, Haiku 4.5
- Added OpenAI Codex variants and GPT-5 Mini
- CLI agent now supports 5 providers

**v1.0** (2026-01-31)
- Initial release
- 14 universal rules defined
- Claude Code integration
- Complete documentation

---

## License

This philosophy is free to use, share, and adapt. The goal is simple code for everyone.

---

**Remember: The best code is code that anyone can understand.**

*RadSim - Because simplicity scales.*
