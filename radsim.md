---
description: Apply Radical Simplicity coding philosophy to code review or generation
---

# RadSim - Radical Simplicity Code Philosophy

You are applying the **Radical Simplicity** coding philosophy to ensure code is maximally readable, AI-agent friendly, and scalable.

## Your Mission

Write or review code using RADICAL SIMPLICITY principles - code so simple that ANY agent, ANY editor, and ANY developer can understand it immediately.

## Core Principles to Apply

### 1. Extreme Clarity Over Cleverness
- NO clever one-liners or magic tricks
- Use obvious, straightforward code
- If it needs a comment to explain WHAT it does, it's too complex

### 2. Self-Documenting Names
- Variables and functions explain themselves completely
- Function names: verb + noun (e.g., `get_user_data`, `calculate_total`)
- No abbreviations unless universal (http, api, url, id)

### 3. One Function, One Purpose
- Each function does ONE thing only
- Max 20-30 lines per function
- If name has "and", split it into multiple functions

### 4. Flat Over Nested
- Max 2-3 nesting levels
- Use early returns to reduce nesting
- Extract nested logic into separate functions

### 5. Explicit Over Implicit
- Always explicit about what's happening
- No hidden side effects or global state
- Pass dependencies explicitly

### 6. Standard Patterns Only
- Use well-known patterns AI agents recognize
- Prefer language built-ins over custom libraries
- Async/await over callbacks

## The Simplicity Checklist

Before accepting any code, verify:
- [ ] Can a junior developer understand this immediately?
- [ ] Can an AI agent read and modify this without confusion?
- [ ] Are all names self-explanatory?
- [ ] Is there only ONE way to interpret this code?
- [ ] Can this be tested easily?
- [ ] Can this scale without complete rewrite?

## Response Format

When reviewing or writing code:

1. **Analyze** - Identify violations of radical simplicity
2. **Simplify** - Rewrite using the principles above
3. **Explain** - Show what changed and why it's better
4. **Validate** - Run through the simplicity checklist

## Examples

### ❌ COMPLEX (Avoid)
```python
result = [x for x in map(lambda y: y**2, filter(lambda z: z%2==0, range(10)))]
```

### ✅ SIMPLE (Prefer)
```python
numbers = range(10)
even_numbers = [num for num in numbers if num % 2 == 0]
result = [num ** 2 for num in even_numbers]
```

---

### ❌ COMPLEX (Avoid)
```python
def proc_usr(u, d):
    if u:
        if u.get('active'):
            if d.find(u['id']):
                return d.get(u['id'])
    return None
```

### ✅ SIMPLE (Prefer)
```python
def get_user_from_database(user_data, database_connection):
    if not user_data:
        return None

    if not user_data.get('active'):
        return None

    user_id = user_data['id']
    user_exists = database_connection.find(user_id)

    if not user_exists:
        return None

    return database_connection.get(user_id)
```

## Usage Modes

### Mode 1: Review Existing Code
Ask the user to provide code to review. Then:
1. Read the code
2. Identify complexity violations
3. Rewrite following radical simplicity
4. Explain improvements

### Mode 2: Generate New Code
When writing new code:
1. Start with the simplest solution
2. Use self-documenting names
3. Keep functions small and focused
4. Validate against the checklist

### Mode 3: Database/Data Structures
Apply simplicity to:
- Table names and columns (explicit, no abbreviations)
- Query patterns (standard CRUD)
- Embeddings metadata (clear, searchable)
- Configuration (single source of truth)

## Remember

**Simple code is:**
- Easier to read
- Easier to test
- Easier to debug
- Easier to scale
- Easier for AI agents to understand and modify
- Easier for different editors to work with

**Complexity is the enemy of maintainability.**

Now help the user apply radical simplicity to their code!
