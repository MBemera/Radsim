"""Declarative command metadata for the slash-command registry."""


_HELP_DETAIL_FIELDS = (
    "title",
    "aliases",
    "summary",
    "usage",
    "details",
    "examples",
    "related",
    "tips",
)


def _command(
    names: list[str],
    handler_name: str,
    description: str,
    category: str,
    *,
    accepts_args: bool,
    telegram_safe: bool,
    title: str,
    summary: str,
    usage: list[str],
    details: str,
    examples: list[str],
    related: list[str],
    tips: list[str] | None = None,
    help_aliases: list[str] | None = None,
) -> dict:
    """Build one command record with its provider-visible help details."""
    command = {
        "names": names,
        "handler_name": handler_name,
        "description": description,
        "category": category,
        "accepts_args": accepts_args,
        "telegram_safe": telegram_safe,
        "title": title,
        "aliases": help_aliases if help_aliases is not None else names[1:],
        "summary": summary,
        "usage": usage,
        "details": details,
        "examples": examples,
        "related": related,
    }
    if tips is not None:
        command["tips"] = tips
    return command


def build_help_details(command_specs: list[dict]) -> dict:
    """Build the legacy topic-keyed long-help view from command records."""
    return {
        spec["names"][0].lstrip("/"): {
            field: spec[field] for field in _HELP_DETAIL_FIELDS if field in spec
        }
        for spec in command_specs
    }


DEFAULT_COMMAND_SPECS = [
    _command(["/help", "/h", "/?", "/commands", "/cmds"], "_cmd_help", "Show help and all commands", "navigation",
        accepts_args=True, telegram_safe=True,
        title="Help Menu",
        help_aliases=["/h", "/?"],
        summary="Show the help menu or detailed help for a specific command.",
        usage=["/help", "/help <command>"],
        details="Displays the main help menu with categorized commands.\n"
            "Pass a command name to get detailed help, usage examples, and tips.",
        examples=["/help", "/help skill", "/help plan", "/h complexity"],
        related=["/tools", "/modes"],
        tips=["You can also ask naturally, e.g. 'how do I use skills?'"],
    ),
    _command(["/tools"], "_cmd_tools", "List all available tools", "navigation",
        accepts_args=False, telegram_safe=True,
        title="Available Tools",
        summary="List all available tools the agent can use.",
        usage=["/tools"],
        details="Displays the full list of tools available to RadSim, including\n"
            "file operations, git, shell, search, testing, and more.",
        examples=["/tools"],
        related=["/help"],
    ),
    _command(["/clear", "/c", "/new", "/fresh"], "_cmd_clear", "Clear conversation and start fresh", "conversation",
        accepts_args=False, telegram_safe=True,
        title="Clear Conversation",
        summary="Clear the conversation and start fresh.",
        usage=["/clear", "/new"],
        details="Clears conversation history, the task tracker, and background\n"
            "jobs, and resets rate limiters and budget counters. Learned\n"
            "preferences and skills are kept — use /reset for those.",
        examples=["/clear", "/new"],
        related=["/reset"],
    ),
    _command(["/config", "/provider", "/swap"], "_cmd_config", "Change provider or API key", "provider",
        accepts_args=False, telegram_safe=False,
        title="Provider Configuration",
        summary="Full configuration setup for provider and API key.",
        usage=["/config"],
        details="Re-runs the configuration wizard where you can change your AI\n"
            "provider and enter a new API key. This is the full setup flow —\n"
            "use /switch for a quicker model change.",
        examples=["/config"],
        related=["/switch", "/setup", "/free"],
    ),
    _command(["/switch", "/model"], "_cmd_switch", "Quick switch provider/model", "provider",
        accepts_args=True, telegram_safe=False,
        title="Quick Switch Provider/Model",
        summary="Interactively switch your AI provider and model.",
        usage=["/switch"],
        details="Opens an interactive menu to select a new provider (Claude, GPT-5,\n"
            "Gemini, Vertex AI, OpenRouter) and then pick a model. Requires an\n"
            "API key already configured in your .env file.",
        examples=["/switch", "/model"],
        related=["/config", "/free"],
        tips=["Use /free to instantly switch to the cheapest model."],
    ),
    _command(["/login"], "_cmd_login", "Log in to a provider with an API key", "provider",
        accepts_args=True, telegram_safe=False,
        title="Provider Login",
        summary="Log in to a provider with an API key.",
        usage=["/login", "/login <provider>"],
        details="Configures API credentials from inside RadSim:\n\n"
            "  • (no args)    — Pick a provider from a numbered menu\n"
            "  • <provider>   — Run the API-key wizard for that provider\n\n"
            "After login, RadSim hot-swaps to the newly configured provider.",
        examples=["/login", "/login openrouter", "/login claude"],
        related=["/logout", "/config", "/switch"],
    ),
    _command(["/logout"], "_cmd_logout", "Remove a provider's saved credentials", "provider",
        accepts_args=True, telegram_safe=False,
        title="Provider Logout",
        summary="Remove a provider's saved API key and cached tokens.",
        usage=["/logout", "/logout <provider>"],
        details="Removes the stored API key (and any cached OAuth tokens) for a\n"
            "provider. Pick from a menu or name the provider directly.",
        examples=["/logout", "/logout openai"],
        related=["/login", "/config"],
    ),
    _command(["/free"], "_cmd_free", "Switch to free OpenRouter model", "provider",
        accepts_args=False, telegram_safe=True,
        title="Cheapest Model",
        summary="Instantly switch to the cheapest OpenRouter model.",
        usage=["/free"],
        details="Switches to DeepSeek V4 Flash on OpenRouter ($0.09/$0.18 per 1M tokens).\n"
            "Requires an OPENROUTER_API_KEY in your .env file.",
        examples=["/free"],
        related=["/switch", "/config"],
        tips=["Great for quick tasks where you don't need a top-tier model."],
    ),
    _command(["/ratelimit", "/rl", "/limit"], "_cmd_ratelimit", "Set API call limit per turn", "provider",
        accepts_args=True, telegram_safe=False,
        title="Rate Limit Settings",
        summary="Set API call limit per turn to control agent throughput.",
        usage=["/ratelimit"],
        details="Choose how many API calls the agent can make per turn:\n"
            "  Light (15)     - Conservative, good for simple tasks\n"
            "  Standard (30)  - Balanced, recommended for most work\n"
            "  Heavy (75)     - For complex multi-step tasks\n"
            "  Intensive (100)- For large refactors and deep analysis\n"
            "  Maximum (200)  - Maximum throughput, use with caution\n\n"
            "Setting is saved and persists across sessions.",
        examples=["/ratelimit", "/rl"],
        related=["/switch", "/config", "/settings"],
        tips=["Start with Standard and increase if you hit limits on complex tasks."],
    ),
    _command(["/theme", "/palette"], "_cmd_theme", "Pick UI color palette", "appearance",
        accepts_args=True, telegram_safe=False,
        title="Color Theme",
        summary="Pick the UI color palette.",
        usage=["/theme", "/theme <name>"],
        details="Changes RadSim's terminal color palette. Run without arguments\n"
            "for an interactive picker, or pass a palette name directly.\n"
            "The choice is saved in ~/.radsim/settings.json.",
        examples=["/theme", "/palette"],
        related=["/font", "/animations"],
    ),
    _command(["/font", "/glyphs"], "_cmd_font", "Pick font / glyph profile", "appearance",
        accepts_args=True, telegram_safe=False,
        title="Font / Glyph Profile",
        summary="Pick the glyph profile (Nerd Font, Unicode, ASCII).",
        usage=["/font", "/font <profile>"],
        details="Selects which glyph set RadSim uses for icons and symbols.\n"
            "Pick ASCII if your terminal font shows broken characters.",
        examples=["/font", "/glyphs"],
        related=["/theme", "/animations"],
    ),
    _command(["/animations", "/anim"], "_cmd_animations", "Set animation level", "appearance",
        accepts_args=True, telegram_safe=False,
        title="Animation Level",
        summary="Set the animation level (full, subtle, off).",
        usage=["/animations", "/animations <level>"],
        details="Controls spinners and boot animations:\n\n"
            "  • full   — Animated spinners and boot sequence\n"
            "  • subtle — Static indicators, no motion\n"
            "  • off    — Plain text only",
        examples=["/animations", "/anim off"],
        related=["/theme", "/font"],
    ),
    _command(["/exit", "/quit", "/q"], "_cmd_exit", "Exit RadSim", "session",
        accepts_args=False, telegram_safe=False,
        title="Exit RadSim",
        summary="Quit RadSim gracefully.",
        usage=["/exit", "/quit", "/q"],
        details="Exits RadSim cleanly. You can also type 'exit' or 'quit' without the slash.",
        examples=["/exit", "/quit"],
        related=["/kill"],
    ),
    _command(["/usage", "/cost"], "_cmd_usage", "Show session token usage and estimated cost", "session",
        accepts_args=False, telegram_safe=True,
        title="Session Usage & Cost",
        summary="Show this session's token usage and estimated cost.",
        usage=["/usage"],
        details="Displays input/output token totals for the current session and\n"
            "an estimated cost based on the active model's pricing. Models\n"
            "without pricing data show cost as n/a.",
        examples=["/usage", "/cost"],
        related=["/stats", "/ratelimit"],
    ),
    _command(["/copy", "/cp"], "_cmd_copy", "Copy last response, code, or file to clipboard", "session",
        accepts_args=True, telegram_safe=False,
        title="Copy to Clipboard",
        summary="Copy the last response, code block, or written file.",
        usage=["/copy", "/copy code", "/copy file"],
        details="Copies content to the system clipboard:\n"
            "  • /copy       — the last full response\n"
            "  • /copy code  — the last fenced code block in the response\n"
            "  • /copy file  — the content of the last written file",
        examples=["/copy code"],
        related=["/show", "/export"],
    ),
    _command(["/export"], "_cmd_export", "Export the conversation to a markdown file", "session",
        accepts_args=True, telegram_safe=False,
        title="Export Conversation",
        summary="Save the conversation as a markdown file.",
        usage=["/export", "/export <filename>"],
        details="Writes the conversation to a markdown file in the project\n"
            "directory (default: a timestamped name). Tool calls are noted;\n"
            "tool results and images are omitted to keep the export readable.\n"
            "Existing files are never overwritten.",
        examples=["/export", "/export review-session.md"],
        related=["/copy", "/clear"],
    ),
    _command(["/undo"], "_cmd_undo", "Restore files changed by the last agent edit", "session",
        accepts_args=True, telegram_safe=False,
        title="Undo File Changes",
        summary="Restore files to their state before the last agent edit.",
        usage=["/undo", "/undo list"],
        details="Before the agent writes, edits, renames, patches, or deletes a\n"
            "file, RadSim snapshots it. /undo restores the most recent\n"
            "checkpoint: rewritten files get their old content back, and\n"
            "files that did not exist before are removed.\n\n"
            "Covers write_file, replace_in_file, delete_file, rename_file,\n"
            "multi_edit, and apply_patch. Keeps the last 20 checkpoints per\n"
            "project; files over 5 MB are recorded but not snapshotted.",
        examples=["/undo", "/undo list"],
        related=["/show"],
        tips=["Run /undo repeatedly to step further back."],
    ),
    _command(["/kill", "/stop", "/abort"], "_cmd_kill", "EMERGENCY: Immediately stop agent", "session",
        accepts_args=False, telegram_safe=False,
        title="Emergency Stop",
        summary="EMERGENCY: Immediately terminate the agent.",
        usage=["/kill", "/stop", "/abort"],
        details="Force-kills RadSim immediately. Use when the agent is stuck or\n"
            "doing something unexpected. Prefer /exit for normal shutdown.",
        examples=["/kill", "/stop"],
        related=["/exit"],
        tips=["Only use in emergencies — /exit is safer for normal use."],
    ),
    _command(["/setup", "/onboarding"], "_cmd_setup", "Re-run the setup wizard", "provider",
        accepts_args=False, telegram_safe=False,
        title="Setup Wizard",
        summary="Re-run the initial setup wizard.",
        usage=["/setup", "/onboarding"],
        details="Runs the full onboarding flow again: provider selection, API key\n"
            "entry, and model selection.",
        examples=["/setup"],
        related=["/config", "/switch"],
    ),
    _command(["/good", "/+"], "_cmd_good", "Mark last response as good (positive feedback)", "learning",
        accepts_args=False, telegram_safe=True,
        title="Positive Feedback",
        summary="Mark the last response as good (positive feedback).",
        usage=["/good", "/+"],
        details="Records positive feedback on the last response. RadSim uses this\n"
            "to learn your preferences and improve future responses.",
        examples=["/good", "/+"],
        related=["/improve", "/stats"],
    ),
    _command(["/improve", "/-"], "_cmd_improve", "Mark last response for improvement", "learning",
        accepts_args=False, telegram_safe=True,
        title="Improvement Feedback",
        summary="Mark the last response for improvement (negative feedback).",
        usage=["/improve", "/-"],
        details="Records that the last response could be better. RadSim uses this\n"
            "alongside positive feedback to learn what works and what doesn't.",
        examples=["/improve", "/-"],
        related=["/good", "/stats"],
    ),
    _command(["/stats"], "_cmd_stats", "Learning stats (report|audit|prefs|prompt)", "learning",
        accepts_args=True, telegram_safe=True,
        title="Learning Statistics",
        summary="Show learning statistics and deeper learning views.",
        usage=["/stats", "/stats report", "/stats audit", "/stats prefs", "/stats prompt"],
        details="Bare /stats shows key learning metrics: tasks completed, success\n"
            "rate, errors tracked, feedback received, and tools tracked.\n\n"
            "Subactions:\n"
            "  report — export the full-text learning report\n"
            "  audit  — audit every learned preference\n"
            "  prefs  — show learned code style preferences\n"
            "  prompt — show system prompt size by layer",
        examples=["/stats", "/stats prefs", "/stats prompt"],
        related=["/reset", "/skill"],
    ),
    _command(["/reset"], "_cmd_reset", "Reset learned data (usage: /reset <category>)", "learning",
        accepts_args=True, telegram_safe=False,
        title="Reset Learning Data",
        summary="Reset a category of learned data or the token budget.",
        usage=["/reset", "/reset <category>"],
        details="Reset specific learning categories:\n\n"
            "  • budget       — Reset token budget counters\n"
            "  • preferences  — Reset learned code style\n"
            "  • errors       — Reset error patterns\n"
            "  • examples     — Reset few-shot examples\n"
            "  • tools        — Reset tool effectiveness data\n"
            "  • reflections  — Reset task reflections\n"
            "  • all          — Reset everything",
        examples=["/reset budget", "/reset preferences", "/reset all"],
        related=["/stats"],
    ),
    _command(["/trust"], "_cmd_trust", "View or reset learned confirmation trust", "learning",
        accepts_args=True, telegram_safe=False,
        title="Confirmation Trust",
        summary="View or reset learned confirmation trust.",
        usage=["/trust", "/trust reset [tool]", "/trust low", "/trust medium"],
        details="RadSim learns which safe actions you routinely approve and can\n"
            "auto-confirm them (trust bandit). This command shows what has\n"
            "been learned, adjusts the trust threshold, or resets it.",
        examples=["/trust", "/trust reset", "/trust reset write_file"],
        related=["/settings", "/stats"],
    ),
    _command(["/skill", "/skills"], "_cmd_skill", "Configure custom skills/instructions", "customization",
        accepts_args=True, telegram_safe=False,
        title="Custom Skills & Instructions",
        summary="Add, list, remove, or import custom instructions.",
        usage=[
            "/skill",
            "/skill add <instruction>",
            "/skill list",
            "/skill remove <n>",
            "/skill templates",
            "/skill learn <file>",
            "/skill clear",
        ],
        details="Skills are persistent custom instructions that shape how RadSim\n"
            "responds. They survive across conversations.\n\n"
            "  • add       — Add a new instruction (e.g. 'Always use TypeScript')\n"
            "  • list      — Show all active skills\n"
            "  • remove    — Remove a skill by number\n"
            "  • templates — Show example skills to get started\n"
            "  • learn     — Import skills from a file\n"
            "  • clear     — Remove all skills",
        examples=[
            "/skill add Always use TypeScript instead of JavaScript",
            "/skill list",
            "/skill remove 2",
            "/skill templates",
        ],
        related=["/stats", "/settings"],
        tips=[
            "Skills are stored in ~/.radsim/skills.json",
            "Use /skill templates for inspiration",
        ],
    ),
    _command(["/hook", "/hooks"], "_cmd_hook", "Create and manage lifecycle hooks", "customization",
        accepts_args=True, telegram_safe=False,
        title="Lifecycle Hooks",
        summary="Run your own shell commands on agent events.",
        usage=[
            "/hook            (interactive menu)",
            "/hook list",
            "/hook add",
            "/hook toggle     (arrow-key on/off switches)",
            "/hook remove     (pick from a list)",
            "/hook add <name> <event> <matcher> <command...>",
        ],
        details="Hooks run a shell command when an agent event fires. Events:\n"
            "pre_tool, post_tool, session_start, session_end, on_error.\n"
            "The matcher is a glob against the tool name (git_*, *, ...);\n"
            "session hooks always fire.\n\n"
            "Every action works without arguments: bare /hook opens a menu,\n"
            "and remove/on/off show a picker of your hooks.\n\n"
            "Each hook receives a JSON payload on stdin. A pre_tool hook\n"
            "that exits with code 2 BLOCKS the tool call and its stderr is\n"
            "shown as the reason. Hooks can only block actions — they can\n"
            "never approve, skip a confirmation, or bypass validation.\n"
            "A pre_tool hook that fails to run blocks the call (fail closed).",
        examples=[
            "/hook add test-gate pre_tool git_push pytest -q",
            "/hook add lint-after post_tool write_file ruff check .",
            "/hook off lint-after",
        ],
        related=["/skill", "/settings"],
        tips=[
            "Hooks are stored in ~/.radsim/hooks.json (max 20).",
            "The command is everything after the matcher — no quotes needed.",
        ],
    ),
    _command(["/memory", "/mem"], "_cmd_memory", "Manage persistent memory", "memory",
        accepts_args=True, telegram_safe=False,
        title="Persistent Memory",
        summary="Save, recall, and manage persistent memory entries.",
        usage=["/memory", "/memory remember <text>", "/memory forget <n>", "/memory list"],
        details="Memory lets RadSim remember facts across conversations.\n\n"
            "  • remember — Save a piece of information\n"
            "  • forget   — Remove a memory by number\n"
            "  • list     — Show all stored memories",
        examples=[
            "/memory remember My project uses PostgreSQL 16",
            "/memory list",
            "/memory forget 3",
        ],
        related=["/skill", "/stats"],
    ),
    _command(["/teach", "/t"], "_cmd_teach", "Toggle Teach Me mode (explains while coding)", "modes",
        accepts_args=False, telegram_safe=True,
        title="Teach Me Mode",
        summary="Toggle teach mode — adds explanations to every response.",
        usage=["/teach", "/t"],
        details="When teach mode is ON, RadSim adds [teach] inline annotations explaining\n"
            "what each piece of code does and why. Great for learning new\n"
            "languages, frameworks, or understanding unfamiliar codebases.\n\n"
            "Annotations appear in magenta and are automatically stripped\n"
            "from files written to disk.",
        examples=["/teach", "/t"],
        related=["/modes", "/show"],
        tips=[
            "Press T as a hotkey to toggle teach mode quickly",
            "Annotations are stripped from saved files automatically",
        ],
    ),
    _command(["/modes"], "_cmd_modes", "List all available modes", "modes",
        accepts_args=False, telegram_safe=True,
        title="Available Modes",
        summary="List all available mode toggles.",
        usage=["/modes"],
        details="Shows all modes (teach, awake, etc.) and their current on/off status.",
        examples=["/modes"],
        related=["/teach", "/awake"],
    ),
    _command(["/awake", "/caffeinate"], "_cmd_awake", "Toggle stay-awake mode (macOS)", "modes",
        accepts_args=False, telegram_safe=True,
        title="Stay-Awake Mode",
        summary="Toggle stay-awake mode (prevents macOS sleep).",
        usage=["/awake", "/caffeinate"],
        details="Uses macOS 'caffeinate' to prevent the system from sleeping.\n"
            "Useful during long-running tasks. Toggle off when done.",
        examples=["/awake", "/caffeinate"],
        related=["/modes"],
    ),
    _command(["/show"], "_cmd_show", "Show last written file content", "modes",
        accepts_args=True, telegram_safe=True,
        title="Show Last Written File",
        summary="Display the content of the last file written by the agent.",
        usage=["/show", "/show all"],
        details="Shows the last file RadSim wrote, with line numbers. In teach\n"
            "mode, annotations are highlighted in magenta.\n\n"
            "  • (no args) — Show last written file\n"
            "  • all       — Show all files written this session",
        examples=["/show", "/show all"],
        related=["/teach"],
        tips=["Press S during a write confirmation to preview code."],
    ),
    _command(["/selfmod", "/self"], "_cmd_selfmod", "View/edit RadSim source and custom prompt", "customization",
        accepts_args=True, telegram_safe=False,
        title="Self-Modification",
        summary="View or edit RadSim source code and custom prompt.",
        usage=["/selfmod", "/selfmod path", "/selfmod prompt", "/selfmod list"],
        details="Access RadSim's own source code:\n\n"
            "  • path   — Show the RadSim source directory\n"
            "  • prompt — View/edit the custom system prompt\n"
            "  • list   — List all source files",
        examples=["/selfmod path", "/selfmod prompt", "/self list"],
        related=["/evolve", "/settings"],
    ),
    _command(["/telegram", "/tg"], "_cmd_telegram", "Configure Telegram notifications", "integrations",
        accepts_args=True, telegram_safe=False,
        title="Telegram Notifications",
        summary="Configure Telegram bot for notifications and remote control.",
        usage=[
            "/telegram",
            "/telegram setup",
            "/telegram listen",
            "/telegram test",
            "/telegram send <msg>",
            "/telegram status",
        ],
        details="Connect RadSim to a Telegram bot for:\n\n"
            "  • setup   — Configure bot token and chat ID\n"
            "  • listen  — Toggle receiving messages from Telegram\n"
            "  • test    — Send a test message\n"
            "  • send    — Send a custom message\n"
            "  • status  — Check current configuration",
        examples=["/telegram setup", "/tg test", "/telegram send Task done!"],
        related=["/settings"],
    ),
    _command(["/settings", "/set"], "_cmd_settings", "View/change agent settings", "configuration",
        accepts_args=True, telegram_safe=False,
        title="Agent Settings",
        summary="View or change agent configuration parameters.",
        usage=["/settings", "/settings <key> <value>", "/settings security_level <level>"],
        details="Manage RadSim's internal settings:\n\n"
            "  • (no args)          — Interactive menu\n"
            "  • <key>              — View a single setting\n"
            "  • <key> <value>      — Change a setting\n"
            "  • security_level     — Set preset (strict/balanced/permissive)",
        examples=[
            "/settings",
            "/settings security_level strict",
            "/set self_improvement.enabled true",
        ],
        related=["/evolve", "/config"],
    ),
    _command(["/evolve", "/self-improve"], "_cmd_evolve", "Control learning, proposals, and extensions", "learning",
        accepts_args=True, telegram_safe=False,
        title="Evolve Controls",
        summary="Control verified learning, proposals, and reviewed Python extensions.",
        usage=[
            "/evolve",
            "/evolve status",
            "/evolve on|off",
            "/evolve auto on|off",
            "/evolve learning on|off",
            "/evolve extensions on|off",
            "/evolve settings",
            "/evolve analyze|review|history|stats",
        ],
        details="Use one command surface for evolution-related settings:\n\n"
            "  • status              - Show every current state\n"
            "  • on / off            - Toggle the proposal engine\n"
            "  • auto on / off       - Toggle automatic proposals\n"
            "  • learning on / off   - Toggle learning collection\n"
            "  • extensions on / off - Toggle reviewed local extensions\n"
            "  • settings            - Configure individual learning modules\n"
            "  • analyze             - Create proposals from verified outcomes\n"
            "  • review              - Explicitly approve or reject proposals\n"
            "  • history / stats     - Inspect retained learning data",
        examples=[
            "/evolve status",
            "/evolve on",
            "/evolve learning off",
            "/evolve analyze",
        ],
        related=["/settings", "/selfmod"],
        tips=[
            "Proposal analysis and self-extension are disabled by default.",
            "Generated Python always requires explicit approval.",
        ],
    ),
    _command(["/complexity", "/cx"], "_cmd_complexity", "Complexity budget & scoring", "analysis",
        accepts_args=True, telegram_safe=False,
        title="Complexity Budget & Scoring",
        summary="Analyze and manage code complexity.",
        usage=[
            "/complexity",
            "/complexity budget <N>",
            "/complexity analyze <file>",
            "/complexity report",
        ],
        details="The complexity system scores code and enforces budgets:\n\n"
            "  • (no args) — Interactive menu\n"
            "  • budget N  — Set max complexity budget\n"
            "  • analyze   — Score a specific file\n"
            "  • report    — Full project complexity report",
        examples=["/complexity", "/cx budget 50", "/complexity analyze src/auth.py"],
        related=["/stress", "/archaeology"],
    ),
    _command(["/stress", "/adversarial"], "_cmd_stress", "Adversarial code review", "analysis",
        accepts_args=True, telegram_safe=False,
        title="Adversarial Code Review",
        summary="Run adversarial stress testing on your code.",
        usage=["/stress", "/stress <file>"],
        details="Stress testing tries to break your code by finding edge cases,\n"
            "security vulnerabilities, performance issues, and logic errors.\n"
            "Can target a specific file or run on the whole project.",
        examples=["/stress", "/stress src/api/routes.py"],
        related=["/complexity", "/archaeology"],
    ),
    _command(["/archaeology", "/arch", "/dead"], "_cmd_archaeology", "Find dead code & zombies", "analysis",
        accepts_args=True, telegram_safe=False,
        title="Dead Code Archaeology",
        summary="Find dead code, zombie functions, and unused imports.",
        usage=["/archaeology", "/archaeology clean"],
        details="Scans your project for:\n\n"
            "  • Unused imports\n"
            "  • Dead functions never called\n"
            "  • Zombie code (commented out blocks)\n"
            "  • Unreachable code paths\n\n"
            "Use 'clean' for interactive cleanup.",
        examples=["/archaeology", "/arch clean"],
        related=["/complexity", "/stress"],
    ),
    _command(["/plan", "/p"], "_cmd_plan", "Structured plan-confirm-execute workflow", "planning",
        accepts_args=True, telegram_safe=False,
        title="Plan Mode",
        summary="Structured plan → confirm → execute workflow.",
        usage=["/plan", "/plan <task description>"],
        details="Plan mode breaks complex tasks into steps:\n\n"
            "  1. You describe the task\n"
            "  2. RadSim generates a structured plan\n"
            "  3. You review and approve (or edit)\n"
            "  4. RadSim executes the approved plan step by step\n\n"
            "This gives you full control over multi-step operations.",
        examples=[
            "/plan refactor the auth module to use JWT tokens",
            "/plan add dark mode to the settings page",
            "/p",
        ],
        related=["/panning", "/complexity"],
        tips=["Use /plan for tasks with multiple files or risky changes."],
    ),
    _command(["/panning", "/pan"], "_cmd_panning", "Brain-dump processing & synthesis", "planning",
        accepts_args=True, telegram_safe=False,
        title="Brain-Dump Processing",
        summary="Process messy brain-dumps into structured synthesis.",
        usage=["/panning", "/panning <brain dump text>"],
        details="Panning mode takes unstructured thoughts, ideas, or notes and\n"
            "synthesizes them into a structured, actionable output. Great for:\n\n"
            "  • Converting rough notes into a spec\n"
            "  • Organizing scattered requirements\n"
            "  • Turning brainstorms into action items",
        examples=[
            "/panning I need auth, maybe OAuth, also user profiles, and...",
            "/pan",
        ],
        related=["/plan"],
    ),
    _command(["/background", "/bg"], "_cmd_background", "View/manage background sub-agent jobs", "background",
        accepts_args=True, telegram_safe=True,
        title="Background Jobs",
        summary="View and manage background sub-agent jobs.",
        usage=["/background", "/bg", "/bg<N>"],
        details="Lists background sub-agent jobs with status and runtime.\n"
            "Use /bg<N> (e.g. /bg2) to view the result of job N.\n"
            "Job results are also injected into the conversation when done.",
        examples=["/background", "/bg1"],
        related=["/job"],
    ),
    _command(["/job", "/jobs", "/cron"], "_cmd_job", "Manage scheduled cron jobs", "background",
        accepts_args=True, telegram_safe=False,
        title="Scheduled Jobs",
        summary="Manage scheduled cron jobs.",
        usage=[
            "/job",
            "/job add",
            "/job remove   (pick from a list)",
            "/job pause    (pick from a list)",
            "/job resume   (pick from a list)",
            "/job run      (pick from a list)",
        ],
        details="Schedules recurring commands (cron-style). Every action works\n"
            "without an id — you get a picker of your jobs:\n\n"
            "  • (no args)   — List all scheduled jobs\n"
            "  • add         — Create a new scheduled job\n"
            "  • remove      — Delete a job\n"
            "  • pause/resume— Toggle a job without deleting it\n"
            "  • run         — Run a job immediately\n\n"
            "Jobs the agent schedules for you (via the schedule_task tool)\n"
            "show up here too — they share one store.",
        examples=["/job", "/job add", "/job run"],
        related=["/background", "/telegram"],
    ),
    _command(["/mcp"], "_cmd_mcp", "Manage MCP server connections", "integrations",
        accepts_args=True, telegram_safe=False,
        title="MCP Server Connections",
        summary="Manage MCP (Model Context Protocol) server connections.",
        usage=["/mcp", "/mcp status", "/mcp list", "/mcp add", "/mcp connect <name>",
                  "/mcp disconnect <name>", "/mcp remove <name>"],
        details="Connect to external MCP servers to extend RadSim with additional tools.\n"
            "MCP is the same protocol used by Claude Desktop, Cursor, and other tools.\n\n"
            "Subcommands:\n"
            "  status     - Show all servers and connection state (default)\n"
            "  list       - Show all tools from connected servers\n"
            "  add        - Interactively add a new server\n"
            "  connect    - Connect to a configured server\n"
            "  disconnect - Disconnect from a server\n"
            "  remove     - Remove a server configuration\n\n"
            "Config file: ~/.radsim/mcp.json\n"
            "Supports: stdio, SSE, and Streamable HTTP transports.\n"
            "Install MCP SDK: pip install radsimcli[mcp]",
        examples=["/mcp", "/mcp add", "/mcp connect filesystem", "/mcp list"],
        related=["/tools", "/config"],
        tips=[
            "MCP tools appear alongside native tools in /tools output.",
            "All MCP tools require confirmation unless auto_confirm is enabled.",
            "Set autoConnect: true in config to connect on startup.",
        ],
    ),
]


TELEGRAM_SAFE_COMMANDS = {
    spec["names"][0]: spec["description"]
    for spec in DEFAULT_COMMAND_SPECS
    if spec["telegram_safe"]
}


COMMAND_HINTS = {
    "model": [
        ("/switch", "Quick switch model"),
        ("/config", "Full configuration"),
        ("/free", "Use free model"),
    ],
    "error": [
        ("/clear", "Clear and retry"),
        ("/clear", "Fresh start"),
    ],
    "slow": [
        ("/switch", "Try faster model"),
        ("/free", "Use free model"),
    ],
    "feedback": [
        ("/good", "Mark as good"),
        ("/improve", "Mark for improvement"),
    ],
    "help": [
        ("/help", "Full help"),
        ("/tools", "Available tools"),
        ("/help", "All commands"),
    ],
    "code": [
        ("/skill add", "Add coding preference"),
        ("/stats prefs", "See learned style"),
        ("/complexity", "Check complexity budget"),
        ("/stress", "Adversarial review"),
        ("/archaeology", "Find dead code"),
    ],
    "planning": [
        ("/plan", "Create/manage plans"),
        ("/panning", "Brain-dump processing"),
    ],
}
