"""s159 AC9.1, AC9.2, AC7.3: the snapshot carries branch, landed, story CI and running."""

# ruff: noqa: F811
from __future__ import annotations

import json
from pathlib import Path

from agile_team import config as cfg
from agile_team import stages
from agile_team.dashboard.step_times import Span
from agile_team.events import EventKind
from agile_team.gates import StoryState
from agile_team.story_branches import Landed, StoryCi

from .test_snapshot import FIXTURE_TEXT, build, config, put_story  # noqa: F401


def story_row(config: cfg.Config, scratch: Path, story: StoryState) -> dict:
    put_story(config, story)
    (row,) = build(config, scratch)["stories"]
    return row


def test_a_row_shows_the_branch_ac9_1(config: cfg.Config, scratch: Path) -> None:
    story = StoryState("s1", "One", "implement", sprint=1, branch="team/story-s1-r1")
    assert story_row(config, scratch, story)["branch"] == "team/story-s1-r1"


def test_landed_is_null_until_done_then_the_merge_ac9_1(config: cfg.Config, scratch: Path) -> None:
    story = StoryState("s1", "One", "land", sprint=1, landed=Landed("m" * 40))
    assert story_row(config, scratch, story)["landed"] is None
    story.status = "done"
    assert story_row(config, scratch, story)["landed"] == "m" * 40


def test_story_ci_shows_sha_verdict_and_source_ac9_1(config: cfg.Config, scratch: Path) -> None:
    story = StoryState("s1", "One", "implement", sprint=1, ci=StoryCi("a" * 40, "red", "pr"))
    row = story_row(config, scratch, story)
    assert row["story_ci"] == {"sha": "a" * 40, "verdict": "red", "source": "pr"}


def test_running_is_true_while_the_heartbeat_has_a_step_for_the_story_ac9_1(
    config: cfg.Config, scratch: Path
) -> None:
    from agile_team import system

    put_story(config, StoryState("s1", "One", "implement", sprint=1))
    beat = {"steps": [{"story": "s1", "role": "developer"}], "step": {"story": "s1"}}
    system.write_text(config.run_dir / "heartbeat.json", json.dumps(beat))
    assert build(config, scratch)["stories"][0]["running"] is True


def test_the_fixture_stories_carry_the_new_keys_ac9_1() -> None:
    for row in json.loads(FIXTURE_TEXT)["stories"]:
        assert {"branch", "landed", "story_ci", "running"} <= set(row)


def test_a_span_carries_resumed_ac7_3() -> None:
    assert Span("developer", "s1", 1.0, resumed=True).as_dict()["resumed"] is True
    assert Span("developer", "s1", 1.0).as_dict()["resumed"] is False


def test_the_land_stage_is_listed_with_its_label_ac9_2() -> None:
    assert stages.Name.STORY_LAND.value == "story.land"
    assert "story" in stages.NAMESPACES


def test_new_event_kinds_exist() -> None:
    for name in ("STORY_BRANCH", "STORY_LANDED", "STORY_CI"):
        assert hasattr(EventKind, name)
    assert EventKind.STORY_LANDED == "story-landed" and EventKind.STORY_CI == "story-ci"
