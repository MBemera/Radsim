# Shell Commands Skills

Execute shell commands safely in RadSim.

## Available Tools

### run_shell_command
Execute a shell command with safety controls.

```python
# Simple command
run_shell_command(command="ls -la")

# With timeout
run_shell_command(command="npm install", timeout=120)

# In specific directory
run_shell_command(command="python setup.py install", cwd="./mypackage")
```

**Parameters:**
- `command` (required): The shell command to execute
- `timeout` (optional): Timeout in seconds (default: 60)
- `cwd` (optional): Working directory

**Returns:**
```json
{
  "success": true,
  "stdout": "command output...",
  "stderr": "",
  "returncode": 0
}
```

## Security Controls

### Destructive Commands (Require explicit confirmation)
These commands always prompt for confirmation, even in auto-confirm mode:

- `rm`, `rmdir`, `del`, `unlink`, `shred` - Deletion
- `sudo`, `su`, `chown`, `chmod` - Privileged operations
- `mv` - Moving (can overwrite)
- `git push`, `git reset`, `git rebase` - Git destructive
- `npm publish`, `pip upload` - Publishing
- `docker rm`, `docker rmi` - Container deletion
- `kubectl delete` - Kubernetes deletion

### Path Traversal Protection
Commands with `..` in arguments are blocked to prevent escaping the project directory.

## Common Use Cases

### Package Management
```python
# Python
run_shell_command(command="pip install requests")
run_shell_command(command="pip freeze > requirements.txt")

# Node.js
run_shell_command(command="npm install express")
run_shell_command(command="npm run build")

# Ruby
run_shell_command(command="bundle install")
```

### Running Tests
```python
# Python
run_shell_command(command="pytest tests/ -v")
run_shell_command(command="python -m pytest --cov=src")

# Node.js
run_shell_command(command="npm test")
run_shell_command(command="jest --coverage")
```

### Building Projects
```python
# Compile TypeScript
run_shell_command(command="tsc")

# Build frontend
run_shell_command(command="npm run build", timeout=300)

# Docker build
run_shell_command(command="docker build -t myapp .")
```

### Development Servers
```python
# Note: Long-running commands may timeout
run_shell_command(command="npm run dev", timeout=10)
# For servers, consider using background processes
```

## Best Practices

1. **Use specific tools when available** - Prefer `git_status` over `git status`.

2. **Set appropriate timeouts** - Builds and installs may need longer timeouts.

3. **Check return codes** - `returncode: 0` means success.

4. **Review destructive commands** - Always read the confirmation prompt.

5. **Avoid interactive commands** - Commands requiring input will hang.

## Common Patterns

### Check before install
```python
# Check if already installed
result = run_shell_command(command="which node")
if not result["success"]:
    run_shell_command(command="brew install node")
```

### Chain commands
```python
# Build and test
run_shell_command(command="npm run build && npm test")
```

### Capture output for analysis
```python
result = run_shell_command(command="npm outdated --json")
if result["success"]:
    outdated = json.loads(result["stdout"])
```

## Limitations

- **No interactive input** - Commands requiring user input will fail
- **Timeout** - Long-running processes may be killed
- **Working directory** - Commands run in project root by default
- **Environment** - Uses system environment variables
