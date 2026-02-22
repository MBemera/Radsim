# Search Skills

Tools for finding files and searching content in RadSim.

## Available Tools

### glob_files
Find files matching a glob pattern.

```python
# Find all Python files
glob_files(pattern="**/*.py")

# Find test files in specific directory
glob_files(pattern="tests/**/*.py", directory_path="src")

# Find config files
glob_files(pattern="*.{json,yaml,toml}")
```

**Parameters:**
- `pattern` (required): Glob pattern (e.g., `**/*.py`, `src/**/*.ts`)
- `directory_path` (optional): Base directory (default: current directory)

**Returns:**
```json
{
  "success": true,
  "matches": ["src/main.py", "src/utils.py", "tests/test_main.py"],
  "count": 3
}
```

**Pattern Examples:**
- `*.py` - Python files in current directory
- `**/*.py` - Python files recursively
- `src/**/*.{ts,tsx}` - TypeScript files in src/
- `test_*.py` - Files starting with "test_"

---

### grep_search
Search file contents with regex patterns.

```python
# Find function definitions
grep_search(pattern="def\\s+\\w+\\(", directory_path="src")

# Find TODO comments
grep_search(pattern="TODO|FIXME", file_pattern="*.py")

# Case-insensitive search
grep_search(pattern="error", case_sensitive=False)
```

**Parameters:**
- `pattern` (required): Regex pattern to search for
- `directory_path` (optional): Directory to search in
- `file_pattern` (optional): Glob pattern to filter files
- `case_sensitive` (optional): Case-sensitive search (default: True)
- `max_results` (optional): Maximum matches to return (default: 100)

**Returns:**
```json
{
  "success": true,
  "matches": [
    {"file": "src/main.py", "line": 42, "content": "def process_data(input):"},
    {"file": "src/utils.py", "line": 15, "content": "def helper_function():"}
  ],
  "count": 2,
  "files_searched": 25
}
```

---

### search_files
High-level search combining glob and content search.

```python
# Find files containing a specific import
search_files(
    pattern="from flask import",
    file_pattern="**/*.py"
)

# Find files by name and content
search_files(
    name_pattern="*test*.py",
    content_pattern="assert"
)
```

**Parameters:**
- `pattern` (optional): Content pattern to search
- `name_pattern` (optional): File name pattern
- `file_pattern` (optional): Glob pattern for files
- `directory_path` (optional): Base directory

---

### find_definition
Find where a symbol is defined (function, class, variable).

```python
find_definition(symbol="UserService", directory_path="src")
```

**Parameters:**
- `symbol` (required): Name of the symbol to find
- `directory_path` (optional): Directory to search

**Returns:**
```json
{
  "success": true,
  "definitions": [
    {"file": "src/services/user.py", "line": 15, "type": "class"}
  ],
  "count": 1
}
```

---

### find_references
Find all usages of a symbol.

```python
find_references(symbol="process_data", directory_path="src")
```

**Parameters:**
- `symbol` (required): Name of the symbol
- `directory_path` (optional): Directory to search

## Best Practices

1. **Start broad, then narrow** - Begin with a general search, then add constraints.

2. **Use appropriate patterns** - Use glob for file names, regex for content.

3. **Limit results** - Large codebases can have thousands of matches. Use `max_results`.

4. **Combine tools** - Use `glob_files` to find relevant files, then `grep_search` for content.

## Common Patterns

### Find all usages of a function
```python
# Step 1: Find definition
find_definition(symbol="my_function")

# Step 2: Find all references
find_references(symbol="my_function")
```

### Search for API endpoints
```python
grep_search(
    pattern="@app\\.(get|post|put|delete)\\(",
    file_pattern="**/*.py"
)
```

### Find configuration values
```python
grep_search(
    pattern="DATABASE_URL|API_KEY|SECRET",
    file_pattern="*.{py,env.example}"
)
```

### Locate test files for a module
```python
glob_files(pattern="**/test_mymodule*.py")
```
