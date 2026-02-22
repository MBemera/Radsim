"""Tests for __main__.py and CLI entry point."""

import subprocess
import sys


class TestMainModule:
    """Test python -m radsim works."""

    def test_main_module_exists(self):
        """__main__.py must exist for python -m radsim to work."""
        from radsim import __main__  # noqa: F401

    def test_main_imports_cli(self):
        """__main__.py should import main from cli."""
        from radsim.__main__ import main
        assert callable(main)

    def test_version_flag(self):
        """radsim --version should print version and exit cleanly."""
        result = subprocess.run(
            [sys.executable, "-m", "radsim", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "RadSim" in result.stdout

    def test_help_flag(self):
        """radsim --help should print usage and exit cleanly."""
        result = subprocess.run(
            [sys.executable, "-m", "radsim", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "RadSim" in result.stdout


class TestCLIParsing:
    """Test CLI argument parsing."""

    def test_parse_provider_choices(self):
        """All 5 providers should be valid choices."""
        from radsim.cli import parse_arguments

        for provider in ["claude", "openai", "gemini", "vertex", "openrouter"]:
            # Test that parsing doesn't raise for valid providers
            sys.argv = ["radsim", "--provider", provider, "test prompt"]
            args = parse_arguments()
            assert args.provider == provider

    def test_parse_yes_flag(self):
        """--yes flag should set auto_confirm."""
        from radsim.cli import parse_arguments

        sys.argv = ["radsim", "--yes", "test prompt"]
        args = parse_arguments()
        assert args.yes is True

    def test_parse_no_stream_flag(self):
        """--no-stream flag should be parsed."""
        from radsim.cli import parse_arguments

        sys.argv = ["radsim", "--no-stream", "test prompt"]
        args = parse_arguments()
        assert args.no_stream is True

    def test_parse_prompt(self):
        """Positional prompt argument should be captured."""
        from radsim.cli import parse_arguments

        sys.argv = ["radsim", "Create a hello world app"]
        args = parse_arguments()
        assert args.prompt == "Create a hello world app"

    def test_parse_no_prompt_interactive(self):
        """No prompt means interactive mode."""
        from radsim.cli import parse_arguments

        sys.argv = ["radsim"]
        args = parse_arguments()
        assert args.prompt is None
