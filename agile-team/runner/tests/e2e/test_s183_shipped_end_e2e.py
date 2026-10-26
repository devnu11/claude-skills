"""s183 end to end on real git: does the target already hold the sprint head (AC1, AC3)?"""

from __future__ import annotations

from pathlib import Path

import pytest

from ..conftest import git
from .test_s59_rebase_e2e import World, make_world


@pytest.fixture
def repos(tmp_path: Path) -> World:
    return make_world(tmp_path)


def sprint_head(world: World) -> tuple[str, str]:
    """Two sprint commits on the team clone; return (first, head)."""
    first = world.commit(world.team, "src/a.txt", "a\n", "sprint one")
    return first, world.commit(world.team, "src/b.txt", "b\n", "sprint two")


def fast_forward_main(world: World, sha: str) -> None:
    """Move origin/main to ``sha`` as a human fast-forward merge does."""
    git(world.team, "push", "-q", "origin", f"{sha}:refs/heads/main")
    git(world.team, "fetch", "-q", "origin")


def test_ac1_a_main_fast_forwarded_to_the_head_already_holds_it(repos: World) -> None:
    _, head = sprint_head(repos)
    fast_forward_main(repos, head)
    assert repos.upstream().is_in_target(head) is True


def test_ac3_a_main_holding_only_part_of_the_sprint_does_not_hold_the_head(repos: World) -> None:
    first, head = sprint_head(repos)
    fast_forward_main(repos, first)
    assert repos.upstream().is_in_target(head) is False


def test_ac3_an_untouched_main_does_not_hold_the_head(repos: World) -> None:
    _, head = sprint_head(repos)
    assert repos.upstream().is_in_target(head) is False
