# Directory Operations Skills

Tools for managing directories in RadSim.

## Available Tools

### list_directory
List contents of a directory.

```python
# Current directory
list_directory()

# Specific directory
list_directory(directory_path="src")

# Recursive listing
list_directory(directory_path="src", recursive=True, max_depth=2)
```

**Parameters:**
- `directory_path` (optional): Path to list (default: current directory)
- `recursive` (optional): List recursively (default: False)
- `max_depth` (optional): Maximum recursion depth (default: 3)

**Returns:**
```json
{
  "success": true,
  "path": "/project/src",
  "items": [
    {"name": "main.py", "type": "file", "size": 1234},
    {"name": "utils", "type": "directory"}
  ],
  "count": 2
}
```

---

### create_directory
Create a directory (and parent directories if needed).

```python
# Simple directory
create_directory(directory_path="new_folder")

# Nested directories
create_directory(directory_path="src/components/ui")
```

**Parameters:**
- `directory_path` (required): Path of directory to create

**Returns:**
```json
{
  "success": true,
  "path": "/project/src/components/ui"
}
```

## Best Practices

1. **Check existence first** - Use `list_directory` to verify paths.

2. **Use relative paths** - Stay within the project directory.

3. **Don't create unnecessary directories** - `write_file` creates parent dirs automatically.

## Common Patterns

### Explore project structure
```python
# Get overview
list_directory(recursive=True, max_depth=2)
```

### Set up new feature directory
```python
# Create directory structure
create_directory(directory_path="src/features/auth")
create_directory(directory_path="src/features/auth/components")
create_directory(directory_path="tests/features/auth")
```

### Check if directory exists
```python
result = list_directory(directory_path="target_dir")
if not result["success"]:
    create_directory(directory_path="target_dir")
```

## Limitations

- **Max 500 items** - Directory listings are capped
- **Hidden files excluded** - Files starting with `.` are skipped
- **Max depth 3** - Recursive listing limited to prevent overload

For finding specific files, use `glob_files` or `search_files` instead.
