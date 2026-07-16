"""Parity checks for provider-facing tool definitions."""

import json
from pathlib import Path

from radsim.tools import _TOOL_REGISTRY, TOOL_DEFINITIONS

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"
BROWSER_TOOL_NAMES = {
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_screenshot",
}


def test_tool_definitions_match_golden_bytes():
    serialized_definitions = json.dumps(TOOL_DEFINITIONS, indent=2, sort_keys=True) + "\n"
    golden_definitions = (FIXTURE_DIRECTORY / "tool_definitions_golden.json").read_text()

    assert serialized_definitions == golden_definitions


def test_tool_definition_order_matches_golden_names():
    golden_names = json.loads(
        (FIXTURE_DIRECTORY / "tool_definition_names_golden.json").read_text()
    )
    current_names = [definition["name"] for definition in TOOL_DEFINITIONS]

    assert current_names == golden_names


def test_every_tool_name_is_unique_and_executable():
    definition_names = [definition["name"] for definition in TOOL_DEFINITIONS]
    executable_names = set(_TOOL_REGISTRY) | BROWSER_TOOL_NAMES

    assert len(definition_names) == 72
    assert len(definition_names) == len(set(definition_names))
    assert set(definition_names) == executable_names
