"""s115 e2e: the runner drives a story through design, ops-review and tests (AC1-AC5)."""

from __future__ import annotations

import functools

from agile_team import config as config_mod
from agile_team import story_spec
from agile_team.gates import StoryStatus

from ..conftest import handoff, write_story
from ..pipeline_helpers import Script, add_story, build, drive, step_roles

AUTO = {"ac": "AC1", "verdict": "automatic", "how": "pytest tests/e2e"}


def world(make_runtime, replies, listed=("design", "tests", "implement", "review")):
    script = Script({"devops": replies})
    rt = build(make_runtime, script, steps=config_mod.pipeline_steps(list(listed)))
    add_story(rt)
    write_story(rt.config, "s1", "cli")
    rt.pipeline.checks.story_spec = functools.partial(story_spec.read, rt.config)
    return rt, script


def test_ops_review_runs_after_design_though_not_listed(make_runtime) -> None:
    """AC1/AC2/AC4: devops reviews after design; its rows land in the story file."""
    rt, script = world(make_runtime, [handoff("done", tooling=[AUTO])])
    drive(rt)
    roles = step_roles(rt)
    assert roles[:2] == ["architect", "devops"]
    assert "## Ops review" in script.prompts["devops"][0]
    text = (rt.config.repo / ".team" / "stories" / "s1.md").read_text()
    assert "## Tooling" in text and "- AC1: automatic today: pytest tests/e2e" in text


def test_a_story_past_design_never_visits_ops_review(make_runtime) -> None:
    """AC1: a story already at tests is not sent back."""
    rt, _ = world(make_runtime, [])
    rt.state.stories["s1"].step = "tests"
    drive(rt)
    assert "devops" not in step_roles(rt)


def test_changes_requested_goes_back_to_the_architect(make_runtime) -> None:
    """AC3: the design assumes impossible tooling."""
    rt, _ = world(make_runtime, [handoff("changes_requested", summary="no such harness")])
    drive(rt)
    assert step_roles(rt)[:3] == ["architect", "devops", "architect"]


def test_unfiled_missing_row_holds_the_story(make_runtime) -> None:
    """AC3: a missing row with no story holds the story at ops-review."""
    row = {"ac": "AC1", "verdict": "missing", "needs": "a browser harness"}
    rt, _ = world(make_runtime, [handoff("done", tooling=[row])])
    drive(rt)
    story = rt.state.stories["s1"]
    assert story.hold == "gate_hold" and story.step == "ops-review"
    assert story.status is not StoryStatus.DONE
