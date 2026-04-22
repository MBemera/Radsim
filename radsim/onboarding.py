"""Onboarding flow for first-time RadSim users.

Guides users through:
1. Welcome and introduction
2. Provider and model selection
3. API key configuration
4. Initial settings
5. Quick tutorial
"""

import json
import logging
import os
import sys
import time

from .config import (
    CONFIG_DIR,
    ENV_FILE,
    PROVIDER_MODELS,
    PROVIDER_URLS,
    SETTINGS_FILE,
    load_env_file,
    save_config,
)

logger = logging.getLogger(__name__)

ONBOARDING_FILE = CONFIG_DIR / "onboarding_complete.json"
TERMS_ACCEPTED_FILE = CONFIG_DIR / "terms_accepted.json"


def has_accepted_terms() -> bool:
    """Check if user has accepted the Terms & Conditions."""
    return TERMS_ACCEPTED_FILE.exists()


def mark_terms_accepted(user_name: str = ""):
    """Record that the user accepted the Terms & Conditions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "accepted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "user_name": user_name,
        "license": "MIT",
    }
    TERMS_ACCEPTED_FILE.write_text(json.dumps(data, indent=2))


def has_completed_onboarding() -> bool:
    """Check if user has completed onboarding."""
    return ONBOARDING_FILE.exists()


def mark_onboarding_complete(user_name: str = None):
    """Mark onboarding as complete."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "user_name": user_name,
    }
    ONBOARDING_FILE.write_text(json.dumps(data, indent=2))


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def pause(message: str = "Press Enter to continue..."):
    """Pause and wait for user input."""
    try:
        input(f"\n  {message}")
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)


def print_header(title: str):
    """Print a styled header."""
    width = 50
    print()
    print("  ╭" + "─" * width + "╮")
    print("  │" + title.center(width) + "│")
    print("  ╰" + "─" * width + "╯")
    print()


def print_box(lines: list, title: str = None):
    """Print text in a box."""
    width = max(len(line) for line in lines) + 4
    width = max(width, 50)

    print()
    if title:
        print(f"  ┌─ {title} " + "─" * (width - len(title) - 4) + "┐")
    else:
        print("  ┌" + "─" * width + "┐")

    for line in lines:
        padding = width - len(line) - 2
        print(f"  │ {line}" + " " * padding + "│")

    print("  └" + "─" * width + "┘")
    print()


def step_terms_and_conditions() -> bool:
    """Show Terms & Conditions and require acceptance.

    Returns:
        True if accepted, False if declined.
    """
    clear_screen()
    print_header("Terms & Conditions")

    print("  Before using RadSim, you must review and accept the following terms.")
    print()

    print_box(
        [
            "RadSim - MIT License",
            "Copyright (c) 2024-2026 Matthew Bright",
        ],
        title="LICENSE",
    )

    print("  Key Terms:")
    print()
    print("  1. MIT LICENSE")
    print("     RadSim is free and open source. You may use, copy, modify,")
    print("     merge, publish, distribute, sublicense, and/or sell copies")
    print("     of RadSim subject to the MIT License terms.")
    print()
    print("  2. NO WARRANTY")
    print("     RadSim is provided \"AS IS\" without any warranty.")
    print("     The author is not liable for any damages arising from use.")
    print()
    print("  3. AI-GENERATED CODE WARNING")
    print("     RadSim generates code using AI models. You are solely")
    print("     responsible for reviewing, testing, and validating ALL")
    print("     generated code before use in any environment.")
    print()
    print("  4. FILE SYSTEM OPERATIONS")
    print("     RadSim reads, writes, and deletes files on your system.")
    print("     You are responsible for maintaining backups.")
    print()
    print("  5. ASSUMPTION OF RISK")
    print("     By accepting, you acknowledge you understand the risks")
    print("     of AI-powered code generation and file manipulation.")
    print()
    print("  Full details: LICENSE, DISCLAIMER.md, and NOTICE files.")
    print()

    print("  ─────────────────────────────────────────────────────")
    print()

    while True:
        try:
            response = input(
                "  Do you accept the Terms & Conditions? (yes/no): "
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n  Setup cancelled.")
            return False

        if response in ("yes", "y"):
            print()
            print("  ok Terms & Conditions accepted.")
            return True

        if response in ("no", "n"):
            print()
            print("  You must accept the Terms & Conditions to use RadSim.")
            print("  Exiting.")
            return False

        print("  Please type 'yes' or 'no'.")


def step_welcome() -> str:
    """Step 1: Welcome screen and get user's name."""
    clear_screen()

    print()
    print("  ██████╗  █████╗ ██████╗ ███████╗██╗███╗   ███╗")
    print("  ██╔══██╗██╔══██╗██╔══██╗██╔════╝██║████╗ ████║")
    print("  ██████╔╝███████║██║  ██║███████╗██║██╔████╔██║")
    print("  ██╔══██╗██╔══██║██║  ██║╚════██║██║██║╚██╔╝██║")
    print("  ██║  ██║██║  ██║██████╔╝███████║██║██║ ╚═╝ ██║")
    print("  ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝")
    print()
    print("  ─────────────────────────────────────────────────")
    print("           Radically Simple Code Generator")
    print("  ─────────────────────────────────────────────────")
    print()

    print("  Welcome! I'm RadSim, your AI coding assistant.")
    print()
    print("  I can help you:")
    print("    • Write and edit code in any language")
    print("    • Search and navigate your codebase")
    print("    • Run shell commands and tests")
    print("    • Manage git operations")
    print("    • Fetch documentation from the web")
    print()

    try:
        name = input("  What should I call you? ").strip()
        if not name:
            name = "Developer"
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    print()
    print(f"  Nice to meet you, {name}! Let's get you set up.")
    pause()

    return name


def step_user_profile(user_name: str):
    """Gather user profile information for personalization."""
    from .memory import save_memory

    clear_screen()
    print_header("Tell Me About Yourself")

    print(f"  {user_name}, a few quick questions so I can tailor my help to you.")
    print("  (All answers are optional — just press Enter to skip any question.)")
    print()

    # Question 1: Main focus area
    print("  1. What's your main development focus?")
    print()
    print("     1) Web development (frontend/fullstack)")
    print("     2) Data science / ML / AI")
    print("     3) Backend / APIs")
    print("     4) DevOps / Automation / scripting")
    print("     5) Other")
    print()

    focus_map = {
        "1": "web development",
        "2": "data science / ML",
        "3": "backend / APIs",
        "4": "devops / automation",
        "5": "other",
    }

    try:
        focus_choice = input("  Enter 1-5 [skip]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    focus = focus_map.get(focus_choice, "")
    if focus:
        save_memory("development_focus", focus, memory_type="preference")

    # Question 2: Experience level
    print()
    print("  2. What's your experience level with coding?")
    print()
    print("     1) Beginner    — learning as I go")
    print("     2) Intermediate — comfortable building projects")
    print("     3) Advanced    — senior / architect level")
    print()

    level_map = {
        "1": "beginner",
        "2": "intermediate",
        "3": "advanced",
    }

    try:
        level_choice = input("  Enter 1-3 [skip]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    level = level_map.get(level_choice, "")
    if level:
        save_memory("experience_level", level, memory_type="preference")

    # Question 3: Languages
    print()
    print("  3. What languages do you mostly work in?")
    print("     (comma-separated, e.g. Python, JavaScript, TypeScript)")
    print()

    try:
        languages = input("  Languages [skip]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    if languages:
        save_memory("languages", languages, memory_type="preference")

    # Question 4: Response style
    print()
    print("  4. How do you prefer RadSim to respond?")
    print()
    print("     1) Concise  — just the code, minimal explanation")
    print("     2) Balanced — code with brief context")
    print("     3) Detailed — explain what and why")
    print()

    style_map = {
        "1": "concise",
        "2": "balanced",
        "3": "detailed",
    }

    try:
        style_choice = input("  Enter 1-3 [skip]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    style = style_map.get(style_choice, "")
    if style:
        save_memory("response_style", style, memory_type="preference")

    # Question 5: Dev environment / OS
    print()
    print("  5. What's your primary development environment?")
    print()
    print("     1) macOS")
    print("     2) Linux")
    print("     3) Windows (WSL)")
    print("     4) Windows (native)")
    print("     5) Cloud IDE (Codespaces, Gitpod, etc.)")
    print()

    env_map = {
        "1": "macOS",
        "2": "Linux",
        "3": "Windows (WSL)",
        "4": "Windows (native)",
        "5": "Cloud IDE",
    }

    try:
        env_choice = input("  Enter 1-5 [skip]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    env = env_map.get(env_choice, "")
    if env:
        save_memory("dev_environment", env, memory_type="preference")

    # Question 6: Testing approach
    print()
    print("  6. How do you approach testing?")
    print()
    print("     1) I don't write tests yet")
    print("     2) Light testing (happy path only)")
    print("     3) Thorough testing (unit + integration)")
    print("     4) TDD (test-driven development)")
    print()

    test_map = {
        "1": "no tests yet",
        "2": "light testing",
        "3": "thorough testing",
        "4": "TDD",
    }

    try:
        test_choice = input("  Enter 1-4 [skip]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    test = test_map.get(test_choice, "")
    if test:
        save_memory("testing_approach", test, memory_type="preference")

    # Question 7: Current project (optional)
    print()
    print("  7. What are you building right now? (optional)")
    print("     (e.g. a SaaS app, automation scripts, ML pipeline)")
    print()

    try:
        project = input("  Current project [skip]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    if project:
        save_memory("current_project", project, memory_type="preference")

    # Summary
    answered = sum(1 for x in [focus, level, languages, style, env, test, project] if x)
    print()
    if answered > 0:
        print(f"  Profile saved! ({answered} preference{'s' if answered != 1 else ''} recorded)")
    else:
        print("  No worries! You can update preferences anytime with /memory.")
    pause()


def step_provider_intro():
    """Step 2: Explain providers."""
    clear_screen()
    print_header("Step 1 of 6: Choose Your AI Provider")

    print("  RadSim works with multiple AI providers.")
    print("  Each has different strengths and pricing:")
    print()

    providers = [
        ("Claude (Anthropic)", "Great for coding, reasoning, safety", "$3-15/M tokens"),
        ("GPT-5 (OpenAI)", "Versatile, multimodal, fast", "$1-15/M tokens"),
        ("Gemini (Google)", "Huge context, good for docs", "$0.10-5/M tokens"),
        ("Vertex AI (Google Cloud)", "GCP-hosted Gemini + Claude models", "$0.80-15/M tokens"),
        ("OpenRouter", "Recommended - multiple models, cheapest", "$0.14-0.50/M tokens"),
    ]

    for name, desc, price in providers:
        print(f"  • {name}")
        print(f"    {desc}")
        print(f"    Pricing: {price}")
        print()

    pause()


def step_select_provider() -> tuple:
    """Step 3: Select provider and model."""
    clear_screen()
    print_header("Step 2 of 6: Select Provider & Model")

    print("  Choose your preferred AI provider:")
    print()
    print("    1. Claude (Anthropic)       - Best for coding")
    print("    2. GPT-5 (OpenAI)           - Versatile & fast")
    print("    3. Gemini (Google)           - Large context window")
    print("    4. Vertex AI (Google Cloud)  - GCP-hosted models")
    print("    5. OpenRouter               - Recommended (cheapest, most models)")
    print()

    provider_map = {
        "1": "claude",
        "2": "openai",
        "3": "gemini",
        "4": "vertex",
        "5": "openrouter",
    }

    while True:
        try:
            choice = input("  Enter 1-5 [5]: ").strip() or "5"
        except (KeyboardInterrupt, EOFError):
            print("\n  Setup cancelled.")
            sys.exit(0)

        provider = provider_map.get(choice)
        if provider:
            break
        print("  Invalid choice. Please enter 1-5.")

    # Select model
    print()
    print(f"  Great! Now choose a {provider.title()} model:")
    print()

    models = PROVIDER_MODELS[provider]
    for i, (_model_id, model_name) in enumerate(models, 1):
        print(f"    {i}. {model_name}")
    print()

    while True:
        try:
            model_choice = input(f"  Enter 1-{len(models)} [1]: ").strip() or "1"
        except (KeyboardInterrupt, EOFError):
            print("\n  Setup cancelled.")
            sys.exit(0)

        try:
            model_index = int(model_choice) - 1
            if 0 <= model_index < len(models):
                model = models[model_index][0]
                model_name = models[model_index][1]
                break
        except ValueError:
            logger.debug("Non-numeric model choice entered during onboarding")
        print(f"  Invalid choice. Please enter 1-{len(models)}.")

    print()
    print(f"  ok Selected: {provider.title()} / {model_name}")
    pause()

    return provider, model


def step_api_key(provider: str) -> str:
    """Step 4: Configure API key (or project ID for Vertex AI)."""
    from .config import PROVIDER_ENV_VARS

    clear_screen()
    print_header("Step 3 of 6: API Key Setup")

    provider_url = PROVIDER_URLS[provider]

    # Vertex AI uses project ID + location instead of an API key
    if provider == "vertex":
        # Check if project ID already exists
        existing_project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not existing_project:
            env_config = load_env_file()
            existing_project = env_config.get("keys", {}).get("GOOGLE_CLOUD_PROJECT")

        if existing_project and not existing_project.lower().startswith("paste_your"):
            print(f"  ok Found existing GOOGLE_CLOUD_PROJECT: {existing_project}")
            print()
            print("  Your Vertex AI project is already configured!")
            location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
            if not location:
                env_config = env_config if "env_config" in dir() else load_env_file()
                location = env_config.get("keys", {}).get(
                    "GOOGLE_CLOUD_LOCATION", "us-central1"
                )
            pause()
            return f"{existing_project}:{location}"

        print("  Vertex AI uses your Google Cloud project credentials.")
        print()
        print("  Prerequisites:")
        print(f"  1. A GCP project with Vertex AI enabled: {provider_url}")
        print("  2. Application Default Credentials (run: gcloud auth application-default login)")
        print()
        print("  [api key] Enter your GCP project details:")
        print()

        try:
            project_id = input("  Google Cloud Project ID (or press Enter to skip): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Setup cancelled.")
            sys.exit(0)

        if not project_id:
            print()
            print("  No problem! You can add it later:")
            print(f"  1. Open: {ENV_FILE}")
            print('  2. Add: GOOGLE_CLOUD_PROJECT="your-project-id"')
            print('         GOOGLE_CLOUD_LOCATION="us-central1"')
            print()
            print("  Then run 'radsim' again.")
            pause()
            return None

        try:
            location = (
                input("  GCP Location [us-central1]: ").strip() or "us-central1"
            )
        except (KeyboardInterrupt, EOFError):
            print("\n  Setup cancelled.")
            sys.exit(0)

        # Save project config securely
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        env_config = load_env_file()
        existing_keys = env_config.get("keys", {})
        existing_keys["GOOGLE_CLOUD_PROJECT"] = project_id
        existing_keys["GOOGLE_CLOUD_LOCATION"] = location

        lines = [
            "# RadSim Configuration",
            "# This file is chmod 600 (secure)",
            "",
            f'RADSIM_PROVIDER="{provider}"',
            "",
            "# API Keys & Credentials",
        ]

        for key_name, key_value in existing_keys.items():
            if key_value and not key_value.lower().startswith("paste_your"):
                lines.append(f'{key_name}="{key_value}"')

        lines.append("")
        ENV_FILE.write_text("\n".join(lines))
        ENV_FILE.chmod(0o600)

        print()
        print("  ok Vertex AI config saved securely to ~/.radsim/.env")
        pause()
        return f"{project_id}:{location}"

    # Standard API key flow for non-Vertex providers
    env_var_name = PROVIDER_ENV_VARS.get(provider, "RADSIM_API_KEY")

    # Check if key already exists
    existing_key = os.getenv(env_var_name)
    if not existing_key:
        env_config = load_env_file()
        existing_key = env_config.get("keys", {}).get(env_var_name)

    if existing_key and not existing_key.lower().startswith("paste_your"):
        print(f"  ok Found existing {env_var_name}")
        print()
        print("  Your API key is already configured!")
        pause()
        return existing_key

    # Need to set up API key
    print("  To use RadSim, you need an API key from your provider.")
    print()
    print(f"  1. Go to: {provider_url}")
    print("  2. Create a new API key")
    print("  3. Copy the key")
    print()
    print("  [api key] For security, you have three options:")
    print()
    print("  Option A: Paste your key now (stored securely in ~/.radsim/.env)")
    print("  Option B: Create a blank .env file (you fill in the key yourself)")
    print("  Option C: Skip for now (add key manually later)")
    print()

    try:
        choice = input("  Enter choice (a/b/c) [a]: ").strip().lower() or "a"
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    if choice == "b":
        # Option B: Create blank .env with placeholder
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Load existing keys to preserve them
        env_config = load_env_file()
        existing_keys = env_config.get("keys", {})

        lines = [
            "# RadSim Configuration",
            "# This file is chmod 600 (secure)",
            "#",
            "# Add your API key below and run 'radsim' again.",
            f"# Get your key from: {provider_url}",
            "",
            f'RADSIM_PROVIDER="{provider}"',
            "",
            "# Paste your API key between the quotes below:",
            f'{env_var_name}=""',
            "",
        ]

        # Preserve any existing keys from other providers
        for key_name, key_value in existing_keys.items():
            if (
                key_name != env_var_name
                and key_value
                and not key_value.lower().startswith("paste_your")
            ):
                lines.append(f'{key_name}="{key_value}"')

        lines.append("")
        ENV_FILE.write_text("\n".join(lines))
        ENV_FILE.chmod(0o600)  # Secure permissions

        print()
        print("  ok Blank .env file created at:")
        print(f"    {ENV_FILE}")
        print()
        print("  Next steps:")
        print(f'  1. Open {ENV_FILE} in your text editor')
        print(f'  2. Paste your API key between the quotes on the {env_var_name} line')
        print("  3. Save the file and run 'radsim' again")
        pause()
        return None

    elif choice == "a" or (choice != "c" and len(choice) >= 20):
        # Option A: Paste key directly
        # If they typed something long, treat it as an API key
        if choice == "a":
            print()
            try:
                api_key_input = input("  Paste your API key: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n  Setup cancelled.")
                sys.exit(0)
        else:
            # They typed the key directly instead of selecting an option
            api_key_input = choice

        if not api_key_input:
            print()
            print("  No key entered. You can add it later to ~/.radsim/.env")
            pause()
            return None

        # Validate key format (basic check)
        if len(api_key_input) < 20:
            print()
            print("  warning: That doesn't look like a valid API key.")
            print("  You can add it later to ~/.radsim/.env")
            pause()
            return None

        # Save the key securely
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Load existing keys and add this one
        env_config = load_env_file()
        existing_keys = env_config.get("keys", {})
        existing_keys[env_var_name] = api_key_input

        # Write to .env file
        lines = [
            "# RadSim Configuration",
            "# This file is chmod 600 (secure)",
            "",
            f'RADSIM_PROVIDER="{provider}"',
            "",
            "# API Keys",
        ]

        for key_name, key_value in existing_keys.items():
            if key_value and not key_value.lower().startswith("paste_your"):
                lines.append(f'{key_name}="{key_value}"')

        lines.append("")
        ENV_FILE.write_text("\n".join(lines))
        ENV_FILE.chmod(0o600)  # Secure permissions

        print()
        print("  ok API key saved securely to ~/.radsim/.env")
        pause()
        return api_key_input

    else:
        # Option C: Skip
        print()
        print("  No problem! You can add it later:")
        print(f"  1. Open: {ENV_FILE}")
        print(f'  2. Add: {env_var_name}="your-key-here"')
        print()
        print("  Then run 'radsim' again.")
        pause()
        return None


def step_settings():
    """Step 5: Configure initial settings."""
    clear_screen()
    print_header("Step 4 of 6: Preferences")

    print("  Let's configure a few preferences:")
    print()

    settings = {}

    # Auto-confirm setting
    print("  1. Auto-confirm file writes?")
    print("     (Skip confirmation for each file the AI creates)")
    print()
    print("     y = Yes, auto-confirm (faster, less safe)")
    print("     n = No, ask me each time (default, recommended)")
    print()

    try:
        auto_confirm = input("  Auto-confirm? [n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    settings["auto_confirm"] = auto_confirm in ["y", "yes"]

    # Verbose mode
    print()
    print("  2. Verbose mode?")
    print("     (Show detailed info about what the AI is doing)")
    print()

    try:
        verbose = input("  Verbose mode? [n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    settings["verbose"] = verbose in ["y", "yes"]

    # Token budget
    print()
    print("  3. Session token budget?")
    print("     (Limit tokens per session to control costs)")
    print()
    print("     0 = Unlimited (default)")
    print("     500000 = ~$1.50 per session with Claude Sonnet")
    print()

    try:
        budget_input = input("  Token budget [0]: ").strip()
        budget = int(budget_input) if budget_input else 0
    except (ValueError, KeyboardInterrupt, EOFError):
        budget = 0

    settings["max_session_input_tokens"] = budget

    # Save settings
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    existing_settings = {}
    if SETTINGS_FILE.exists():
        try:
            existing_settings = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            logger.debug("Failed to parse existing settings file during onboarding")

    existing_settings.update(settings)
    SETTINGS_FILE.write_text(json.dumps(existing_settings, indent=2))

    print()
    print("  ok Preferences saved!")
    pause()

    return settings


def step_appearance():
    """Step: Choose UI palette, font profile, and animation level."""
    from .theme import (
        ANIMATION_LEVELS,
        FONT_PROFILES,
        PALETTES,
        save_animation_level,
        save_font_profile_selection,
        save_palette_selection,
    )

    clear_screen()
    print_header("Step 5 of 6: Appearance")

    print("  Pick a color palette for RadSim's terminal UI.")
    print("  (You can change it anytime with /theme.)")
    print()

    palette_keys = list(PALETTES.keys())
    for index, key in enumerate(palette_keys, 1):
        palette = PALETTES[key]
        print(f"    {index}. {palette['label']}")
        print(f"       {palette['description']}")
    print()

    try:
        raw = input(f"  Enter 1-{len(palette_keys)} [2 = Soft Neon]: ").strip() or "2"
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    try:
        index = int(raw) - 1
        if 0 <= index < len(palette_keys):
            save_palette_selection(palette_keys[index])
            print(f"\n  ok Palette: {PALETTES[palette_keys[index]]['label']}")
    except ValueError:
        logger.debug("Non-numeric palette choice; keeping default")

    print()
    print("  Now pick a font/glyph profile.")
    print("  Nerd Font = best visuals but requires a patched terminal font.")
    print("  Unicode = safe default. ASCII = maximum compatibility.")
    print("  (You can change it anytime with /font.)")
    print()

    profile_keys = list(FONT_PROFILES.keys())
    for index, key in enumerate(profile_keys, 1):
        profile = FONT_PROFILES[key]
        print(f"    {index}. {profile['label']}")
        print(f"       {profile['description']}")
    print()

    try:
        raw = input(f"  Enter 1-{len(profile_keys)} [2 = Unicode]: ").strip() or "2"
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    try:
        index = int(raw) - 1
        if 0 <= index < len(profile_keys):
            save_font_profile_selection(profile_keys[index])
            print(f"\n  ok Font profile: {FONT_PROFILES[profile_keys[index]]['label']}")
    except ValueError:
        logger.debug("Non-numeric font profile choice; keeping default")

    print()
    print("  Finally, pick an animation level.")
    print("  Full = animated spinner and tool updates.")
    print("  Subtle = static status line and in-place tool updates.")
    print("  Off = final output only.")
    print("  (You can change it anytime with /animations.)")
    print()

    for index, level in enumerate(ANIMATION_LEVELS, 1):
        print(f"    {index}. {level}")
    print()

    try:
        raw = input(f"  Enter 1-{len(ANIMATION_LEVELS)} [2 = subtle]: ").strip() or "2"
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled.")
        sys.exit(0)

    try:
        index = int(raw) - 1
        if 0 <= index < len(ANIMATION_LEVELS):
            save_animation_level(ANIMATION_LEVELS[index])
            print(f"\n  ok Animation level: {ANIMATION_LEVELS[index]}")
    except ValueError:
        logger.debug("Non-numeric animation choice; keeping default")

    pause()


def step_tutorial():
    """Step 6: Quick tutorial."""
    clear_screen()
    print_header("Step 6 of 6: Quick Start Guide")

    print("  Here's how to use RadSim:")
    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  BASIC USAGE                                    │")
    print("  ├─────────────────────────────────────────────────┤")
    print("  │  Just type what you want to do:                 │")
    print("  │                                                 │")
    print("  │  > Create a Python function to validate emails  │")
    print("  │  > Fix the bug in src/utils.py                  │")
    print("  │  > Add error handling to this code              │")
    print("  └─────────────────────────────────────────────────┘")
    print()

    pause()

    clear_screen()
    print_header("Quick Start Guide")

    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  USEFUL COMMANDS                                │")
    print("  ├─────────────────────────────────────────────────┤")
    print("  │  /help        - Show all commands               │")
    print("  │  /tools       - List available tools            │")
    print("  │  /switch      - Change AI provider/model        │")
    print("  │  /clear       - Clear conversation history      │")
    print("  │  /teach       - Toggle teaching mode            │")
    print("  │  /exit        - Exit RadSim                     │")
    print("  └─────────────────────────────────────────────────┘")
    print()

    pause()

    clear_screen()
    print_header("Quick Start Guide")

    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  SAFETY FEATURES                                │")
    print("  ├─────────────────────────────────────────────────┤")
    print("  │  • RadSim asks before writing/deleting files    │")
    print("  │  • Press Esc or Ctrl+C to cancel any operation  │")
    print("  │  • Double Ctrl+C = Emergency hard stop          │")
    print("  │  • Type /kill to immediately stop the agent     │")
    print("  │  • /reset budget clears token limits            │")
    print("  └─────────────────────────────────────────────────┘")
    print()

    pause()


def step_complete(user_name: str, provider: str, model: str):
    """Final step: Confirm setup complete."""
    clear_screen()
    print_header("Setup Complete!")

    print(f"  You're all set, {user_name}!")
    print()
    print("  Your configuration:")
    print(f"    Provider: {provider.title()}")
    print(f"    Model:    {model}")
    print("    Config:   ~/.radsim/")
    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  Ready to code! Just type your request below.  │")
    print("  │                                                 │")
    print("  │  Example: Create a hello world Flask app        │")
    print("  └─────────────────────────────────────────────────┘")
    print()

    # Mark onboarding complete
    mark_onboarding_complete(user_name)

    # Save user name to memory for personalization
    try:
        from .memory import save_memory

        save_memory("name", user_name, memory_type="preference")
    except Exception:
        logger.debug("Failed to save user name to memory during onboarding")


def run_onboarding() -> tuple:
    """Run the complete onboarding flow.

    Returns:
        Tuple of (api_key, provider, model) or (None, None, None) if incomplete.
    """
    # Step 0: Terms & Conditions (must accept to continue)
    if not has_accepted_terms():
        accepted = step_terms_and_conditions()
        if not accepted:
            sys.exit(0)
        mark_terms_accepted()

    # Step 1: Welcome
    user_name = step_welcome()

    # Step 2: User profile (personalization)
    step_user_profile(user_name)

    # Step 3: Provider intro
    step_provider_intro()

    # Step 4: Select provider and model
    provider, model = step_select_provider()

    # Step 5: API key
    api_key = step_api_key(provider)

    if not api_key:
        # User skipped API key - can't continue
        print()
        print("  Please add your API key and run 'radsim' again.")
        print()
        return None, None, None

    # Step 6: Settings
    step_settings()

    # Step 7: Appearance (palette + font profile)
    step_appearance()

    # Step 8: Tutorial
    step_tutorial()

    # Step 8: Complete
    step_complete(user_name, provider, model)

    # Save final config
    save_config(api_key, provider, model)

    return api_key, provider, model


def should_run_onboarding() -> bool:
    """Check if onboarding should run.

    Returns True if:
    - First time running (no config exists)
    - User hasn't completed onboarding
    """
    # Check if onboarding was completed
    if has_completed_onboarding():
        return False

    # Check if config exists (might be manual setup)
    if ENV_FILE.exists():
        env_config = load_env_file()
        # If they have a valid API key, skip onboarding
        for key in env_config.get("keys", {}).values():
            if key and not key.lower().startswith("paste_your"):
                return False

    return True
