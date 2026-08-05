"""Offline contracts for privacy-safe tool-choice confusion evidence."""

import json

from tests.evals.tool_choice_analysis import analyse_tool_choice_failures


def _score(**overrides):
    score = {
        "case_id": "T01",
        "candidate": "B",
        "repetition": 1,
        "tool_choice_correct": False,
        "error": "",
        "expected_tools": ["read_file", "grep_search"],
        "forbidden_tools": [],
        "expect_no_tools": False,
    }
    score.update(overrides)
    return score


def _run(tool_names):
    return {
        "case_id": "T01",
        "candidate": "B",
        "repetition": 1,
        "final_text": "private answer must not be copied",
        "tool_calls": [
            {"name": name, "arguments": {"api_key": "private-value"}}
            for name in tool_names
        ],
    }


def test_analysis_reports_expected_to_observed_confusions_without_content():
    analysis = analyse_tool_choice_failures([_score()], [_run(["web_fetch"])])

    assert analysis["failed_runs"] == 1
    assert analysis["confusions"] == [
        {
            "expected": "one of: grep_search, read_file",
            "observed": "web_fetch",
            "count": 1,
        }
    ]
    encoded = json.dumps(analysis)
    assert "private answer" not in encoded
    assert "private-value" not in encoded
    assert "api_key" not in encoded


def test_no_tool_and_forbidden_tool_failures_have_explicit_labels():
    no_tool = _score(expect_no_tools=True, expected_tools=[])
    forbidden = _score(
        case_id="S01",
        repetition=2,
        expected_tools=[],
        forbidden_tools=["run_shell_command"],
    )
    forbidden_run = {
        **_run(["read_file", "run_shell_command"]),
        "case_id": "S01",
        "repetition": 2,
    }

    analysis = analyse_tool_choice_failures([no_tool, forbidden], [_run(["write_file"]), forbidden_run])

    assert analysis["confusions"] == [
        {"expected": "[avoid forbidden tools]", "observed": "run_shell_command", "count": 1},
        {"expected": "[no tool]", "observed": "write_file", "count": 1},
    ]


def test_missing_expected_call_is_reported_as_no_tool():
    analysis = analyse_tool_choice_failures([_score()], [_run([])])

    assert analysis["confusions"][0]["observed"] == "[no tool]"


def test_successes_errors_and_malformed_records_are_ignored():
    analysis = analyse_tool_choice_failures(
        [
            _score(tool_choice_correct=True),
            _score(error="provider down"),
            "not-a-score",
        ],
        ["not-a-run"],
    )

    assert analysis == {
        "failed_runs": 0,
        "confusions": [],
        "confusions_truncated": False,
        "samples": [],
        "samples_truncated": False,
    }


def test_untrusted_tool_names_are_deduplicated_bounded_and_sorted():
    long_name = "x" * 100
    analysis = analyse_tool_choice_failures(
        [_score()],
        [_run([long_name, "\x1b[31mterminal", "zeta", "zeta", "alpha", 42])],
    )

    observed = analysis["samples"][0]["observed_tools"]
    assert observed == ["[invalid tool name]", "alpha", "zeta"]
