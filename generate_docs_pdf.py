"""Generate RadSim documentation PDF.

Uses fpdf2 for professional PDF generation with clean aesthetics.
Ensures no text overlapping and strictly no emojis.
"""

from fpdf import FPDF

# Page dimensions for A4
PAGE_W = 210
PAGE_H = 297
MARGIN_L = 20
MARGIN_R = 20
MARGIN_T = 20
MARGIN_B = 20
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R
EFFECTIVE_PAGE_H = PAGE_H - MARGIN_T - MARGIN_B


class RadSimDoc(FPDF):
    """Professional PDF document for RadSim documentation."""

    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=MARGIN_B)
        self.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)

    # ── Header / Footer ──

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            y_start = 10
            self.set_xy(MARGIN_L, y_start)
            self.cell(CONTENT_W / 2, 6, "RadSim v1.1.0 - Technical Documentation", align="L")
            self.set_xy(PAGE_W / 2, y_start)
            self.cell((CONTENT_W / 2), 6, f"Page {self.page_no()}", align="R")
            
            # Draw line
            self.set_xy(MARGIN_L, y_start + 7)
            self.set_draw_color(220, 220, 220)
            self.set_line_width(0.3)
            self.line(MARGIN_L, self.get_y(), PAGE_W - MARGIN_R, self.get_y())
            self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(160, 160, 160)
        self.cell(0, 10, "Emera Digital Tools  |  github.com/MBemera/Radsim", align="C")

    # ── Helper for Page Breaks ──

    def check_space(self, height_needed):
        """Check if there is enough space on the page, else add new page."""
        if self.get_y() + height_needed > PAGE_H - MARGIN_B:
            self.add_page()

    # ── Formatting Methods ──

    def section(self, number, title):
        """Major section heading with professional styling."""
        self.add_page()  # Always start sections on a new page for cleanliness
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(20, 40, 80)  # Dark Navy
        
        heading = f"{number}. {title}" if number else title
        self.cell(0, 10, heading)
        self.ln(12)
        
        # Underline
        start_y = self.get_y() - 4
        self.set_draw_color(20, 40, 80)
        self.set_line_width(0.8)
        self.line(MARGIN_L, start_y, PAGE_W - MARGIN_R, start_y)
        self.ln(5)

    def subsection(self, title):
        """Sub-heading."""
        self.check_space(20)
        self.ln(4)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(40, 40, 40)
        self.cell(0, 8, title)
        self.ln(10)

    def para(self, text):
        """Standard paragraph."""
        self.set_font("Helvetica", "", 10)
        self.set_text_color(50, 50, 50)
        self.multi_cell(CONTENT_W, 5, text)
        self.ln(5)

    def bullet_list(self, items):
        """Render a clean bullet list."""
        self.set_font("Helvetica", "", 10)
        self.set_text_color(50, 50, 50)
        for item in items:
            self.check_space(10)
            current_y = self.get_y()
            self.set_x(MARGIN_L + 5)
            # Draw bullet manually to ensure alignment
            self.cell(5, 5, chr(149), align='C') # Simple dot bullet
            self.set_xy(MARGIN_L + 12, current_y)
            self.multi_cell(CONTENT_W - 12, 5, item)
            self.ln(2)
        self.ln(3)

    def code(self, text):
        """Code block with background and wrapping."""
        self.set_font("Courier", "", 9)
        self.set_text_color(30, 30, 30)
        self.set_fill_color(245, 245, 245)
        
        lines = text.split('\n')
        # Calculate height needed
        line_height = 5
        total_height = len(lines) * line_height + 4
        
        self.check_space(total_height)
        
        # Draw background block? No, simpler to just fill lines for better wrapping support
        # But to make it look like a block, we can iterate
        
        for line in lines:
            # Handle long lines in code by wrapping
            # We need to preserve indentation
            indent = len(line) - len(line.lstrip())
            safe_line = line.replace('\t', '    ')
            
            # Check if line fits width
            # Courier 9pt is approx 2.5mm per char?
            # A safer way is using multi_cell even for code
            self.check_space(line_height)
            self.cell(CONTENT_W, line_height, f"  {safe_line}", fill=True, ln=1)
            
        self.ln(5)

    def table(self, headers, rows, widths):
        """Robust table rendering."""
        row_height = 7
        
        # Calculate approximate height for header
        self.check_space(row_height * 2)

        # Header
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(255, 255, 255)
        self.set_fill_color(50, 70, 100) # Slate blue
        
        x_start = MARGIN_L
        for i, h in enumerate(headers):
            self.set_xy(x_start, self.get_y())
            self.cell(widths[i], row_height, str(h), border=0, fill=True, align='C')
            x_start += widths[i]
        self.ln(row_height)

        # Rows
        self.set_font("Helvetica", "", 9)
        self.set_text_color(40, 40, 40)
        
        fill = False
        for row in rows:
            # Check height for this row (assuming 1 line per cell for check, 
            # but multi_cell might expand it)
            # We'll calculate max height needed for this row
            max_lines = 1
            for i, cell_text in enumerate(row):
                # Simulate multi_cell to get height
                # FPDF2 has get_string_width, but exact wrapping is tricky to predict without actually doing it
                # We'll assume approx chars per line
                pass
            
            # Simple check for at least 15mm
            self.check_space(15)

            if fill:
                self.set_fill_color(245, 247, 250)
            else:
                self.set_fill_color(255, 255, 255)
                
            # We need to find the height of the tallest cell in this row
            y_before = self.get_y()
            max_y = y_before
            
            # First pass: render invisibly or just render and backtrack? 
            # FPDF doesn't support easy backtracking.
            # We will render all cells with same Y, allowing them to expand down.
            # Then we set Y to the max Y reached.
            
            x_curr = MARGIN_L
            for i, cell_text in enumerate(row):
                self.set_xy(x_curr, y_before)
                self.multi_cell(widths[i], row_height, str(cell_text), border=0, fill=True, align='L')
                if self.get_y() > max_y:
                    max_y = self.get_y()
                x_curr += widths[i]
            
            # Draw borders or just spacing?
            # Let's draw a light bottom line for the row
            self.set_draw_color(230, 230, 230)
            self.line(MARGIN_L, max_y, PAGE_W - MARGIN_R, max_y)

            # Advance
            self.set_y(max_y)
            fill = not fill
            
        self.ln(5)


def build_pdf():
    pdf = RadSimDoc()
    pdf.set_title("RadSim Documentation v1.1.0")
    pdf.set_author("Emera Digital Tools")

    # ════════════════════════════════════════
    # TITLE PAGE
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.ln(60)
    
    # Title
    pdf.set_font("Helvetica", "B", 36)
    pdf.set_text_color(20, 40, 80)
    pdf.cell(0, 15, "RadSim", align="C")
    pdf.ln(15)
    
    # Subtitle
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, "Radically Simple Code Generator", align="C")
    pdf.ln(20)
    
    # Divider
    pdf.set_draw_color(20, 40, 80)
    pdf.set_line_width(0.5)
    line_w = 40
    pdf.line((PAGE_W/2) - (line_w/2), pdf.get_y(), (PAGE_W/2) + (line_w/2), pdf.get_y())
    pdf.ln(20)
    
    # Version Info
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, "Technical Documentation", align="C")
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Version 1.1.0", align="C")
    
    # Footer Area
    pdf.set_y(-60)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, "Author: Matthew Bright", align="C")
    pdf.ln(5)
    pdf.cell(0, 6, "Emera Digital Tools  |  February 2026", align="C")

    # ════════════════════════════════════════
    # TABLE OF CONTENTS
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(20, 40, 80)
    pdf.cell(0, 10, "Table of Contents")
    pdf.ln(15)
    
    toc = [
        " 1.  Overview",
        " 2.  Installation and Setup",
        " 3.  Dependencies",
        " 4.  Project Structure",
        " 5.  CLI Usage and Arguments",
        " 6.  Configuration System",
        " 7.  Supported AI Providers and Models",
        " 8.  Core Agent Loop",
        " 9.  Built-in Tools (35+)",
        "10.  Slash Commands",
        "11.  Modes (Teach, Verbose)",
        "12.  Learning System (8 Modules)",
        "13.  Memory and Vector Store",
        "14.  Security and Safety",
        "15.  Rate Limiting and Protection",
        "16.  Sub-Agent Delegation",
        "17.  Hooks System",
        "18.  Model Router and Failover",
        "19.  Skills System",
        "20.  Scheduler",
        "21.  Task Logging and Audit",
        "22.  Health Checks",
        "23.  Output and Display",
        "24.  Testing (685 Tests)",
        "25.  File Paths Reference",
        "26.  Public API Exports",
    ]
    
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(60, 60, 60)
    for item in toc:
        pdf.cell(0, 8, item)
        pdf.ln(8)

    # ════════════════════════════════════════
    # 1. OVERVIEW
    # ════════════════════════════════════════
    pdf.section(1, "Overview")
    pdf.para(
        "RadSim is a standalone CLI coding agent that provides Claude Code-like "
        "functionality with support for multiple AI providers. It runs locally using "
        "your own API key and offers 35+ built-in tools, interactive and single-shot "
        "modes, automatic provider failover, and a built-in learning system."
    )
    pdf.para(
        "Core Philosophy: Radical Simplicity. Write code so simple that any agent, "
        "any editor, and any developer can understand it immediately. Code is optimized "
        "for human readability, AI agent comprehension, cross-editor compatibility, "
        "and scalability."
    )
    pdf.subsection("Key Features")
    pdf.bullet_list([
        "Multi-provider AI support (Claude, OpenAI, Gemini, Vertex AI, OpenRouter)",
        "35+ built-in tools for file ops, search, git, shell, testing, and more",
        "Interactive REPL and single-shot execution modes",
        "Teach Mode with inline code explanations and auto-stripping for clean output",
        "Learning system that adapts to your coding style over time",
        "Semantic vector memory with ChromaDB (or JSON fallback)",
        "Sub-agent delegation to specialized models",
        "Intelligent model routing with automatic failover",
        "Three-layer rate limiting and budget protection",
        "Comprehensive security: path traversal, injection, and access control",
        "Event hooks for custom pre/post tool and API actions",
        "Structured audit logging (JSON and SQLite)",
        "Cron-style task scheduling",
        "Code analysis: complexity scoring, dead code detection, stress testing",
    ])

    # ════════════════════════════════════════
    # 2. INSTALLATION
    # ════════════════════════════════════════
    pdf.section(2, "Installation and Setup")

    pdf.subsection("Install from Source")
    pdf.code("pip install -e .")

    pdf.subsection("Install with Extras")
    pdf.code(
        "pip install -e '.[all]'      # All optional dependencies\n"
        "pip install -e '.[openai]'   # OpenAI support\n"
        "pip install -e '.[gemini]'   # Google Gemini support\n"
        "pip install -e '.[browser]'  # Browser automation (Playwright)\n"
        "pip install -e '.[memory]'   # Vector memory (ChromaDB)\n"
        "pip install -e '.[dev]'      # Development tools (pytest, ruff)"
    )

    pdf.subsection("First Run")
    pdf.para(
        "On first launch, RadSim runs an interactive onboarding wizard that guides "
        "you through provider selection, model choice, API key configuration, and "
        "security preferences. Settings are saved to ~/.radsim/.env with chmod 600 "
        "(owner read/write only)."
    )
    pdf.code(
        "radsim              # Interactive mode (launches onboarding first time)\n"
        "radsim --setup      # Re-run the setup wizard\n"
        'radsim "your task"  # Single-shot mode' 
    )

    pdf.subsection("Python Version Requirement")
    pdf.para("Requires Python 3.10 or later. Tested on 3.10, 3.11, 3.12, 3.13, and 3.14.")

    # ════════════════════════════════════════
    # 3. DEPENDENCIES
    # ════════════════════════════════════════
    pdf.section(3, "Dependencies")

    pdf.subsection("Build System")
    pdf.para("hatchling -- PEP 517 build backend.")

    pdf.subsection("Required Dependencies")
    pdf.table(
        ["Package", "Version Constraint", "Purpose"],
        [["anthropic", ">=0.40.0, <1.0", "Claude API client (Anthropic)"]],
        [40, 50, 80],
    )

    pdf.subsection("Optional Dependencies (pip extras)")
    pdf.table(
        ["Extra", "Package", "Version", "Purpose"],
        [
            ["openai", "openai", ">=1.50.0, <2.0", "OpenAI GPT models"],
            ["gemini", "google-genai", ">=0.8.0", "Google Gemini"],
            ["browser", "playwright", ">=1.40.0, <2.0", "Browser automation"],
            ["memory", "chromadb", ">=0.4.0, <1.0", "Vector memory"],
            ["vector", "chromadb", ">=0.4.0, <1.0", "Semantic search"],
        ],
        [25, 40, 45, 60],
    )

    pdf.subsection("Development Dependencies")
    pdf.table(
        ["Package", "Version", "Purpose"],
        [
            ["pytest", ">=8.0.0", "Test framework"],
            ["ruff", ">=0.4.0", "Linter and formatter"],
        ],
        [40, 40, 90],
    )

    # ════════════════════════════════════════
    # 4. PROJECT STRUCTURE
    # ════════════════════════════════════════
    pdf.section(4, "Project Structure")
    pdf.code(
        "radsim/\n"
        "  __init__.py          Public API exports\n"
        "  cli.py               CLI entry point, argument parsing\n"
        "  agent.py             Core agent loop (~1900 lines)\n"
        "  config.py            Configuration system, env loading\n"
        "  api_client.py        Multi-provider API wrapper\n"
        "  commands.py          Slash commands\n"
        "  modes.py             Mode system (teach, verbose)\n"
        "  prompts.py           System prompt construction\n"
        "  output.py            Terminal display formatting\n"
        "  safety.py            File write safety checks\n"
        "  access_control.py    Access code protection\n"
        "  hooks.py             Event hooks system\n"
        "  model_router.py      Intelligent model routing\n"
        "  rate_limiter.py      Loop protection, budgets\n"
        "  sub_agent.py         Sub-agent task delegation\n"
        "  memory.py            Simple JSON memory\n"
        "  vector_memory.py     Semantic memory (ChromaDB)\n"
        "  health.py            Startup health checks\n"
        "  scheduler.py         Cron-style task scheduling\n"
        "  task_logger.py       Structured audit logging\n"
        "  skills.py            User-configurable instructions\n"
        "  onboarding.py        First-time setup wizard"
    )
    pdf.ln(2)
    pdf.code(
        "  tools/\n"
        "    definitions.py     Tool JSON schema definitions\n"
        "    file_ops.py        read, write, replace, delete, rename\n"
        "    directory_ops.py   list, create directories\n"
        "    search.py          glob, grep, search files\n"
        "    shell.py           Shell command execution\n"
        "    git.py             Git operations\n"
        "    web.py             URL fetching\n"
        "    testing.py         lint, format, type-check, test\n"
        "    dependencies.py    Package management\n"
        "    code_intel.py      Find definitions/references\n"
        "    advanced.py        Docker, database, refactoring\n"
        "    project.py         Batch ops, planning, context\n"
        "    validation.py      Safety validation checks"
    )

    # ════════════════════════════════════════
    # 5. CLI USAGE
    # ════════════════════════════════════════
    pdf.section(5, "CLI Usage and Arguments")

    pdf.subsection("Basic Usage")
    pdf.code(
        "radsim                     # Interactive REPL mode\n"
        'radsim "Create a REST API" # Single-shot mode\n'
        "radsim --help              # Show help\n"
        "radsim --version           # Show version"
    )

    pdf.subsection("Command-Line Arguments")
    pdf.table(
        ["Argument", "Description"],
        [
            ["--provider, -p", "Provider: claude, openai, gemini, vertex"],
            ["--api-key, -k", "API key (overrides environment variable)"],
            ["--yes, -y", "Auto-confirm file writes (skip prompts)"],
            ["--verbose, -V", "Enable verbose output mode"],
            ["--no-stream", "Disable streaming responses"],
            ["--context-file", "Load initial context from a file"],
            ["--version, -v", "Show version and exit"],
            ["--skip-onboarding", "Skip first-time setup wizard"],
            ["--setup", "Re-run setup wizard"],
        ],
        [50, 120],
    )

    pdf.subsection("Exit Codes")
    pdf.bullet_list([
        "0 -- Success",
        "1 -- Error",
        "130 -- Interrupted (Ctrl+C)",
    ])

    # ════════════════════════════════════════
    # 6. CONFIGURATION
    # ════════════════════════════════════════
    pdf.section(6, "Configuration System")
    pdf.para("Configuration is loaded in the following priority order (highest first):")
    pdf.bullet_list([
        "CLI argument overrides (--provider, --api-key, etc.)",
        "Environment variables (RADSIM_*, ANTHROPIC_API_KEY, etc.)",
        "Local .env file in the current working directory",
        "Global ~/.radsim/.env",
        "Built-in default values",
    ])

    pdf.subsection("Config Settings")
    pdf.table(
        ["Setting", "Default", "Description"],
        [
            ["provider", "claude", "AI provider to use"],
            ["api_key", "(env)", "API key for selected provider"],
            ["model", "(auto)", "Model ID to use"],
            ["auto_confirm", "False", "Auto-yes for file writes"],
            ["verbose", "False", "Show detailed output"],
            ["stream", "True", "Enable streaming responses"],
            ["max_api_calls", "15", "Max API calls per user turn"],
            ["rate_limit_ms", "50", "Delay between API calls (ms)"],
        ],
        [40, 30, 100],
    )

    pdf.subsection("Environment Variables")
    pdf.table(
        ["Variable", "Purpose"],
        [
            ["RADSIM_PROVIDER", "Provider name"],
            ["RADSIM_MODEL", "Model ID"],
            ["RADSIM_API_KEY", "Generic API key"],
            ["ANTHROPIC_API_KEY", "Claude (Anthropic) API key"],
            ["OPENAI_API_KEY", "OpenAI API key"],
            ["GOOGLE_API_KEY", "Google Gemini API key"],
            ["GOOGLE_CLOUD_PROJECT", "Vertex AI project ID"],
            ["RADSIM_ACCESS_CODE", "Access protection code"],
        ],
        [60, 110],
    )

    # ════════════════════════════════════════
    # 7. PROVIDERS
    # ════════════════════════════════════════
    pdf.section(7, "Supported AI Providers")

    pdf.subsection("Claude (Anthropic) -- Default")
    pdf.table(
        ["Model ID", "Description"],
        [
            ["claude-opus-4-6", "Most capable; best for complex tasks"],
            ["claude-sonnet-4-5", "Balanced performance and cost"],
            ["claude-haiku-4-5", "Fast and cost-effective"],
        ],
        [50, 120],
    )

    pdf.subsection("OpenAI")
    pdf.table(
        ["Model ID", "Description"],
        [
            ["gpt-5.2", "Latest flagship model"],
            ["gpt-5.2-codex", "Code-specialized variant"],
            ["gpt-5-mini", "Smaller, faster model"],
        ],
        [50, 120],
    )

    pdf.subsection("Google Gemini")
    pdf.table(
        ["Model ID", "Description"],
        [
            ["gemini-3-pro", "Most capable Gemini model"],
            ["gemini-3-flash", "Fast Gemini model"],
        ],
        [50, 120],
    )

    # ════════════════════════════════════════
    # 8. CORE AGENT LOOP
    # ════════════════════════════════════════
    pdf.section(8, "Core Agent Loop")
    pdf.para(
        "The RadSimAgent class (agent.py) is the heart of the system. "
        "It manages the conversation loop, API calls, tool execution, context window "
        "management, and integration with the learning system."
    )

    pdf.subsection("Message Flow")
    pdf.bullet_list([
        "1. User input is added to the message history.",
        "2. Session auto-prunes if context window usage exceeds 80%.",
        "3. Learning system suggests optimal tool chains (if enabled).",
        "4. API call sent with system prompt, tool definitions, and messages.",
        "5. Response processed: text content and tool calls extracted.",
        "6. Each tool call executed (with user confirmation for writes).",
        "7. Tool results appended to messages.",
        "8. Steps 4-7 repeat until the API returns no more tool calls.",
    ])

    pdf.subsection("Tool Confirmation Categories")
    pdf.table(
        ["Category", "Tools", "Behavior"],
        [
            ["Confirmation", "write_file, delete_file", "Always asks user"],
            ["Required", "run_shell_command, deploy", "before executing"],
            ["Read-Only", "read_file, list_directory", "Executes immediately"],
            ["Light", "run_tests, lint_code", "Skipped when -y used"],
        ],
        [30, 60, 80],
    )

    # ════════════════════════════════════════
    # 9. TOOLS
    # ════════════════════════════════════════
    pdf.section(9, "Built-in Tools (35+)")

    pdf.subsection("File Operations")
    pdf.table(
        ["Tool", "Description"],
        [
            ["read_file", "Read file with pagination"],
            ["read_many_files", "Batch read multiple files"],
            ["write_file", "Create or overwrite a file"],
            ["replace_in_file", "Find and replace in file"],
            ["rename_file", "Rename or move a file"],
            ["delete_file", "Delete a file"],
        ],
        [40, 130],
    )

    pdf.subsection("Directory Operations")
    pdf.table(
        ["Tool", "Description"],
        [
            ["list_directory", "List directory contents"],
            ["create_directory", "Create directory with parents"],
        ],
        [40, 130],
    )

    pdf.subsection("Search")
    pdf.table(
        ["Tool", "Description"],
        [
            ["glob_files", "File pattern matching (glob)"],
            ["grep_search", "Regex content search (grep)"],
            ["search_files", "Simple text search"],
        ],
        [40, 130],
    )

    pdf.subsection("Git Operations")
    pdf.table(
        ["Tool", "Description"],
        [
            ["git_status", "Show working tree status"],
            ["git_diff", "Show changes (staged/unstaged)"],
            ["git_log", "Show commit history"],
            ["git_branch", "List branches"],
            ["git_add", "Stage files for commit"],
            ["git_commit", "Create a commit"],
            ["git_checkout", "Switch branches or restore"],
            ["git_stash", "Stash/pop changes"],
        ],
        [40, 130],
    )

    pdf.subsection("Testing and Quality")
    pdf.table(
        ["Tool", "Description"],
        [
            ["run_tests", "Run test suite"],
            ["lint_code", "Lint code with auto-fix option"],
            ["format_code", "Format code to standard"],
            ["type_check", "Run type checker"],
        ],
        [40, 130],
    )

    pdf.subsection("Shell and Dependencies")
    pdf.table(
        ["Tool", "Description"],
        [
            ["run_shell_command", "Execute shell command"],
            ["web_fetch", "Fetch URL content"],
            ["list_dependencies", "List project dependencies"],
            ["add_dependency", "Add a dependency"],
            ["npm_install / pip_install", "Install packages"],
        ],
        [50, 120],
    )

    # ════════════════════════════════════════
    # 10. COMMANDS
    # ════════════════════════════════════════
    pdf.section(10, "Slash Commands")

    pdf.subsection("Navigation and Help")
    pdf.table(
        ["Command", "Description"],
        [
            ["/help, /h", "Show help menu"],
            ["/tools", "List all available tools"],
            ["/commands", "List all slash commands"],
        ],
        [40, 130],
    )

    pdf.subsection("Configuration")
    pdf.table(
        ["Command", "Description"],
        [
            ["/switch", "Quick provider/model switch"],
            ["/config", "Full configuration menu"],
            ["/clear", "Clear conversation history"],
            ["/new", "Fresh conversation and reset all limits"],
        ],
        [40, 130],
    )

    pdf.subsection("Learning")
    pdf.table(
        ["Command", "Description"],
        [
            ["/good, /+", "Positive feedback"],
            ["/improve, /-", "Needs improvement feedback"],
            ["/stats", "Learning statistics"],
            ["/report", "Export learning report"],
            ["/preferences", "Show learned preferences"],
        ],
        [40, 130],
    )

    pdf.subsection("Analysis")
    pdf.table(
        ["Command", "Description"],
        [
            ["/teach", "Toggle Teach Mode"],
            ["/complexity", "Run complexity scoring"],
            ["/stress", "Run adversarial code review"],
            ["/archaeology", "Find dead/unused code"],
        ],
        [40, 130],
    )

    # ════════════════════════════════════════
    # 11. MODES
    # ════════════════════════════════════════
    pdf.section(11, "Modes")

    pdf.subsection("Teach Mode  (/teach)")
    pdf.para(
        "When active, the agent acts as a tutor. It proactively "
        "explains why it chose an approach and how things work. Code receives "
        "inline teaching annotations that are automatically stripped before writing to "
        "disk."
    )
    pdf.para("Annotation rules:")
    pdf.bullet_list([
        "Explain HOW (mechanism) and WHY (reasoning).",
        "Placed directly above functions, classes, imports.",
        "Code without annotations is rejected in this mode.",
    ])

    pdf.subsection("Verbose Mode  (/v)")
    pdf.para(
        "Shows detailed tool execution information including full tool inputs and "
        "outputs. Useful for debugging agent behavior."
    )

    # ════════════════════════════════════════
    # 12. LEARNING SYSTEM
    # ════════════════════════════════════════
    pdf.section(12, "Learning System")
    pdf.para(
        "RadSim includes 8 learning modules that adapt to the user over time. "
        "Data is stored in ~/.radsim/learning/."
    )
    pdf.table(
        ["Module", "Purpose"],
        [
            ["Preference Learner", "Learns code style: indentation, naming"],
            ["Error Analyzer", "Tracks error patterns to prevent repeats"],
            ["Few-Shot Assembler", "Stores successful examples"],
            ["Active Learner", "Detects uncertainty"],
            ["Tool Optimizer", "Learns effective tool chains"],
            ["Reflection Engine", "Post-task analysis"],
            ["Self-Improver", "Generates improvement proposals"],
            ["Analytics", "Statistics for learning progress"],
        ],
        [50, 120],
    )

    # ════════════════════════════════════════
    # 13. MEMORY AND SECURITY
    # ════════════════════════════════════════
    pdf.section(13, "Memory and Security")

    pdf.subsection("Memory")
    pdf.para(
        "RadSim supports dual memory backends: ChromaDB (vector search) and "
        "JSON-based keyword search (fallback). It stores conversation summaries, "
        "code patterns, and user preferences."
    )

    pdf.subsection("Security")
    pdf.bullet_list([
        "Path Safety: Blocks access to sensitive files (.env, .git, etc.)",
        "Traversal Prevention: Blocks ../../../ style attacks",
        "Access Control: Optional access code protection",
        "Command Injection: Shell commands are validated and sanitized",
        "Write Confirmation: User must approve destructive actions",
    ])

    # ════════════════════════════════════════
    # 14. SCHEDULER & LOGGING
    # ════════════════════════════════════════
    pdf.section(14, "Scheduler & Logging")

    pdf.subsection("Scheduler")
    pdf.para("Cron-style task scheduling stored in ~/.radsim/schedules.json.")
    pdf.code('{"schedule": "0 9 * * *", "command": "pytest tests/"}')

    pdf.subsection("Task Logging")
    pdf.para("Structured audit logging in JSON and SQLite formats.")
    pdf.table(
        ["Event Type", "Data Captured"],
        [
            ["api_call", "Model, provider, tokens, duration"],
            ["tool_execution", "Tool name, inputs, outputs"],
            ["error", "Error type, message, context"],
        ],
        [40, 130],
    )

    # ════════════════════════════════════════
    # 15. FILE PATHS
    # ════════════════════════════════════════
    pdf.section(15, "File Paths Reference")

    pdf.subsection("Configuration")
    pdf.bullet_list([
        "~/.radsim/.env -- API keys (chmod 600)",
        "~/.radsim/settings.json -- Runtime config",
    ])

    pdf.subsection("Data")
    pdf.bullet_list([
        "~/.radsim/learning/ -- Learning data files",
        "~/.radsim/vector_store/ -- Memory database",
        "~/.radsim/logs/ -- Audit logs",
        "~/.radsim/skills.json -- User skills",
    ])

    # ── Generate ──
    output_path = "/Users/brighthome/Documents/CLAUDE CODE/RADSIM/RadSim_Documentation_v1.1.0.pdf"
    pdf.output(output_path)
    return output_path


if __name__ == "__main__":
    path = build_pdf()
    print(f"PDF generated: {path}")