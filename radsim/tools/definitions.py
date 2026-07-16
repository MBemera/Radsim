"""Tool definitions for RadSim API.

RadSim Principle: Single Source of Truth
"""


def _tool(
    name: str,
    description: str,
    properties: dict | None = None,
    required: list[str] | None = None,
) -> dict:
    """Build one provider-facing tool schema entry."""
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
    }


TOOL_DEFINITIONS = [
    # Browser Tools
    _tool("browser_open", "Visit a URL and capture content/screenshot (requires Playwright).",
        {"url": {"type": "string", "description": "URL to visit"}},
        ["url"]),
    _tool("browser_click", "Click an element on the current page.",
        {"selector": {"type": "string", "description": "CSS selector or text to click"}},
        ["selector"]),
    _tool("browser_type", "Type text into an input field.",
        {
            "selector": {"type": "string", "description": "CSS selector for input"},
            "text": {"type": "string", "description": "Text to type"},
        },
        ["selector", "text"]),
    _tool("browser_screenshot", "Take a screenshot of the current page.",
        {"filename": {"type": "string", "description": "Optional filename"}},
        []),
    # System Tools
    _tool("install_system_tool", "Install a system CLI tool (claude-code, gemini-cli, etc).",
        {
            "tool_name": {
                "type": "string",
                "description": "Tool name (e.g. 'claude-code', 'npm:pkg', 'brew:pkg')",
            }
        },
        ["tool_name"]),
    # File Operations
    _tool("read_file", "Read the contents of a file. Supports offset and limit for large files.",
        {
            "file_path": {"type": "string", "description": "Path to the file to read"},
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (0-indexed)",
                "default": 0,
            },
            "limit": {"type": "integer", "description": "Maximum number of lines to read"},
        },
        ["file_path"]),
    _tool("read_many_files", "Read multiple files at once. More efficient than reading one at a time.",
        {
            "file_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths to read (max 20)",
            }
        },
        ["file_paths"]),
    _tool("read_document", "Extract text from a document file: PDF, DOCX, XLSX, CSV, or plain text. Use this instead of read_file for binary document formats.",
        {"file_path": {"type": "string", "description": "Path to the document file"}},
        ["file_path"]),
    _tool("read_image", "Load an image (png/jpg/gif/webp) and attach it to the conversation so it can be visually interpreted. Requires a vision-capable model. Use to read screenshots, diagrams, charts, or photos the user provides.",
        {"file_path": {"type": "string", "description": "Path to the image file"}},
        ["file_path"]),
    _tool("write_file", "Write content to a file. Creates parent directories if needed.",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
            "file_path": {"type": "string", "description": "Path to the file to write"},
            "content": {"type": "string", "description": "Content to write to the file"},
        },
        ["file_path", "content"]),
    _tool("replace_in_file", "Replace text in a file. For single match only unless replace_all is true.",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
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
        ["file_path", "old_string", "new_string"]),
    _tool("rename_file", "Rename or move a file.",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
            "old_path": {"type": "string", "description": "Current file path"},
            "new_path": {"type": "string", "description": "New file path"},
        },
        ["old_path", "new_path"]),
    _tool("delete_file", "Delete a file. DESTRUCTIVE - requires confirmation.",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
            "file_path": {"type": "string", "description": "Path to the file to delete"},
        },
        ["file_path"]),
    # Directory Operations
    _tool("list_directory", "List contents of a directory with file types and sizes.",
        {
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
        []),
    _tool("create_directory", "Create a directory and any parent directories.",
        {"directory_path": {"type": "string", "description": "Path of directory to create"}},
        ["directory_path"]),
    # Search Tools
    _tool("glob_files", "Find files matching a glob pattern (like **/*.py, src/**/*.ts).",
        {
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
        ["pattern"]),
    _tool("grep_search", "Search file contents with regex. Returns file, line number, and content.",
        {
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
            "output_mode": {
                "type": "string",
                "description": "Output format: 'content' (matching lines with context), 'files_only' (just file paths), 'count' (match counts per file)",
                "enum": ["content", "files_only", "count"],
                "default": "content",
            },
        },
        ["pattern"]),
    _tool("search_files", "Simple text search. Returns list of files containing the pattern.",
        {
            "pattern": {"type": "string", "description": "Text to search for"},
            "directory_path": {
                "type": "string",
                "description": "Directory to search (default: current)",
                "default": ".",
            },
        },
        ["pattern"]),
    # Shell Execution
    _tool("run_shell_command", "Execute a shell command (bash on Unix, PowerShell on Windows).",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
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
        ["command"]),
    # Web Tools
    _tool("web_fetch", "Fetch content from a URL.",
        {"url": {"type": "string", "description": "URL to fetch"}},
        ["url"]),
    _tool("http_request", "Make an HTTP request to an API endpoint (GET/POST/PUT/PATCH/DELETE/HEAD) with optional headers and body. Use for JSON/REST APIs; use web_fetch for reading web pages.",
        {
            "url": {"type": "string", "description": "Full http(s) URL"},
            "method": {"type": "string", "description": "HTTP method (default GET)"},
            "headers": {
                "type": "object",
                "description": "Optional request headers as name: value pairs",
            },
            "body": {
                "type": "string",
                "description": "Optional request body (JSON should be a serialized string)",
            },
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
        },
        ["url"]),
    _tool("screen_capture", "Capture the user's screen (macOS only) and attach the screenshot to the conversation for visual interpretation. Requires a vision-capable model. Use when the user says 'look at my screen' or asks about something they can see.",
        {
            "save_path": {
                "type": "string",
                "description": "Optional filename for the screenshot (defaults to a timestamped name)",
            }
        },
        []),
    # Git Tools
    _tool("git_status", "Get git repository status (current branch, changed files).",
        {},
        []),
    _tool("git_diff", "Get git diff (unstaged or staged changes).",
        {
            "staged": {
                "type": "boolean",
                "description": "Show staged changes only (default: false)",
                "default": False,
            },
            "file_path": {"type": "string", "description": "Specific file to diff (optional)"},
        },
        []),
    _tool("git_log", "Get git commit history.",
        {
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
        []),
    _tool("git_branch", "List all git branches.",
        {},
        []),
    # Code Intelligence
    _tool("find_definition", "Find where a symbol (function, class, variable) is defined.",
        {
            "symbol": {"type": "string", "description": "Symbol name to find definition of"},
            "directory_path": {
                "type": "string",
                "description": "Directory to search (default: current)",
                "default": ".",
            },
        },
        ["symbol"]),
    _tool("find_references", "Find all references to a symbol in the codebase.",
        {
            "symbol": {"type": "string", "description": "Symbol name to find references of"},
            "directory_path": {
                "type": "string",
                "description": "Directory to search (default: current)",
                "default": ".",
            },
        },
        ["symbol"]),
    # Testing & Validation Tools
    _tool("run_tests", "Run project tests with auto-detection (pytest, jest, go test, cargo test).",
        {
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
        []),
    _tool("lint_code", "Run linter on project (ruff, eslint, golangci-lint, clippy).",
        {
            "file_path": {"type": "string", "description": "Specific file to lint (optional)"},
            "fix": {
                "type": "boolean",
                "description": "Auto-fix issues if possible",
                "default": False,
            },
        },
        []),
    _tool("format_code", "Format code using project formatter (black, prettier, gofmt, rustfmt).",
        {
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
        []),
    _tool("type_check", "Run type checker (mypy, tsc, go vet).",
        {"file_path": {"type": "string", "description": "Specific file to check (optional)"}},
        []),
    # Git Write Operations
    _tool("git_add", "Stage files for commit.",
        {
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
        []),
    _tool("git_commit", "Create a git commit with a message.",
        {
            "message": {"type": "string", "description": "Commit message"},
            "amend": {
                "type": "boolean",
                "description": "Amend the previous commit",
                "default": False,
            },
        },
        ["message"]),
    _tool("git_checkout", "Switch branches or restore files.",
        {
            "branch": {"type": "string", "description": "Branch name to checkout"},
            "create": {"type": "boolean", "description": "Create new branch", "default": False},
            "file_path": {"type": "string", "description": "Restore specific file from HEAD"},
        },
        []),
    _tool("git_stash", "Stash or restore uncommitted changes.",
        {
            "action": {
                "type": "string",
                "enum": ["push", "pop", "list", "drop"],
                "description": "Stash action to perform",
                "default": "push",
            },
            "message": {"type": "string", "description": "Message for stash (only with push)"},
        },
        []),
    # Dependency Management
    _tool("list_dependencies", "List project dependencies (pip, npm, go, cargo).",
        {},
        []),
    _tool("add_dependency", "Add a package dependency to the project.",
        {
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
        ["package"]),
    _tool("remove_dependency", "Remove a package dependency from the project.",
        {"package": {"type": "string", "description": "Package name to remove"}},
        ["package"]),
    _tool("npm_install", "Install an npm package directly. Works without needing package.json to exist first.",
        {
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
        ["package"]),
    _tool("pip_install", "Install a Python pip package directly.",
        {
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
        ["package"]),
    _tool("init_project", "Initialize a new project using scaffolding tools like create-vite, create-react-app, etc.",
        {
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
        ["project_type"]),
    # Project Tools
    _tool("get_project_info", "Get information about the current project (type, tools, files).",
        {},
        []),
    _tool("batch_replace", "Replace text across multiple files in the project.",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
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
        ["pattern", "replacement"]),
    # Task Planning
    _tool("plan_task", "Create a structured task plan with subtasks.",
        {
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
        ["task_description"]),
    _tool("save_context", "Save conversation/task context to file for later resumption.",
        {
            "context_data": {"type": "object", "description": "Context data to save"},
            "filename": {
                "type": "string",
                "description": "Name of context file",
                "default": "radsim_context.json",
            },
        },
        ["context_data"]),
    _tool("load_context", "Load previously saved context from file.",
        {
            "filename": {
                "type": "string",
                "description": "Name of context file to load",
                "default": "radsim_context.json",
            }
        },
        []),
    # Agentic Delegation
    _tool("delegate_task", "Delegate a task to a sub-agent with tool access. Runs in background by default so the user can keep working. Default tier='fast' (Haiku, read-only tools, cheap). Use tier='capable' for code generation/refactoring (full tools). Set background=false only when the main agent needs the result immediately to continue.",
        {
            "task_description": {
                "type": "string",
                "description": "Detailed description of the task for the sub-agent",
            },
            "tier": {
                "type": "string",
                "description": "Model tier: 'fast' (default, Haiku, read-only tools), 'capable' (code gen, full tools), 'review' (audits, read-only tools)",
                "enum": ["fast", "capable", "review"],
                "default": "fast",
            },
            "context": {
                "type": "string",
                "description": "Additional context or file contents to provide",
            },
            "model": {
                "type": "string",
                "description": "Override: specific model alias or full model ID. Overrides tier default.",
                "default": "current",
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
                        "model": {
                            "type": "string",
                            "description": "Model for this task (defaults to 'current')",
                        },
                        "system_prompt": {
                            "type": "string",
                            "description": "Optional system prompt",
                        },
                    },
                    "required": ["task"],
                },
                "description": "Run multiple tasks in parallel with different models. If provided, task_description is ignored.",
            },
            "background": {
                "type": "boolean",
                "description": "Run in background (default: true). Set to false only when the main agent needs the result immediately to continue its current response.",
                "default": True,
            },
        },
        ["task_description"]),
    _tool("submit_completion", "Submit the final result of a delegated task (used by sub-agents).",
        {
            "summary": {"type": "string", "description": "Summary of work completed"},
            "artifacts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of files created or modified",
            },
        },
        ["summary"]),
    # Skill Management
    _tool("add_skill", "Add a permanent custom skill/instruction that applies to all future conversations.",
        {
            "instruction": {
                "type": "string",
                "description": "The skill instruction text (e.g., 'Always use type hints in Python')",
            },
            "category": {
                "type": "string",
                "description": "Optional category: code_style, language, framework, testing, naming, general",
            },
        },
        ["instruction"]),
    _tool("remove_skill", "Remove a skill by its index (1-based).",
        {
            "index": {
                "type": "integer",
                "description": "1-based index of the skill to remove (use list_skills to see indices)",
            },
        },
        ["index"]),
    {
        "name": "list_skills",
        "description": "List all active user skills/instructions.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    # Notifications
    _tool("send_telegram", "Send a message via Telegram bot. Requires prior /telegram setup.",
        {
            "message": {
                "type": "string",
                "description": "Message text to send via Telegram",
            },
        },
        ["message"]),
    # Advanced Skills
    _tool("analyze_code", "Analyze Python code structure using AST. Returns functions, classes, imports, and complexity metrics.",
        {
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
        ["file_path"]),
    _tool("run_docker", "Run Docker commands for container management. Actions: ps, images, run, stop, start, logs, exec, build, pull, rm, rmi.",
        {
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
            "command": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command argv to run in the container (for run or exec)",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional Docker options as explicit argv items",
            },
        },
        ["action"]),
    _tool("database_query", "Execute SQL queries on a SQLite database. Read-only by default for safety.",
        {
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
        ["query"]),
    _tool("generate_tests", "Generate test stubs for a Python source file. Creates pytest or unittest style test templates.",
        {
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
        ["source_file"]),
    _tool("refactor_code", "Perform code refactoring operations: rename symbols, extract functions, inline variables.",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
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
        ["action", "file_path"]),
    _tool("deploy", "Deploy application or check deployment readiness. Supports Vercel, Netlify, Heroku, Railway, Fly.io.",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
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
        []),
    # Memory & Scheduling
    _tool("save_memory", "Save a value to persistent memory. Use for storing user preferences, project context, or learned patterns that should persist across sessions.",
        {
            "key": {"type": "string", "description": "The key to store under"},
            "value": {"type": "string", "description": "The value to store"},
            "memory_type": {
                "type": "string",
                "description": "Type: 'preference' (user settings), 'context' (project-specific), 'pattern' (learned behaviors)",
                "default": "preference",
            },
        },
        ["key", "value"]),
    _tool("load_memory", "Load values from persistent memory. Retrieve stored preferences, project context, or patterns.",
        {
            "key": {"type": "string", "description": "The key to load (omit for all)"},
            "memory_type": {
                "type": "string",
                "description": "Type: 'preference', 'context', 'pattern'",
                "default": "preference",
            },
        },
        []),
    _tool("forget_memory", "Remove stale persistent memory. Use when a preference, project context key, or learned pattern is no longer true.",
        {
            "key": {"type": "string", "description": "The key or exact pattern text to remove"},
            "memory_type": {
                "type": "string",
                "description": "Type: 'preference', 'context', 'pattern'",
                "default": "preference",
            },
        },
        ["key"]),
    _tool("schedule_task", "Schedule a recurring task using cron syntax. Common examples: '*/5 * * * *' (every 5 min), '0 9 * * *' (daily 9am), '0 9 * * 1' (Monday 9am).",
        {
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
        ["name", "schedule", "command"]),
    _tool("list_schedules", "List all scheduled tasks and their status.",
        {},
        []),
    # Task Tracking
    _tool("todo_read", "Read the current task tracking list. Shows pending, in-progress, and completed items. Use frequently during multi-step tasks to check progress.",
        {},
        []),
    _tool("todo_write", "Update the task tracking list. Pass the full list of tasks with statuses. Exactly one task can be 'in_progress' at a time.",
        {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "Task ID (omit for new tasks)"},
                        "description": {"type": "string", "description": "Task description"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "default": "pending",
                        },
                    },
                    "required": ["description"],
                },
                "description": "Full task list with statuses",
            },
        },
        ["todos"]),
    # Codebase Structure
    _tool("repo_map", "Generate a ranked structural overview of the codebase showing all classes, functions, and methods with signatures. Use BEFORE reading individual files to understand the architecture. Much cheaper than reading every file.",
        {
            "directory_path": {
                "type": "string",
                "description": "Root directory to map (default: current)",
                "default": ".",
            },
            "focus_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to rank higher (currently relevant to the task)",
            },
            "max_tokens": {
                "type": "integer",
                "description": "Token budget for the map (default: 4000)",
                "default": 4000,
            },
            "language_filter": {
                "type": "string",
                "description": "Limit to a language: 'python', 'javascript', 'typescript'",
            },
        },
        []),
    # Multi-File Patch
    _tool("apply_patch", "Apply a multi-file unified diff patch atomically. Supports create, modify, and delete operations. If any hunk fails validation, no changes are applied.",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
            "patch": {
                "type": "string",
                "description": "Simplified unified diff text. Use '--- /dev/null' for create, '+++ /dev/null' for delete.",
            },
        },
        ["patch"]),
    # Atomic Batch Edit
    _tool("multi_edit", "Apply multiple search-and-replace edits to a single file atomically. If any edit fails, none are applied. More efficient than sequential replace_in_file calls.",
        {
            "_intent": {
                "type": "string",
                "description": "Brief explanation of why this action is needed and what it achieves",
            },
            "file_path": {"type": "string", "description": "Path to the file to edit"},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_string": {
                            "type": "string",
                            "description": "Exact text to find (must be unique in file)",
                        },
                        "new_string": {"type": "string", "description": "Replacement text"},
                    },
                    "required": ["old_string", "new_string"],
                },
                "description": "List of edits to apply in order",
            },
        },
        ["file_path", "edits"]),
    _tool("add_tool", "Register a new tool the agent can call. "
        "The new tool is appended to radsim/tools/custom_tools.py and hot-loaded "
        "so it is callable on the very next turn (no restart). "
        "Use when the user asks you to add or extend your tool capabilities.",
        {
            "name": {
                "type": "string",
                "description": "snake_case tool name, e.g. 'count_words'",
            },
            "description": {
                "type": "string",
                "description": "One-line description shown to future invocations of the model",
            },
            "parameters": {
                "type": "object",
                "description": (
                    "JSON Schema with 'properties' (and optional 'required'). "
                    "Each property becomes a named argument passed to the body."
                ),
            },
            "body": {
                "type": "string",
                "description": (
                    "Python function body (no 'def' line). "
                    "Receives each parameter as a named arg. "
                    "Must return a dict, conventionally {'success': bool, ...}. "
                    "os/subprocess/shutil imports are forbidden for safety."
                ),
            },
        },
        ["name", "description", "parameters", "body"]),
    _tool("list_custom_tools", "List all tools added via add_tool.",
        {},
        []),
    _tool("remove_tool", "Remove a custom tool that was added via add_tool.",
        {
            "name": {"type": "string", "description": "Tool name to remove"},
        },
        ["name"]),
]
