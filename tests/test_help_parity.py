"""Rendered parity checks for command long-help output."""

import re
from pathlib import Path

import pytest

from radsim.commands_metadata import DEFAULT_COMMAND_SPECS
from radsim.output import HELP_DETAILS, _resolve_help_topic, print_help_detail

HELP_FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "help_golden"
ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
HELP_TOPICS = [spec["names"][0].lstrip("/") for spec in DEFAULT_COMMAND_SPECS]


@pytest.mark.parametrize("topic", HELP_TOPICS)
def test_rendered_help_matches_golden(topic, capsys):
    print_help_detail(topic)

    rendered_help = ANSI_PATTERN.sub("", capsys.readouterr().out)
    golden_help = (HELP_FIXTURE_DIRECTORY / f"{topic}.txt").read_text()

    assert rendered_help == golden_help


def test_help_topics_match_primary_commands():
    assert set(HELP_DETAILS) == set(HELP_TOPICS)


@pytest.mark.parametrize("topic", HELP_TOPICS)
def test_primary_help_topic_resolution_is_unchanged(topic):
    assert _resolve_help_topic(topic) == topic
    assert _resolve_help_topic(f"/{topic}") == topic


@pytest.mark.parametrize(
    ("alias", "topic"),
    [
        (alias, topic)
        for topic, details in HELP_DETAILS.items()
        for alias in details.get("aliases", [])
    ],
)
def test_help_alias_resolution_is_unchanged(alias, topic):
    assert _resolve_help_topic(alias) == topic
