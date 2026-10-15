"""s157: lint findings ignore warning lines, so house-rules warnings never route a gate fix."""

import pytest
from agile_team import owners
from agile_team.owners import Source


def paths(output: str) -> list[str]:
    return [f.path for f in owners.findings(output, Source.LINT)]


def test_house_rules_fail_line_is_a_finding() -> None:
    out = "a/b.py:12: fail function-length: 14 statements\n"
    assert paths(out) == ["a/b.py"]


@pytest.mark.parametrize(
    "line",
    [
        "a/b.py:12: warn function-length: 14 statements",
        "a/b.py:3:1: warning: something",
        "a/b.py:3: WARNING x",
        "a/b.py:3: Warn x",
    ],
)
def test_warning_lines_are_not_findings(line: str) -> None:
    assert paths(line + "\n") == []


def test_ruff_code_still_counts() -> None:
    assert paths("a/b.py:3:1: W291 trailing whitespace\n") == ["a/b.py"]


def test_word_starting_with_warn_still_counts() -> None:
    assert paths("a/b.py:3: warnings_off is unused\n") == ["a/b.py"]


MIXED = (
    "x.py:1: fail function-length: too long\n"
    "y.py:2: warn nesting: deep\n"
    "x.py:9: fail nesting: deeper\n"
    "y.py:5: warn function-length: long\n"
    "stale baseline entry: z.py function-length\n"
    "2 failures, 2 warnings\n"
)


def test_mixed_output_finds_only_failing_file() -> None:
    assert set(paths(MIXED)) == {"x.py"}


def test_mixed_output_places_one_item_with_both_fail_lines() -> None:
    items = owners.placed(owners.findings(MIXED, Source.LINT), "x.py\ny.py\n")
    assert [i.path for i in items] == ["x.py"]
    assert items[0].lines == [
        "x.py:1: fail function-length: too long",
        "x.py:9: fail nesting: deeper",
    ]


def test_ruff_full_pattern_unchanged() -> None:
    out = "E501 Line too long\n --> pkg/mod.py:3:5\n"
    assert paths(out) == ["pkg/mod.py"]


def test_would_reformat_pattern_unchanged() -> None:
    assert paths("Would reformat: pkg/mod.py\n") == ["pkg/mod.py"]
