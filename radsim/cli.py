# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""CLI entry point for RadSim Agent."""

import argparse
import os
import signal
import sys
from importlib.metadata import version

from .agent import run_interactive, run_single_shot
from .config import load_config
from .output import print_agent_response, print_error

# Track Ctrl+C presses for emergency stop
_interrupt_count = 0
_last_interrupt = 0


def _emergency_stop_handler(signum, frame):
    """Handle Ctrl+C with escalating response.

    First Ctrl+C: graceful interrupt
    Second Ctrl+C within 2 seconds: HARD KILL
    """
    global _interrupt_count, _last_interrupt
    import time

    current_time = time.time()

    # Reset counter if more than 2 seconds since last interrupt
    if current_time - _last_interrupt > 2:
        _interrupt_count = 0

    _interrupt_count += 1
    _last_interrupt = current_time

    if _interrupt_count >= 2:
        print("\n\n  🛑 EMERGENCY STOP - Killing process immediately!")
        os._exit(1)
    else:
        print("\n\n  ⚠ Interrupted. Press Ctrl+C again within 2 seconds to FORCE KILL.")
        raise KeyboardInterrupt


# Install signal handler
signal.signal(signal.SIGINT, _emergency_stop_handler)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="radsim",
        description="RadSim - Radically Simple Code Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  radsim "Create a Python function to validate emails"
  radsim "Build a REST API in Go"
  radsim --yes "Refactor src/utils.js"
  radsim  (starts interactive mode)

Environment variables:
  RADSIM_PROVIDER   API provider (claude, openai, gemini)
  RADSIM_API_KEY    Your API key
        """,
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        help="The coding task (omit for interactive mode)",
    )

    parser.add_argument(
        "--provider",
        "-p",
        choices=["claude", "openai", "gemini", "vertex", "openrouter"],
        help="API provider (default: claude)",
    )

    parser.add_argument(
        "--api-key",
        "-k",
        help="API key (or use RADSIM_API_KEY env var)",
    )

    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Auto-confirm file writes",
    )

    parser.add_argument(
        "--verbose",
        "-V",
        action="store_true",
        help="Enable verbose output",
    )

    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming responses",
    )

    parser.add_argument(
        "--context-file",
        help="Load initial context from a file (e.g. context.md)",
    )

    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"RadSim {version('radsim')}",
    )

    parser.add_argument(
        "--skip-onboarding",
        action="store_true",
        help="Skip the first-time setup wizard",
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Re-run the setup wizard",
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    # Configure logging early, before anything else
    from .log_config import configure_logging

    configure_logging()

    args = parse_arguments()

    # T&C is shown only during onboarding (first-time setup), not every login
    from .onboarding import (
        run_onboarding,
        should_run_onboarding,
    )

    # Check if this is first run - show onboarding

    # Force re-run setup if --setup flag is passed
    if args.setup:
        api_key, provider, model = run_onboarding()
        if not api_key:
            sys.exit(0)
        args.provider = provider
        args.api_key = api_key
    # Normal first-run onboarding (unless skipped)
    elif (
        should_run_onboarding()
        and not args.skip_onboarding
        and not args.api_key
        and not args.provider
    ):
        api_key, provider, model = run_onboarding()
        if not api_key:
            # User didn't complete onboarding
            sys.exit(0)
        # Override args with onboarding results
        args.provider = provider
        args.api_key = api_key

    # Check access control first (if enabled)
    from .access_control import check_access_on_startup

    if not check_access_on_startup():
        sys.exit(1)

    # Load configuration
    try:
        config = load_config(
            provider_override=args.provider,
            api_key_override=args.api_key,
            auto_confirm=args.yes,
            verbose=args.verbose,
            stream=not args.no_stream,
        )
    except ValueError as error:
        print_error(str(error))
        sys.exit(1)

    # Production Readiness: Run startup health checks
    from .health import check_health, check_secret_expirations

    health_status = check_health(config)
    if not health_status.healthy:
        print_error("Health check failed:")
        for name, info in health_status.checks.items():
            if not info["ok"]:
                print_error(f"  - {name}: {info['message']}")
        sys.exit(1)

    # Check for expiring secrets
    expiration_warnings = check_secret_expirations()
    for warning in expiration_warnings:
        if warning["status"] == "expired":
            print_error(f"WARNING: {warning['message']}")
        else:
            print(f"  Note: {warning['message']}")

    # Run in appropriate mode
    if args.prompt:
        # Single-shot mode
        try:
            response = run_single_shot(config, args.prompt, args.context_file)
            if not config.stream:
                print_agent_response(response)
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(130)
        except Exception as error:
            print_error(str(error))
            sys.exit(1)
    else:
        # Interactive mode
        try:
            run_interactive(config, args.context_file)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            sys.exit(130)


if __name__ == "__main__":
    main()
