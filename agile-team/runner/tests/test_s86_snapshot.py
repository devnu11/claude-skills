"""s86: the snapshot's dependency keys per story (design DP13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agile_team import state as state_mod
from agile_team.gates import StoryState, StoryStatus
from agile_team.state import RunState

from .test_snapshot import build, make_config


def by_id(stories: dict[str, StoryState], tmp: Path) -> dict[str, dict[str, Any]]:
    config = make_config(tmp / "repo")
    state_mod.save(config.run_dir, RunState(stories=stories, order=list(stories)))
    return {s["id"]: s for s in build(config, tmp)["stories"]}


def story(sid: str, deps: list[str], **kw: Any) -> StoryState:
    return StoryState(sid, sid, "design", depends_on=deps, **kw)


def test_each_story_has_the_three_keys(scratch: Path) -> None:
    rows = by_id({"s1": story("s1", []), "s2": story("s2", ["s1"])}, scratch)
    assert rows["s1"]["depends_on"] == [] and rows["s1"]["waiting_on"] == []
    assert rows["s2"]["depends_on"] == ["s1"] and rows["s2"]["waiting_on"] == ["s1"]
    assert rows["s2"]["dependency_warnings"] == []


def test_a_story_ranked_above_its_dependency_warns(scratch: Path) -> None:
    rows = by_id({"s1": story("s1", ["s2"]), "s2": story("s2", [])}, scratch)
    assert rows["s1"]["dependency_warnings"] == ["s1 is above s2, which it depends on"]
    assert rows["s2"]["dependency_warnings"] == []


def test_a_done_dependency_is_not_waiting_and_a_done_story_has_empty_lists(
    scratch: Path,
) -> None:
    done = story("s2", [], status=StoryStatus.DONE)
    rows = by_id(
        {"s1": story("s1", ["s2"]), "s2": done, "s3": story("s3", ["s2"], status=StoryStatus.DONE)},
        scratch,
    )
    assert rows["s1"]["depends_on"] == ["s2"] and rows["s1"]["waiting_on"] == []
    assert rows["s3"]["depends_on"] == ["s2"]
    assert rows["s3"]["waiting_on"] == [] and rows["s3"]["dependency_warnings"] == []


@pytest.mark.parametrize("key", ["depends_on", "waiting_on", "dependency_warnings"])
def test_keys_are_lists(scratch: Path, key: str) -> None:
    assert by_id({"s1": story("s1", [])}, scratch)["s1"][key] == []


# ----- DP14: the page (static; behaviour under node moves to e2e) ---------------------


@pytest.fixture
def page() -> str:
    from importlib import resources

    from agile_team import system

    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_the_page_defines_the_dependency_helpers(page: str) -> None:
    assert "function depsLine(" in page and "function depWarnings(" in page
    assert "depends on " in page and "bdeps" in page
    assert "dependency_warnings" in page and "waiting_on" in page


def test_backlog_row_shows_dependencies_and_the_timeline_shows_warnings(page: str) -> None:
    row = page[page.index("function backlogRow(") :]
    assert "depsLine(" in row.split("\nfunction ")[0]
    assert "depWarnings(" in row.split("\nfunction ")[0]
    assert "data.warnings" in page and "⚠" in page
