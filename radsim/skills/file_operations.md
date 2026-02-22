# File Operations Skills

Tools for reading, writing, and modifying files in RadSim.

## Available Tools

### read_file
Read contents of a file with optional offset/limit.

```python
# Basic usage
read_file(file_path="src/main.py")

# Read specific lines (0-indexed)
read_file(file_path="src/main.py", offset=10, limit=50)
```

**Parameters:**
- `file_path` (required): Path to the file
- `offset` (optional): Line number to start from (0-indexed)
- `limit` (optional): Maximum lines to read

**Returns:**
```json
{
  "success": true,
  "content": "file contents...",
  "path": "/absolute/path/to/file",
  "line_count": 150
}
```

---

### read_many_files
Read multiple files at once (max 20 files).

```python
read_many_files(file_paths=["src/main.py", "src/utils.py", "README.md"])
```

**Parameters:**
- `file_paths` (required): List of file paths

---

### write_file
Create or overwrite a file. Creates parent directories automatically.

```python
write_file(
    file_path="src/new_module.py",
    content="def hello():\n    print('Hello')\n"
)
```

**Parameters:**
- `file_path` (required): Path for the file
- `content` (required): Content to write

**Protected Patterns:** Cannot write to `.env`, `credentials`, `secrets`, `*.key`, `*.pem`

---

### replace_in_file
Replace specific text in a file (like Claude Code's Edit tool).

```python
# Single replacement (must be unique)
replace_in_file(
    file_path="src/config.py",
    old_string="DEBUG = False",
    new_string="DEBUG = True"
)

# Replace all occurrences
replace_in_file(
    file_path="src/app.py",
    old_string="old_function",
    new_string="new_function",
    replace_all=True
)
```

**Parameters:**
- `file_path` (required): Path to the file
- `old_string` (required): Exact text to find
- `new_string` (required): Replacement text
- `replace_all` (optional): Replace all occurrences (default: False)

**Important:** If `old_string` appears multiple times and `replace_all=False`, the operation fails. Provide more context in `old_string` to make it unique.

---

### rename_file
Rename or move a file.

```python
rename_file(
    old_path="src/old_name.py",
    new_path="src/new_name.py"
)
```

---

### delete_file
Delete a file (requires explicit confirmation).

```python
delete_file(file_path="temp/unused.py")
```

**Warning:** This action cannot be undone.

## Best Practices

1. **Always read before editing** - Use `read_file` to understand existing content before making changes.

2. **Use precise replacements** - Include surrounding context in `old_string` to ensure uniqueness.

3. **Check for protected paths** - Don't attempt to modify `.env`, credentials, or key files.

4. **Handle large files** - Use `offset` and `limit` for files over 100KB.

## Common Patterns

### Safe file modification
```python
# 1. Read the file first
result = read_file(file_path="config.py")
if not result["success"]:
    return result

# 2. Make targeted replacement
replace_in_file(
    file_path="config.py",
    old_string="old_value",
    new_string="new_value"
)
```

### Create file with directory
```python
# write_file automatically creates parent directories
write_file(
    file_path="src/new_package/module.py",
    content="# New module\n"
)
```
