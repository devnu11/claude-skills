"""s119: static checks of the goal line, stage line and Markdown list width (G, ST, W)."""

import re
from importlib import resources

from agile_team import stage_log, stages, system
from agile_team.dashboard.step_times import Mark

PAGE = system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def rule(selector: str) -> str:
    """Body of the first CSS rule whose selector is exactly ``selector``."""
    found = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", PAGE)
    assert found, selector
    return found.group(1)


def test_timeline_rows_use_child_combinators() -> None:
    body = rule(".timeline > li")
    assert "display: grid" in body
    assert "grid-template-columns: 46px minmax(0, 1fr)" in body
    assert "animation: flash" in rule(".timeline > li.new")
    assert "font-size: 12px" in rule(".timeline > li > time")


def test_no_descendant_timeline_selector_remains() -> None:
    assert not re.search(r"\.timeline\s+(li|time)\b", PAGE)
    assert not re.search(r"\.timeline li\b|\.timeline time\b", PAGE)


def test_reduced_motion_targets_the_child_row() -> None:
    assert ".timeline > li.new" in PAGE.split("prefers-reduced-motion")[1]


def test_the_goal_functions_exist_and_the_task_is_the_fallback() -> None:
    for name in ("sprintGoal", "goalText", "renderGoal", "stageLine"):
        assert f"function {name}(" in PAGE, name
    assert "sprint-start" in PAGE
    assert "sprintGoal(view) || view.run.task" in PAGE


def test_the_goal_line_stays_one_ellipsised_line() -> None:
    body = rule(".task")
    for part in ("white-space: nowrap", "overflow: hidden", "text-overflow: ellipsis"):
        assert part in body


def test_runner_result_is_gone() -> None:
    assert "runnerResult" not in PAGE


def test_open_row_carries_the_stage_description_after_attach() -> None:
    run = stages.Run(stages.STAGES[stages.Name.GATE_GREEN], stages.Place("s1", "implement"))
    row = stage_log.open_row(run, Mark(5.0, 7.0, 1.5))
    assert row["description"] == run.stage.description
    keys = list(row)
    assert keys.index("description") == keys.index("attach") + 1
