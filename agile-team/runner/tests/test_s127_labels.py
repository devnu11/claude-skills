"""s127 (AC1, LB1-LB4): short stage labels, repo tool labels and the snapshot's stage_labels."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import stages
from agile_team.stages import Name

from .test_snapshot import build, make_config

LB2 = {
    "env.prepare": "env prepare",
    "presentation.layout": "presentation layout",
    "quality.lint": "ruff check",
    "quality.static": "ruff format",
    "quality.coverage": "coverage report",
    "checkout.guard": "checkout guard",
    "checkout.verify": "checkout verify",
    "gate.tests-red": "pytest: new tests red",
    "gate.tests-rework": "pytest: rework",
    "gate.tests+coverage": "pytest + coverage",
    "gate.suite-runs": "pytest: repeat runs",
    "gate.dispute-output": "pytest: disputed test",
    "gate.route-lint": "ruff check + format",
    "presentation.trial": "presentation trial",
    "gate.green": "pytest: must pass",
    "boundary.sync": "boundary sync",
    "boundary.check": "boundary check",
    "boundary.review": "build review branches",
    "boundary.push": "review PR + push",
    "boundary.rebase": "rebase onto target",
    "boundary.restack": "restack review PRs",
    "boundary.ci-wait": "CI wait",
    "runner-tool.run_tests": "pytest: named tests",
    "runner-tool.run_new_tests": "pytest: new test files",
    "stop.handoff": "stop: handoff parses",
    "stop.lint": "stop: lint fix + check",
    "stop.suite": "stop: suite + coverage",
    "stop.red": "stop: new tests red",
    "stop.presentation": "stop: presentation",
}


def label_problems(labels: dict[str, str]) -> list[str]:
    """What is wrong with a ``{name: label}`` table: missing, too long or repeated."""
    found = [f"{n}: missing" for n, x in labels.items() if not x.strip()]
    found += [f"{n}: long" for n, x in labels.items() if len(x) > stages.LABEL_MAX]
    values = list(labels.values())
    found += [f"{x}: repeated" for x in sorted(set(values)) if values.count(x) > 1]
    return found


def built_in() -> dict[str, str]:
    return {str(n): s.label for n, s in stages.STAGES.items()}


def test_the_label_limit_is_24() -> None:
    assert stages.LABEL_MAX == 24


def test_every_built_in_label_is_valid_and_unique() -> None:
    assert label_problems(built_in()) == []
    assert len(stages.LABELS) == len(stages.STAGES)
    assert frozenset(built_in().values()) == stages.LABELS


def test_the_checker_catches_a_missing_a_long_and_a_repeated_label() -> None:
    assert label_problems({"a": ""}) == ["a: missing"]
    assert label_problems({"a": "x" * 25}) == ["a: long"]
    assert label_problems({"a": "x" * 24}) == []
    assert label_problems({"a": "x", "b": "x"}) == ["x: repeated"]


def test_the_table_covers_every_stage_and_no_other() -> None:
    assert set(LB2) == set(built_in())


@pytest.mark.parametrize(("name", "label"), list(LB2.items()))
def test_a_built_in_label_word_for_word(name: str, label: str) -> None:
    assert stages.STAGES[Name(name)].label == label


def test_as_dict_keys_are_in_order() -> None:
    row = stages.STAGES[Name("gate.green")].as_dict()
    assert list(row) == ["name", "label", "description", "when", "attach"]
    assert row["label"] == "pytest: must pass"


# ----- LB3 -----


def tool(name: str = "n", label: str = "") -> cfg.Tool:
    return cfg.Tool(name, "d", "make x", label)


def test_a_tool_without_a_label_uses_its_name() -> None:
    assert cfg.Tool("n", "d", "c").label == ""
    assert tool().chart_label() == "n"


def test_a_blank_label_uses_the_name() -> None:
    assert tool(label="  ").chart_label() == "n"
    assert cfg.tool_problems([tool(label="  ")]) == []


def test_a_tool_label_is_used_and_stripped() -> None:
    assert tool(label=" deploy it ").chart_label() == "deploy it"


def test_a_24_character_label_is_fine_and_25_is_refused() -> None:
    assert cfg.tool_problems([tool(label="x" * 24)]) == []
    assert cfg.tool_problems([tool(label="x" * 25)]) == [
        "[[tool]] 'n' label must be at most 24 characters"
    ]


def test_two_tools_with_one_label_are_refused() -> None:
    rows = [tool("a", "x"), tool("b", "x")]
    assert cfg.tool_problems(rows) == ["[[tool]] label 'x' is repeated"]


def test_a_tool_label_equal_to_a_built_in_one_is_refused() -> None:
    assert cfg.tool_problems([tool(label="CI wait")]) == ["[[tool]] label 'CI wait' is repeated"]


def test_a_name_used_as_label_that_repeats_a_label_is_refused() -> None:
    rows = [tool("x"), tool("b", "x")]
    assert cfg.tool_problems(rows) == ["[[tool]] label 'x' is repeated"]


def test_the_label_is_read_from_the_config_row(scratch: Path) -> None:
    row = {"name": "deploy.preview", "description": "d", "command": "make p", "label": "deploy"}
    config = make_config(scratch / "repo", tool=[row])
    assert config.tools[0].label == "deploy"


def test_a_long_label_in_the_config_is_a_config_error(scratch: Path) -> None:
    row = {"name": "deploy.preview", "description": "d", "command": "make p", "label": "x" * 25}
    with pytest.raises(cfg.ConfigError, match="label must be at most 24 characters"):
        make_config(scratch / "repo", tool=[row])


# ----- LB4 -----


def test_the_snapshot_has_stage_labels_after_the_descriptions(scratch: Path) -> None:
    snap = build(make_config(scratch / "repo"), scratch)
    keys = list(snap)
    assert keys.index("stage_labels") == keys.index("stage_descriptions") + 1
    assert snap["stage_labels"] == built_in()
    assert list(snap["stage_labels"]) == [str(n) for n in stages.STAGES]


def test_a_repo_tool_adds_its_label_or_its_name(scratch: Path) -> None:
    rows = [
        {"name": "deploy.preview", "description": "d", "command": "c", "label": "preview"},
        {"name": "lint.docs", "description": "d", "command": "c"},
    ]
    got = build(make_config(scratch / "repo", tool=rows), scratch)["stage_labels"]
    assert list(got)[-2:] == ["deploy.preview", "lint.docs"]
    assert got["deploy.preview"] == "preview"
    assert got["lint.docs"] == "lint.docs"
    assert got["gate.green"] == "pytest: must pass"
