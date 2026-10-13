"""e2e: the sprint-start sync reports that main moved and changes nothing (s108, AC5).

Real git in ``tmp_path``: a bare origin, a team clone and a clone that pushes to main.
"""

from __future__ import annotations

from ..conftest import git
from .test_s59_rebase_e2e import make_world


def test_behind_counts_main_commits_and_the_team_branch_is_untouched(tmp_path):
    world = make_world(tmp_path)
    mine = world.commit(world.team, "src/mine.txt", "x\n", "team work")
    world.commit(world.other, "src/other.txt", "y\n", "main moved")
    world.commit(world.other, "src/other2.txt", "z\n", "main moved again")
    world.push_main()
    up = world.upstream()
    assert up.behind() == 2
    assert git(world.team, "rev-parse", "HEAD").strip() == mine
    assert git(world.team, "status", "--porcelain").strip() == ""


def test_behind_is_zero_when_main_has_not_moved(tmp_path):
    world = make_world(tmp_path)
    world.commit(world.team, "src/mine.txt", "x\n", "team work")
    assert world.upstream().behind() == 0
