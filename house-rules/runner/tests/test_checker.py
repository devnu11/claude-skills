"""The engine: suppressions, parse errors, outcome sorting."""

from pathlib import Path

from house_rules.baseline import Baseline
from house_rules.checker import check_sources
from house_rules.config import Settings
from house_rules.model import Level
from house_rules.source import Source

from .conftest import CheckText

LONG = "def add(a, b, c, d):\n    return a\n"


def test_suppressed_line_is_not_reported(check_text: CheckText) -> None:
    text = "def add(a, b, c, d):  # house-rules: allow parameters -- legacy API\n    return a\n"
    assert check_text(text) == []


def test_noqa_alias_suppresses(check_text: CheckText) -> None:
    text = "def show(rows, compact: bool):  # noqa: FBT001 -- callback\n    return rows\n"
    assert check_text(text) == []


def test_parse_error_fails(check_text: CheckText) -> None:
    [finding] = check_text("def broken(:\n")
    assert (finding.rule, finding.level, finding.line) == ("parse-error", Level.FAIL, 1)


def test_disabled_rules_do_not_run(check_text: CheckText) -> None:
    assert check_text(LONG, disable=frozenset({"parameters"})) == []


def test_outcome_sorts_against_the_baseline(tmp_path: Path) -> None:
    settings = Settings(tmp_path)
    Baseline({"old.py::add::parameters": 4}).write(settings.baseline_path)
    sources = [
        Source("old.py", LONG),
        Source("new.py", LONG),
        Source("warn.py", "def add(a, b, c):\n    return a\n"),
    ]
    outcome = check_sources(sources, settings)
    assert [item.path for item in outcome.failures] == ["new.py"]
    assert [item.path for item in outcome.baselined] == ["old.py"]
    assert [item.path for item in outcome.warnings] == ["warn.py"]
    assert outcome.status == 1 and outcome.stale == []


def test_stale_entries_only_for_checked_files(tmp_path: Path) -> None:
    settings = Settings(tmp_path)
    Baseline({"old.py::add::parameters": 4, "other.py::f::parameters": 4}).write(
        settings.baseline_path
    )
    outcome = check_sources([Source("old.py", "def add(a):\n    return a\n")], settings)
    assert outcome.stale == ["old.py::add::parameters"] and outcome.status == 0
