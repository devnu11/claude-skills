"""e2e: the fast restack on real git after a rebase-merge (s108, AC4).

A bare origin, a team clone and a clone that plays GitHub landing rebased copies
(new committer dates, same trees) on main. The ``Rebuilder`` and ``Restacker`` run
for real in a review worktree under ``tmp_path``. The over-100-commits note is pure
arithmetic and stays a unit test.
"""

from __future__ import annotations

from pathlib import Path

from agile_team.boundary import StackEntry
from agile_team.git_ops import Git
from agile_team.restack import REBASE_STOPPED, TREE_CHANGED, Restacker
from agile_team.stack import Move, Rebuilder
from agile_team.upstream import Pr, PrState

from ..s29_helpers import FakePrs
from .test_s59_rebase_e2e import World, make_world

TARGET = "origin/main"


def rev(repo: Path, ref: str) -> str:
    """The sha of ``ref``."""
    return Git(repo).run("rev-parse", ref).strip()


def stack_of(world: World) -> tuple[list[StackEntry], str]:
    """Two sprints on the team clone (a.txt, then b.txt) and the old main tip."""
    base = rev(world.team, "HEAD")
    a = world.commit(world.team, "a.txt", "a\n", "A")
    b = world.commit(world.team, "b.txt", "b\n", "B")
    low = StackEntry(10, "team/sprint-10", base, a, head=a, pr=1)
    high = StackEntry(11, "team/sprint-11", a, b, head=b, pr=2)
    return [low, high], base


def land_bottom(world: World, entry: StackEntry) -> None:
    """Rebase-merge the bottom sprint's commit on main, as GitHub does."""
    world.copy_to_main([entry.end])
    world.push_main()


def restacker(world: World, tmp_path: Path, prs: FakePrs | None = None) -> Restacker:
    """A Restacker over a real Rebuilder on the team clone."""
    return Restacker(prs or FakePrs(), Rebuilder(Git(world.team), tmp_path / "review", TARGET))


def test_restack_after_rebase_merge_keeps_the_tree(tmp_path, isolated_git):
    world = make_world(tmp_path)
    (low, high), old_main = stack_of(world)
    land_bottom(world, low)
    prs = FakePrs()
    prs.prs[low.branch] = Pr(1, "u", PrState.MERGED, False, "main")
    prs.prs[high.branch] = Pr(2, "u", PrState.OPEN, False, low.branch)
    r = restacker(world, tmp_path, prs)
    assert r.merged([low, high]) == [low]
    below = r.rebuilder.merge_base(low.head)
    assert below == old_main
    plan = r.plan([high], below)
    assert plan.refused == "" and plan.emptied == []
    (new,) = plan.heads
    assert new != high.head
    assert r.rebuilder.same_tree(new, high.head)
    assert Git(world.team).attempt("merge-base", "--is-ancestor", TARGET, new)[0] == 0
    assert r.rebuilder.count(TARGET, new) == 1


def test_a_conflicting_rebase_returns_none_and_leaves_no_rebase(tmp_path, isolated_git):
    world = make_world(tmp_path)
    base = rev(world.team, "HEAD")
    mine = world.commit(world.team, "src/f.txt", "1\nmine\n3\n", "mine")
    world.commit(world.other, "src/f.txt", "1\ntheirs\n3\n", "theirs")
    world.push_main()
    rb = Rebuilder(Git(world.team), tmp_path / "review", TARGET)
    rb.prepare()
    assert rb.rebase(mine, Move(TARGET, base)) is None
    assert rb.wt.attempt("rev-parse", "-q", "--verify", "REBASE_HEAD")[0] != 0
    assert not (tmp_path / "review" / ".git" / "rebase-merge").exists()


def test_main_gaining_an_unrelated_commit_refuses_the_plan(tmp_path, isolated_git):
    world = make_world(tmp_path)
    (low, high), _ = stack_of(world)
    land_bottom(world, low)
    world.commit(world.other, "c.txt", "c\n", "unrelated")
    world.push_main()
    r = restacker(world, tmp_path)
    plan = r.plan([high], r.rebuilder.merge_base(low.head))
    assert plan.heads == []
    assert plan.refused == TREE_CHANGED.format(branch=high.branch, onto=TARGET)
    assert rev(world.team, "refs/remotes/origin/main") == rev(world.origin, "main")


def test_a_stopped_rebase_is_refused_with_its_reason(tmp_path, isolated_git):
    world = make_world(tmp_path)
    base = rev(world.team, "HEAD")
    mine = world.commit(world.team, "src/f.txt", "1\nmine\n3\n", "mine")
    world.commit(world.other, "src/f.txt", "1\ntheirs\n3\n", "theirs")
    world.push_main()
    entry = StackEntry(10, "team/sprint-10", base, mine, head=mine, pr=1)
    plan = restacker(world, tmp_path).plan([entry], base)
    assert plan.refused == REBASE_STOPPED.format(branch=entry.branch, onto=TARGET)
