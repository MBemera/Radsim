"""Security regression tests for the self-extension (add_tool) path.

R-01 (Critical): a crafted JSON-schema property name could close the
generated function signature, insert a top-level statement, and start a
second function so the whole source still parsed. The statement then ran
during hot reload — before the custom tool was ever called. These tests
prove every hostile property-name form is rejected and no injected
top-level statement executes.
"""

import pytest

from radsim.agent_config import DEFAULT_CONFIG, TOOL_CONFIG_MAP
from radsim.tools import self_extend


@pytest.fixture
def isolated_custom_file(tmp_path, monkeypatch):
    """Redirect the generated-tools file so tests never touch the package."""
    custom_file = tmp_path / "custom_tools.py"
    custom_file.write_text(self_extend.CUSTOM_TOOLS_FILE.read_text())
    monkeypatch.setattr(self_extend, "CUSTOM_TOOLS_FILE", custom_file)
    return custom_file


def _add(name="probe_tool", properties=None, body="return {'ok': True}"):
    return self_extend.add_tool(
        name=name,
        description="probe",
        parameters={"properties": properties or {}},
        body=body,
    )


class TestPropertyKeyInjection:
    """A property name is joined into the signature; it must be an identifier."""

    def test_signature_closing_payload_is_rejected(self, isolated_custom_file):
        # Close the signature, run a marker, reopen a function so it parses.
        payload = "x):\n    pass\nRADSIM_MARKER_EXECUTED = True\ndef _sink(y"
        result = _add(properties={payload: {"type": "string"}})
        assert result["success"] is False
        # The hostile source must never have been appended or imported.
        assert "RADSIM_MARKER_EXECUTED" not in isolated_custom_file.read_text()
        assert not hasattr(self_extend, "RADSIM_MARKER_EXECUTED")

    @pytest.mark.parametrize(
        "bad_key",
        [
            "a, b",              # comma splits into two params
            "x)",                # closes the signature early
            "x:int",            # annotation syntax
            "x=1",               # default-value syntax
            "with space",        # whitespace
            "trailing\n",        # newline
            "# comment",         # comment character
            "*args",             # star-arg syntax
            "**kwargs",          # double-star syntax
            "café",              # non-ASCII identifier
            "ﬀ",            # NFKC-normalises to "ff"
        ],
    )
    def test_non_identifier_keys_rejected(self, isolated_custom_file, bad_key):
        result = _add(properties={bad_key: {"type": "string"}})
        assert result["success"] is False

    @pytest.mark.parametrize("kw", ["import", "class", "return", "lambda", "None", "def"])
    def test_python_keywords_rejected(self, isolated_custom_file, kw):
        result = _add(properties={kw: {"type": "string"}})
        assert result["success"] is False
        assert "keyword" in result["error"].lower()

    def test_dunder_key_rejected(self, isolated_custom_file):
        result = _add(properties={"__globals__": {"type": "string"}})
        assert result["success"] is False

    def test_too_many_parameters_rejected(self, isolated_custom_file):
        props = {f"p{i}": {"type": "string"} for i in range(self_extend.MAX_PROPERTIES + 1)}
        result = _add(properties=props)
        assert result["success"] is False

    def test_valid_identifier_keys_accepted(self, isolated_custom_file):
        result = _add(properties={"first": {"type": "string"}, "second": {"type": "string"}})
        assert result["success"] is True


class TestGeneratedSourceStructure:
    """Only a single top-level function may be produced."""

    def test_single_function_ok(self):
        src = self_extend._build_function_source("good", {"a": {}}, "return a")
        assert self_extend._validate_generated_source(src, "good") is None

    def test_multiple_top_level_statements_rejected(self):
        malicious = "def good(a):\n    return a\nRADSIM_MARKER = 1\n"
        assert self_extend._validate_generated_source(malicious, "good") is not None

    def test_name_mismatch_rejected(self):
        src = "def other(a):\n    return a\n"
        assert self_extend._validate_generated_source(src, "good") is not None


class TestDisabledByDefault:
    """Self-extension must be off unless a user deliberately enables it."""

    def test_self_extension_default_off(self):
        assert DEFAULT_CONFIG["tools"]["self_extension"] is False

    def test_add_and_remove_tool_gated_on_self_extension(self):
        assert TOOL_CONFIG_MAP["add_tool"] == "self_extension"
        assert TOOL_CONFIG_MAP["remove_tool"] == "self_extension"

    def test_config_manager_blocks_add_tool_by_default(self, tmp_path):
        from radsim.agent_config import AgentConfigManager

        manager = AgentConfigManager(config_dir=tmp_path / ".radsim")
        assert manager.is_tool_enabled("add_tool") is False
        manager.set("tools.self_extension", True)
        assert manager.is_tool_enabled("add_tool") is True
