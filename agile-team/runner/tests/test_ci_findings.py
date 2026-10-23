"""s172/AC2: the tiers of finding lines that ``ci.failing_lines`` shows for a failed step."""

from __future__ import annotations

from agile_team import ci_findings


def pick(*lines: str) -> list[str]:
    return ci_findings.pick_lines(list(lines))


def test_the_test_tier_wins_over_traceback_lines_ac2() -> None:
    traceback = [f"tests/test_x.py:{n}: AssertionError" for n in range(1, 30)]
    failed = ["FAILED tests/test_x.py::test_y - assert 1 == 2", "FAILED tests/test_x.py::test_z"]
    got = pick(*traceback, *failed, "2 failed, 3 passed")
    assert got == [*failed, "2 failed, 3 passed"]


def test_ruff_full_form_shows_the_finding_only_ac2() -> None:
    got = pick(
        "F401 [*] `os` imported but unused",
        "--> a.py:1:8",
        "  |",
        "1 | import os",
        "  |        ^^",
        "Found 1 error.",
        "Error: Process completed with exit code 1.",
    )
    assert got == ["a.py:1:8: F401 [*] `os` imported but unused"]


def test_a_found_count_is_not_a_test_failure_ac2() -> None:
    assert pick("a.py:1:1: E501 long", "Found 12 errors.") == ["a.py:1:1: E501 long"]


def test_a_count_of_failures_is_a_test_line_ac2() -> None:
    assert pick("noise", "3 errors in 0.5s") == ["3 errors in 0.5s"]


def test_house_rules_github_form_shows_path_line_and_message_ac2() -> None:
    line = "::error file=a.py,line=3,title=house-rules verb-name::compile_pattern is not a verb"
    assert pick("checking", line) == ["a.py:3: compile_pattern is not a verb"]


def test_house_rules_error_annotation_drops_the_exit_code_line_ac2() -> None:
    got = pick(
        "##[error]compile_pattern is not a verb", "##[error]Process completed with exit code 1."
    )
    assert got == ["compile_pattern is not a verb"]


def test_house_rules_text_form_is_shown_as_is_ac2() -> None:
    line = "src/c.py:12: fail verb-name: compile_pattern is not a verb"
    assert pick("checking 40 files", line) == [line]


def test_warnings_are_not_findings_ac2() -> None:
    fail = "src/c.py:12: fail verb-name: bad"
    got = pick("src/a.py:1: warn long-function: 40 lines", fail, "src/b.py:2: warn x: y")
    assert got == [fail]


def test_a_format_log_shows_the_would_reformat_lines_ac2() -> None:
    assert pick("x", "Would reformat: a.py", "1 file would be reformatted") == [
        "Would reformat: a.py"
    ]


def test_no_hit_gives_no_lines_ac2() -> None:
    assert pick("plain", "text") == [] and pick() == []


def test_the_first_line_has_an_empty_previous_ac2() -> None:
    assert pick("--> a.py:1:8") == ["a.py:1:8: "]
