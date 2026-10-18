"""s159: config keys story_prefix, max_open_stories, step_reserve_usd; land last; run_home."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import config as cfg

KNOWN = cfg.Known({"developer"}, {"package", "web", "harness"})


def problems(repo: Path, raw: dict, prefix: str) -> list[str]:
    c = cfg.from_raw(repo, raw)
    return [p for p in cfg.validate(c, KNOWN) if p.startswith(prefix)]


def test_story_prefix_default(repo: Path) -> None:
    """s159 spec: story prefix default."""
    assert cfg.from_raw(repo, {}).upstream.story_prefix == "team/story-"
    assert problems(repo, {}, "upstream") == []


@pytest.mark.parametrize("bad", ["-x", "a b", ""])
def test_story_prefix_must_be_a_branch_name(repo: Path, bad: str) -> None:
    """s159 spec: story prefix must be a branch name."""
    got = problems(repo, {"upstream": {"story_prefix": bad}}, "upstream")
    assert "upstream.story_prefix must be a branch name prefix" in got


@pytest.mark.parametrize(
    "u",
    [
        {"prefix": "t/x-", "story_prefix": "t/x-"},
        {"prefix": "t/x-", "story_prefix": "t/x-story-"},
        {"prefix": "t/x-story-", "story_prefix": "t/x-"},
    ],
)
def test_story_prefix_apart_from_prefix(repo: Path, u: dict) -> None:
    """s159 spec: story prefix apart from prefix."""
    got = problems(repo, {"upstream": u}, "upstream")
    assert (
        "upstream.story_prefix must differ from upstream.prefix, and neither may start "
        "with the other" in got
    )


def test_team_defaults(repo: Path) -> None:
    """s159 spec: team defaults."""
    team = cfg.from_raw(repo, {}).team
    assert team.max_open_stories == 5 and team.step_reserve_usd == 1.0


@pytest.mark.parametrize("bad", [0, 1.5, True, -1])
def test_max_open_stories_rejected(repo: Path, bad) -> None:
    """s159 spec: max open stories rejected."""
    got = problems(repo, {"team": {"max_open_stories": bad}}, "team")
    assert "team.max_open_stories must be an integer of at least 1" in got


@pytest.mark.parametrize("ok", [1, 5])
def test_max_open_stories_accepted(repo: Path, ok: int) -> None:
    """s159 spec: max open stories accepted."""
    assert problems(repo, {"team": {"max_open_stories": ok}}, "team.max_open") == []


@pytest.mark.parametrize("bad", [-1, 10.0])
def test_step_reserve_rejected(repo: Path, bad: float) -> None:
    """s159 spec: step reserve rejected."""
    raw = {"team": {"budget_usd": 10.0, "step_reserve_usd": bad}}
    assert "team.step_reserve_usd must be at least 0 and below team.budget_usd" in problems(
        repo, raw, "team"
    )


def test_step_reserve_zero_is_fine(repo: Path) -> None:
    """s159 spec: step reserve zero is fine."""
    raw = {"team": {"budget_usd": 10.0, "step_reserve_usd": 0}}
    assert problems(repo, raw, "team.step_reserve") == []


def test_land_is_always_the_last_step(repo: Path) -> None:
    """s159 spec: land is always the last step."""
    for listed in (["design", "implement", "acceptance"], ["design", "implement"], []):
        assert cfg.pipeline_steps(listed)[-1] == "land"


def test_land_is_listed_after_acceptance() -> None:
    """s159 spec: land is listed after acceptance."""
    steps = cfg.pipeline_steps(["design", "implement", "acceptance"])
    assert steps.index("land") == steps.index("acceptance") + 1


def test_land_cannot_be_removed_by_config() -> None:
    """s159 spec: land cannot be removed by config."""
    assert "land" in cfg.pipeline_steps(["design"])
    assert ("land", cfg.LAST) in cfg.ALWAYS_STEPS


def test_run_dir_follows_run_home(repo: Path) -> None:
    """s159 spec: run dir follows run home."""
    c = cfg.from_raw(repo, {})
    worktree = repo / ".team/run/worktrees/s1"
    at = c.at_worktree(worktree)
    assert at.repo == worktree
    assert at.run_dir == c.run_dir == repo / ".team/run"
