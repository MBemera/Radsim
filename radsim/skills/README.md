# RadSim Skills Documentation

This directory contains skill documentation that is loaded **just-in-time** when tools are invoked.

## How It Works

1. When a tool is called (e.g., `read_file`), the skill registry checks for matching documentation
2. If found, the skill docs are injected into the agent's context
3. This saves context window by only loading relevant information

## Available Skills

| Skill File | Tools Covered |
|------------|---------------|
| `file_operations.md` | read_file, read_many_files, write_file, replace_in_file, rename_file, delete_file |
| `directory_operations.md` | list_directory, create_directory |
| `search.md` | glob_files, grep_search, search_files, find_definition, find_references |
| `git_operations.md` | git_status, git_diff, git_log, git_branch, git_add, git_commit, git_checkout, git_stash |
| `shell_commands.md` | run_shell_command |
| `web_tools.md` | web_fetch |
| `browser_automation.md` | browser_open, browser_click, browser_type, browser_screenshot |

## Adding New Skills

1. Create a new `.md` file in this directory
2. Name it after the tool or tool category
3. Include:
   - Tool description
   - Parameters
   - Return values
   - Examples
   - Best practices

## Skill Registry API

```python
from radsim import load_skill, load_skill_for_tool, get_skill_registry

# Load specific skill
docs = load_skill("git_operations")

# Load skill for a tool
docs = load_skill_for_tool("git_status")

# List all available skills
registry = get_skill_registry()
skills = registry.list_available_skills()
```

## RadSim Principles Applied

- **Just-In-Time Loading**: Docs loaded only when needed
- **Observable by Default**: Clear documentation for every tool
- **Standardized Interfaces**: Consistent doc format across all skills
