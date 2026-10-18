"""s159: story_prefix, max_open_stories, step_reserve_usd, the land step, run_home."""

from pathlib import Path

import pytest
from agile_team import config as cfg

KNOWN = cfg.Known({"developer"}, {"package", "web", "harness"})


def problems(repo: Path, raw: dict) -> str:
    return "\n".join(cfg.validate(cfg.from_raw(repo, raw), KNOWN))


def test_defaults(repo: Path) -> None:
    c = cfg.from_raw(repo, {})
    assert c.upstream.story_prefix == "team/story-"
    assert c.team.max_open_stories == 5
    assert c.team.step_reserve_usd == 1.0


def test_story_prefix_loads(repo: Path) -> None:
    c = cfg.from_raw(repo, {"upstream": {"story_prefix": "wip/s-"}})
    assert c.upstream.story_prefix == "wip/s-"


def test_story_prefix_unsafe(repo: Path) -> None:
    text = problems(repo, {"upstream": {"story_prefix": "bad prefix;"}})
    assert "upstream.story_prefix must be a branch name prefix" in text


@pytest.mark.parametrize("story_prefix", ["team/sprint-", "team/sprint-x-", "team/"])
def test_story_prefix_must_stand_apart_from_prefix(repo: Path, story_prefix: str) -> None:
    text = problems(repo, {"upstream": {"story_prefix": story_prefix}})
    assert "upstream.story_prefix must differ from upstream.prefix" in text


def test_story_prefix_apart_is_fine(repo: Path) -> None:
    text = problems(repo, {"upstream": {"prefix": "team/sprint-", "story_prefix": "team/story-"}})
    assert "story_prefix" not in text


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_max_open_stories_refused(repo: Path, value: object) -> None:
    text = problems(repo, {"team": {"max_open_stories": value}})
    assert "team.max_open_stories must be an integer of at least 1" in text


@pytest.mark.parametrize("value", [1, 5, 40])
def test_max_open_stories_accepted(repo: Path, value: int) -> None:
    assert "max_open_stories" not in problems(repo, {"team": {"max_open_stories": value}})


@pytest.mark.parametrize("value", [-1, 10.0, 11.0])
def test_step_reserve_refused(repo: Path, value: float) -> None:
    raw = {"team": {"budget_usd": 10.0, "step_reserve_usd": value}}
    text = problems(repo, raw)
    assert "team.step_reserve_usd must be at least 0 and below team.budget_usd" in text


@pytest.mark.parametrize("value", [0, 0.5, 9.99])
def test_step_reserve_accepted(repo: Path, value: float) -> None:
    raw = {"team": {"budget_usd": 10.0, "step_reserve_usd": value}}
    assert "step_reserve_usd" not in problems(repo, raw)


def test_land_is_the_last_step_after_acceptance() -> None:
    assert cfg.pipeline_steps(["design", "acceptance", "implement"])[-1] == "land"
    assert cfg.pipeline_steps(["design", "implement", "acceptance"])[-2:] == ["acceptance", "land"]


def test_land_is_last_without_acceptance_and_cannot_be_removed() -> None:
    steps = cfg.pipeline_steps(["design", "implement", "land", "tests"])
    assert steps[-1] == "land" and steps.count("land") == 1
    assert "land" in cfg.pipeline_steps([])


def test_last_anchor_means_the_end() -> None:
    assert ("land", cfg.LAST) in cfg.ALWAYS_STEPS
    assert cfg.PIPELINE_STEPS[-1] == "land"


def test_ops_review_still_follows_design() -> None:
    steps = cfg.pipeline_steps(["design", "tests"])
    assert steps.index("ops-review") == steps.index("design") + 1


def test_run_dir_follows_run_home(repo: Path) -> None:
    c = cfg.from_raw(repo, {})
    assert c.run_home is None and c.run_dir == repo / ".team/run"
    worktree = repo / ".team/run/worktrees/s1"
    at = c.at_worktree(worktree)
    assert at.repo == worktree
    assert at.run_dir == repo / ".team/run"
    assert c.repo == repo
