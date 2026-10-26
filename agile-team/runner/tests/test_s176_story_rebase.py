"""s176: the free branches' heads around a story rebase step, and the put-back and bounce."""

from __future__ import annotations

from pathlib import Path

from agile_team import dispatch, story_rebase, system
from agile_team.gates import Verdict
from agile_team.git_ops import Git
from agile_team.story_branches import StoryRebase
from agile_team.story_rebase import MovedBranch

from .conftest import handoff
from .fake_system import Done, FakeSystem
from .test_story_rebase_steps import (
    BASE,
    CONFLICTS,
    ONTO,
    REBASED,
    mid_rebase,
    rebase_plan,
    settle,
)

OLD, NEW, NEWER = "1" * 40, "2" * 40, "3" * 40
WORKTREE = Path("/fake/repo/wt")


def rebase_of(**kw: object) -> StoryRebase:
    rebase = StoryRebase(ONTO, BASE, "team/story-s1", REBASED, list(CONFLICTS), "developer-cli")
    for name, value in kw.items():
        setattr(rebase, name, value)
    return rebase


def listing(*rows: tuple[str, str, str]) -> Done:
    return Done(0, "".join(f"{name}\t{sha}\t{where}\n" for name, sha, where in rows))


def git_in_worktree() -> Git:
    system.make_dirs(WORKTREE)
    return Git(WORKTREE)


# ----- read_branch_heads (B7) -----------------------------------------------------


def test_the_snapshot_keeps_free_branches_and_the_step_worktrees_own(fake: FakeSystem) -> None:
    fake.reply(
        ("for-each-ref",),
        listing(
            (REBASED, OLD, str(WORKTREE)),
            ("free", OLD, ""),
            ("mine", NEW, str(WORKTREE)),
            ("elsewhere", NEW, "/fake/repo/other-wt"),
        ),
    )
    heads = story_rebase.read_branch_heads(git_in_worktree(), rebase_of())
    assert heads == {"free": OLD, "mine": NEW}


def test_the_snapshot_reads_the_local_branches_in_one_call(fake: FakeSystem) -> None:
    fake.reply(("for-each-ref",), listing())
    story_rebase.read_branch_heads(git_in_worktree(), rebase_of())
    calls = [c.argv for c in fake.commands if "for-each-ref" in c.argv]
    assert len(calls) == 1 and "refs/heads" in calls[0]


def test_an_empty_repo_gives_an_empty_snapshot(fake: FakeSystem) -> None:
    fake.reply(("for-each-ref",), listing())
    assert story_rebase.read_branch_heads(git_in_worktree(), rebase_of()) == {}


# ----- list_moved_branches and put_back_branch (B9) ------------------------------


def test_a_free_branch_that_moved_is_listed_with_both_shas(fake: FakeSystem) -> None:
    fake.reply(("for-each-ref",), listing(("free", NEW, ""), ("same", OLD, "")))
    rebase = rebase_of(heads={"free": OLD, "same": OLD})
    moved = story_rebase.list_moved_branches(git_in_worktree(), rebase)
    assert moved == [MovedBranch("free", OLD, NEW)]


def test_a_deleted_branch_or_one_checked_out_elsewhere_is_not_listed(fake: FakeSystem) -> None:
    fake.reply(("for-each-ref",), listing(("taken", NEW, "/fake/repo/other-wt")))
    rebase = rebase_of(heads={"gone": OLD, "taken": OLD})
    assert story_rebase.list_moved_branches(git_in_worktree(), rebase) == []


def test_nothing_moved_lists_nothing(fake: FakeSystem) -> None:
    fake.reply(("for-each-ref",), listing(("free", OLD, "")))
    assert story_rebase.list_moved_branches(git_in_worktree(), rebase_of(heads={"free": OLD})) == []


def test_put_back_restores_the_branch_guarded_by_its_new_sha(fake: FakeSystem) -> None:
    fake.reply(("update-ref",), Done(0))
    line = story_rebase.put_back_branch(git_in_worktree(), MovedBranch("free", OLD, NEW))
    assert line == story_rebase.BRANCH_MOVED.format(branch="free", old=OLD, new=NEW)
    argv = next(c.argv for c in fake.commands if "update-ref" in c.argv)
    assert argv[-3:] == ("refs/heads/free", OLD, NEW)
    assert story_rebase.PUT_BACK_MESSAGE in argv


def test_a_branch_that_moved_again_is_stuck(fake: FakeSystem) -> None:
    fake.reply(("update-ref",), Done(1, "", "cannot lock ref"))
    line = story_rebase.put_back_branch(git_in_worktree(), MovedBranch("free", OLD, NEW))
    assert line == story_rebase.BRANCH_STUCK.format(branch="free", old=OLD, new=NEW)


def test_a_story_rebase_remembers_no_heads_by_default() -> None:
    first, second = rebase_of(), rebase_of()
    first.heads["x"] = OLD
    assert second.heads == {}


def test_the_brief_tells_the_step_to_move_no_other_branch() -> None:
    brief = " ".join(story_rebase.STORY_REBASE_LINES)
    assert "Move no other branch" in brief and "{branch}" in brief


# ----- the dispatch side (B8, B9) ------------------------------------------------


def test_the_scope_gets_the_branch_and_a_fresh_snapshot(make_runtime, fake: FakeSystem) -> None:
    view, plan = rebase_plan(make_runtime)
    fake.reply(("symbolic-ref",), Done(0, REBASED + "\n"))
    fake.reply(("for-each-ref",), listing(("free", OLD, "")))
    view._set_story_rebase_scope(plan)
    assert plan.scope.git_branch == REBASED
    assert plan.story.rebase.heads == {"free": OLD}


def test_a_resumed_step_keeps_the_snapshot_from_before_the_cut_off(
    make_runtime, fake: FakeSystem
) -> None:
    view, plan = rebase_plan(make_runtime)
    plan.story.rebase.heads = {"free": OLD}
    fake.reply(("symbolic-ref",), Done(0, REBASED + "\n"))
    fake.reply(("for-each-ref",), listing(("free", NEW, "")))
    view._set_story_rebase_scope(plan)
    assert plan.story.rebase.heads == {"free": OLD}


def moved_during_the_step(view, plan, fake: FakeSystem) -> None:
    plan.story.rebase.heads = {"free": OLD}
    fake.reply(("for-each-ref",), listing(("free", NEW, "")))
    fake.reply(("update-ref",), Done(0))


def test_a_step_that_moved_a_free_branch_bounces_and_puts_it_back(
    make_runtime, fake: FakeSystem
) -> None:
    view, plan = rebase_plan(make_runtime)
    moved_during_the_step(view, plan, fake)
    fake.reply(("symbolic-ref",), Done(0, "team/story-s1\n"))
    gate = settle(view, plan, handoff("done", summary="resolved"))["gate"]
    assert gate["verdict"] == Verdict.BOUNCE
    assert "free" in gate["reason"] and OLD in gate["reason"] and NEW in gate["reason"]
    restored = [c.argv for c in fake.commands if "update-ref" in c.argv]
    assert restored and restored[0][-3:] == ("refs/heads/free", OLD, NEW)
    assert plan.story.rebase is not None and plan.story.rebase.heads == {}


def test_a_blocked_step_that_moved_a_branch_bounces_instead_of_holding(
    make_runtime, fake: FakeSystem
) -> None:
    view, plan = rebase_plan(make_runtime)
    mid_rebase(fake)
    moved_during_the_step(view, plan, fake)
    gate = settle(view, plan, handoff("blocked", summary="git add is denied"))["gate"]
    assert gate["verdict"] == Verdict.BOUNCE
    assert "free" in gate["reason"]
    assert plan.story.rebase is not None


def test_a_stuck_branch_still_bounces_with_the_stuck_reason(make_runtime, fake: FakeSystem) -> None:
    view, plan = rebase_plan(make_runtime)
    plan.story.rebase.heads = {"free": OLD}
    fake.reply(("for-each-ref",), listing(("free", NEW, "")))
    fake.reply(("update-ref",), Done(1, "", "cannot lock ref"))
    fake.reply(("symbolic-ref",), Done(0, "team/story-s1\n"))
    gate = settle(view, plan, handoff("done", summary="resolved"))["gate"]
    assert gate["verdict"] == Verdict.BOUNCE
    assert "moved again" in gate["reason"]


def test_a_step_that_moved_nothing_is_settled_as_before(make_runtime, fake: FakeSystem) -> None:
    view, plan = rebase_plan(make_runtime)
    plan.story.rebase.heads = {"free": OLD}
    mid_rebase(fake)
    fake.reply(("for-each-ref",), listing(("free", OLD, "")))
    gate = settle(view, plan, handoff("done", summary="ok"))["gate"]
    assert gate["verdict"] == Verdict.HOLD
    assert not [c for c in fake.commands if "update-ref" in c.argv]


def test_the_runtime_module_exposes_the_put_back_step() -> None:
    assert hasattr(dispatch.Runtime, "_put_back_moved")


# ----- R3, R5, R6 ----------------------------------------------------------------


def test_r5_a_symlinked_repo_keeps_the_worktrees_own_branch(fake: FakeSystem, monkeypatch) -> None:
    link = Path("/fake/repo/link")
    system.make_dirs(link)
    real = system.resolve
    monkeypatch.setattr(system, "resolve", lambda p: WORKTREE if p == link else real(p))
    fake.reply(("for-each-ref",), listing(("mine", NEW, str(WORKTREE))))
    assert story_rebase.read_branch_heads(Git(link), rebase_of()) == {"mine": NEW}


def test_r3_the_story_rebase_launch_env_pins_rebase_update_refs_off(
    make_runtime, fake: FakeSystem
) -> None:
    view, plan = rebase_plan(make_runtime)
    fake.reply(("symbolic-ref",), Done(0, REBASED + "\n"))
    fake.reply(("for-each-ref",), listing())
    view._set_story_rebase_scope(plan)
    env = plan.launch.env
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "rebase.updateRefs"
    assert env["GIT_CONFIG_VALUE_0"] == "false"


def test_r6_a_held_step_that_moved_nothing_ends_with_no_recorded_heads(
    make_runtime, fake: FakeSystem
) -> None:
    view, plan = rebase_plan(make_runtime)
    plan.story.rebase.heads = {"free": OLD}
    mid_rebase(fake)
    fake.reply(("for-each-ref",), listing(("free", OLD, "")))
    gate = settle(view, plan, handoff("blocked", summary="stuck"))["gate"]
    assert gate["verdict"] == Verdict.HOLD
    assert plan.story.rebase.heads == {}
