"""Tool definitions for RadSim API.

RadSim Principle: Single Source of Truth
"""

TOOL_DEFINITIONS = [
    # Browser Tools
    {
        "name": "browser_open",
        "description": "Visit a URL and capture content/screenshot (requires Playwright).",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to visit"}},
            "required": ["url"],
        },
    },
    {
        "name": "browser_click",
        "description": "Click an element on the current page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector or text to click"}
            },
            "required": ["selector"],
        },
    },
    {
        "name": "browser_type",
        "description": "Type text into an input field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for input"},
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "browser_screenshot",
        "description": "Take a screenshot of the current page.",
        "input_schema": {
            "type": "object",
            "properties": {"filename": {"type": "string", "description": "Optional filename"}},
            "required": [],
        },
    },
    # System Tools
    {
        "name": "install_system_tool",
        "description": "Install a system CLI tool (claude-code, gemini-cli, etc).",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Tool name (e.g. 'claude-code', 'npm:pkg', 'brew:pkg')",
                }
            },
            "required": ["tool_name"],
        },
    },
    # File Operations
    {
        "name": "read_file",
        "description": "Read the contents of a file. Supports offset and limit for large files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to read"},
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (0-indexed)",
                    "default": 0,
                },
                "limit": {"type": "integer", "description": "Maximum number of lines to read"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "read_many_files",
        "description": "Read multiple files at once. More efficient than reading one at a time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to read (max 20)",
                }
            },
            "required": ["file_paths"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates parent directories if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "replace_in_file",
        "description": "Replace text in a file. For single match only unless replace_all is true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file"},
                "old_string": {
                    "type": "string",
                    "description": "Exact text to replace (must be unique unless replace_all)",
                },
                "new_string": {"type": "string", "description": "New text to insert"},
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false)",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "rename_file",
        "description": "Rename or move a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "old_path": {"type": "string", "description": "Current file path"},
                "new_path": {"type": "string", "description": "New file path"},
            },
            "required": ["old_path", "new_path"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file. DESTRUCTIVE - requires confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to delete"}
            },
            "required": ["file_path"],
        },
    },
    # Directory Operations
    {
        "name": "list_directory",
        "description": "List contents of a directory with file types and sizes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory_path": {
                    "type": "string",
                    "description": "Path to list (default: current directory)",
                    "default": ".",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "List recursively (default: false)",
                    "default": False,
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursion depth (default: 3)",
                    "default": 3,
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_directory",
        "description": "Create a directory and any parent directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory_path": {"type": "string", "description": "Path of directory to create"}
            },
            "required": ["directory_path"],
        },
    },
    # Search Tools
    {
        "name": "glob_files",
        "description": "Find files matching a glob pattern (like **/*.py, src/**/*.ts).",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.ts')",
                },
                "directory_path": {
                    "type": "string",
                    "description": "Base directory (default: current)",
                    "default": ".",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_search",
        "description": "Search file contents with regex. Returns file, line number, and content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "directory_path": {
                    "type": "string",
                    "description": "Directory to search (default: current)",
                    "default": ".",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Glob to filter files (e.g., '*.py', '*.js')",
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default: false)",
                    "default": False,
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context before/after match (default: 0)",
                    "default": 0,
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "search_files",
        "description": "Simple text search. Returns list of files containing the pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text to search for"},
                "directory_path": {
                    "type": "string",
                    "description": "Directory to search (default: current)",
                    "default": ".",
                },
            },
            "required": ["pattern"],
        },
    },
    # Shell Execution
    {
        "name": "run_shell_command",
        "description": "Execute a shell command (bash on Unix, PowerShell on Windows).",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to execute"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 120)",
                    "default": 120,
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory (default: current)",
                },
            },
            "required": ["command"],
        },
    },
    # Web Tools
    {
        "name": "web_fetch",
        "description": "Fetch content from a URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to fetch"}},
            "required": ["url"],
        },
    },
    # Git Tools
    {
        "name": "git_status",
        "description": "Get git repository status (current branch, changed files).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "git_diff",
        "description": "Get git diff (unstaged or staged changes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "staged": {
                    "type": "boolean",
                    "description": "Show staged changes only (default: false)",
                    "default": False,
                },
                "file_path": {"type": "string", "description": "Specific file to diff (optional)"},
            },
            "required": [],
        },
    },
    {
        "name": "git_log",
        "description": "Get git commit history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of commits (default: 10)",
                    "default": 10,
                },
                "oneline": {
                    "type": "boolean",
                    "description": "One line per commit (default: true)",
                    "default": True,
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_branch",
        "description": "List all git branches.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    # Code Intelligence
    {
        "name": "find_definition",
        "description": "Find where a symbol (function, class, variable) is defined.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol name to find definition of"},
                "directory_path": {
                    "type": "string",
                    "description": "Directory to search (default: current)",
                    "default": ".",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "find_references",
        "description": "Find all references to a symbol in the codebase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol name to find references of"},
                "directory_path": {
                    "type": "string",
                    "description": "Directory to search (default: current)",
                    "default": ".",
                },
            },
            "required": ["symbol"],
        },
    },
    # Testing & Validation Tools
    {
        "name": "run_tests",
        "description": "Run project tests with auto-detection (pytest, jest, go test, cargo test).",
        "input_schema": {
            "type": "object",
            "properties": {
                "test_command": {
                    "type": "string",
                    "description": "Override auto-detected test command",
                },
                "test_path": {
                    "type": "string",
                    "description": "Specific test file or directory to run",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Show verbose output",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "lint_code",
        "description": "Run linter on project (ruff, eslint, golangci-lint, clippy).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Specific file to lint (optional)"},
                "fix": {
                    "type": "boolean",
                    "description": "Auto-fix issues if possible",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "format_code",
        "description": "Format code using project formatter (black, prettier, gofmt, rustfmt).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Specific file to format (optional)",
                },
                "check_only": {
                    "type": "boolean",
                    "description": "Only check formatting without modifying",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "type_check",
        "description": "Run type checker (mypy, tsc, go vet).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Specific file to check (optional)"}
            },
            "required": [],
        },
    },
    # Git Write Operations
    {
        "name": "git_add",
        "description": "Stage files for commit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of files to stage",
                },
                "all_files": {
                    "type": "boolean",
                    "description": "Stage all changes (git add -A)",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_commit",
        "description": "Create a git commit with a message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "amend": {
                    "type": "boolean",
                    "description": "Amend the previous commit",
                    "default": False,
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "git_checkout",
        "description": "Switch branches or restore files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name to checkout"},
                "create": {"type": "boolean", "description": "Create new branch", "default": False},
                "file_path": {"type": "string", "description": "Restore specific file from HEAD"},
            },
            "required": [],
        },
    },
    {
        "name": "git_stash",
        "description": "Stash or restore uncommitted changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["push", "pop", "list", "drop"],
                    "description": "Stash action to perform",
                    "default": "push",
                },
                "message": {"type": "string", "description": "Message for stash (only with push)"},
            },
            "required": [],
        },
    },
    # Dependency Management
    {
        "name": "list_dependencies",
        "description": "List project dependencies (pip, npm, go, cargo).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "add_dependency",
        "description": "Add a package dependency to the project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package name (with optional version like 'requests>=2.0')",
                },
                "dev": {
                    "type": "boolean",
                    "description": "Install as dev dependency",
                    "default": False,
                },
            },
            "required": ["package"],
        },
    },
    {
        "name": "remove_dependency",
        "description": "Remove a package dependency from the project.",
        "input_schema": {
            "type": "object",
            "properties": {"package": {"type": "string", "description": "Package name to remove"}},
            "required": ["package"],
        },
    },
    {
        "name": "npm_install",
        "description": "Install an npm package directly. Works without needing package.json to exist first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package name (e.g., 'vite', 'react', '@types/node')",
                },
                "dev": {
                    "type": "boolean",
                    "description": "Install as dev dependency (--save-dev)",
                    "default": False,
                },
                "global_install": {
                    "type": "boolean",
                    "description": "Install globally (-g)",
                    "default": False,
                },
            },
            "required": ["package"],
        },
    },
    {
        "name": "pip_install",
        "description": "Install a Python pip package directly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package name (e.g., 'flask', 'requests>=2.0')",
                },
                "upgrade": {
                    "type": "boolean",
                    "description": "Upgrade if already installed (--upgrade)",
                    "default": False,
                },
            },
            "required": ["package"],
        },
    },
    {
        "name": "init_project",
        "description": "Initialize a new project using scaffolding tools like create-vite, create-react-app, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_type": {
                    "type": "string",
                    "description": "Project type: 'npm', 'vite', 'react', 'next', 'astro', 'python'",
                },
                "name": {
                    "type": "string",
                    "description": "Project name (used for directory and package name)",
                },
                "template": {
                    "type": "string",
                    "description": "Template variant (e.g., 'react-ts', 'vue' for Vite)",
                },
            },
            "required": ["project_type"],
        },
    },
    # Project Tools
    {
        "name": "get_project_info",
        "description": "Get information about the current project (type, tools, files).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "batch_replace",
        "description": "Replace text across multiple files in the project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text or regex pattern to find"},
                "replacement": {"type": "string", "description": "Text to replace with"},
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '*.py')",
                    "default": "*",
                },
                "directory_path": {
                    "type": "string",
                    "description": "Directory to search in",
                    "default": ".",
                },
            },
            "required": ["pattern", "replacement"],
        },
    },
    # Task Planning
    {
        "name": "plan_task",
        "description": "Create a structured task plan with subtasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "High-level task description",
                },
                "subtasks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of subtask descriptions",
                },
            },
            "required": ["task_description"],
        },
    },
    {
        "name": "save_context",
        "description": "Save conversation/task context to file for later resumption.",
        "input_schema": {
            "type": "object",
            "properties": {
                "context_data": {"type": "object", "description": "Context data to save"},
                "filename": {
                    "type": "string",
                    "description": "Name of context file",
                    "default": "radsim_context.json",
                },
            },
            "required": ["context_data"],
        },
    },
    {
        "name": "load_context",
        "description": "Load previously saved context from file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of context file to load",
                    "default": "radsim_context.json",
                }
            },
            "required": [],
        },
    },
    # Agentic Delegation
    {
        "name": "delegate_task",
        "description": "Delegate a task to a sub-agent using a specified model. Supports parallel execution with multiple models.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Detailed description of the task for the sub-agent",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context or file contents to provide",
                },
                "model": {
                    "type": "string",
                    "description": "Model to use: 'free', 'glm', 'minimax', 'kimi', 'qwen', 'arcee', or full OpenRouter model ID",
                    "default": "free",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional system prompt for the sub-agent",
                },
                "parallel_tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "description": "Task description"},
                            "model": {"type": "string", "description": "Model for this task"},
                            "system_prompt": {"type": "string", "description": "Optional system prompt"},
                        },
                        "required": ["task"],
                    },
                    "description": "Run multiple tasks in parallel with different models. If provided, task_description is ignored.",
                },
            },
            "required": ["task_description"],
        },
    },
    {
        "name": "submit_completion",
        "description": "Submit the final result of a delegated task (used by sub-agents).",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Summary of work completed"},
                "artifacts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of files created or modified",
                },
            },
            "required": ["summary"],
        },
    },
    # Advanced Skills
    {
        "name": "analyze_code",
        "description": "Analyze Python code structure using AST. Returns functions, classes, imports, and complexity metrics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Python file to analyze",
                },
                "analysis_type": {
                    "type": "string",
                    "description": "Type of analysis: 'full', 'functions', 'classes', 'imports', 'complexity'",
                    "default": "full",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "run_docker",
        "description": "Run Docker commands for container management. Actions: ps, images, run, stop, start, logs, exec, build, pull, rm, rmi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Docker action: ps, images, run, stop, start, logs, exec, build, pull, rm, rmi",
                },
                "container": {
                    "type": "string",
                    "description": "Container name or ID (for stop, start, logs, exec, rm)",
                },
                "image": {
                    "type": "string",
                    "description": "Image name (for run, pull, build, rmi)",
                },
                "command": {"type": "string", "description": "Command to run (for run, exec)"},
                "options": {"type": "string", "description": "Additional Docker options as string"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "database_query",
        "description": "Execute SQL queries on a SQLite database. Read-only by default for safety.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL query to execute"},
                "database_path": {
                    "type": "string",
                    "description": "Path to SQLite database file",
                    "default": "database.db",
                },
                "read_only": {
                    "type": "boolean",
                    "description": "If true, only SELECT queries allowed",
                    "default": True,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "generate_tests",
        "description": "Generate test stubs for a Python source file. Creates pytest or unittest style test templates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_file": {
                    "type": "string",
                    "description": "Path to the source file to generate tests for",
                },
                "output_file": {
                    "type": "string",
                    "description": "Path for the test file (default: test_<source_file>)",
                },
                "framework": {
                    "type": "string",
                    "description": "Test framework: 'pytest' or 'unittest'",
                    "default": "pytest",
                },
            },
            "required": ["source_file"],
        },
    },
    {
        "name": "refactor_code",
        "description": "Perform code refactoring operations: rename symbols, extract functions, inline variables.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Refactoring action: 'rename', 'extract_function', 'inline_variable'",
                },
                "file_path": {"type": "string", "description": "Path to the file to refactor"},
                "old_name": {
                    "type": "string",
                    "description": "Current name (for rename, inline_variable)",
                },
                "new_name": {"type": "string", "description": "New name (for rename)"},
                "target_line": {
                    "type": "integer",
                    "description": "Line number to extract (for extract_function)",
                },
                "new_function_name": {
                    "type": "string",
                    "description": "Name for extracted function",
                },
            },
            "required": ["action", "file_path"],
        },
    },
    {
        "name": "deploy",
        "description": "Deploy application or check deployment readiness. Supports Vercel, Netlify, Heroku, Railway, Fly.io.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": "Target platform: 'vercel', 'netlify', 'heroku', 'railway', 'flyio', 'auto'",
                },
                "check_only": {
                    "type": "boolean",
                    "description": "If true, only check readiness without deploying",
                    "default": False,
                },
                "command": {"type": "string", "description": "Custom deploy command to run"},
            },
            "required": [],
        },
    },
    # Memory & Scheduling
    {
        "name": "save_memory",
        "description": "Save a value to persistent memory. Use for storing user preferences, project context, or learned patterns that should persist across sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key to store under"},
                "value": {"type": "string", "description": "The value to store"},
                "memory_type": {
                    "type": "string",
                    "description": "Type: 'preference' (user settings), 'context' (project-specific), 'pattern' (learned behaviors)",
                    "default": "preference",
                },
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "load_memory",
        "description": "Load values from persistent memory. Retrieve stored preferences, project context, or patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key to load (omit for all)"},
                "memory_type": {
                    "type": "string",
                    "description": "Type: 'preference', 'context', 'pattern'",
                    "default": "preference",
                },
            },
            "required": [],
        },
    },
    {
        "name": "schedule_task",
        "description": "Schedule a recurring task using cron syntax. Common examples: '*/5 * * * *' (every 5 min), '0 9 * * *' (daily 9am), '0 9 * * 1' (Monday 9am).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique name for the scheduled task"},
                "schedule": {
                    "type": "string",
                    "description": "Cron expression: 'minute hour day-of-month month day-of-week'",
                },
                "command": {"type": "string", "description": "Shell command to execute"},
                "description": {
                    "type": "string",
                    "description": "Optional description of the task",
                },
            },
            "required": ["name", "schedule", "command"],
        },
    },
    {
        "name": "list_schedules",
        "description": "List all scheduled tasks and their status.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]
