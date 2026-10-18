"""s159 round-2 review: N5 (boundary fix), R1 (push off the loop), R2 (Manager lock), N6, N7."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agile_team import system
from agile_team.boundary import StepKind
from agile_team.boundary_runner import Due
from agile_team.ci import Bucket, Check
from agile_team.gates import StoryState
from agile_team.git_ops import Git
from agile_team.po_tools import Start
from agile_team.router import Work

from .fake_system import FAKE_REPO, Done, FakeSystem
from .late import Late
from .s29_helpers import FakePrs

sched = Late("scheduler")
rp = Late("replay")
story_ci = Late("story_ci")
HEAD, NEWER, SHA = "b" * 40, "c" * 40, "d" * 40


def scheduler(make_runtime, *stories: StoryState):
    rt = make_runtime()
    rt.state.sprint = 1
    rt.state.stories = {s.id: s for s in stories}
    return rt, sched.Scheduler(rt, Start("task"))


def a_story(sid: str = "s1", **kw) -> StoryState:
    return StoryState(id=sid, title="t", step="implement", sprint=1, **kw)


# ---------- N5: a due boundary holds story steps but not its own fix ----------


def due_fix(s, kind: StepKind) -> None:
    due = Due(kind, "devops", "fix the boundary")
    s.router.boundaries.due = lambda: due  # type: ignore[method-assign]


def test_a_due_boundarys_own_devops_fix_is_not_held_n5(make_runtime) -> None:
    _, s = scheduler(make_runtime)
    for kind in (StepKind.TEAM_FIX, StepKind.REBASE_FIX):
        due_fix(s, kind)
        assert not s.is_held_by_boundary(Work("devops", None, "fix", kind))


def test_a_due_boundary_still_holds_a_story_step_n5(make_runtime) -> None:
    story = a_story()
    _, s = scheduler(make_runtime, story)
    due_fix(s, StepKind.TEAM_FIX)
    assert s.is_held_by_boundary(Work("developer-cli", story, "b", StepKind.ROLE))


def test_a_due_boundary_still_holds_a_storyless_non_fix_step_n5(make_runtime) -> None:
    _, s = scheduler(make_runtime)
    due_fix(s, StepKind.TEAM_FIX)
    assert s.is_held_by_boundary(Work("po", None, "b", StepKind.ROLE))


def test_start_work_starts_the_boundary_fix_and_not_the_story_step_n5(make_runtime) -> None:
    story = a_story()
    _, s = scheduler(make_runtime, story)
    due_fix(s, StepKind.REBASE_FIX)
    fix = Work("devops", None, "fix", StepKind.REBASE_FIX)
    step = Work("developer-cli", story, "b", StepKind.ROLE)
    s.router.works = lambda busy: [step, fix]  # type: ignore[method-assign]
    started: list[Work] = []
    s.start_one = lambda w: started.append(w) or True  # type: ignore[method-assign]
    s.start_work()
    assert started == [fix]


# ---------- R2: the Manager holds the main lock only around its settle ----------


def manager_dispatch(make_runtime, branches: bool) -> bool:
    """Whether the main lock was held while the Manager's role step ran."""
    rt, s = scheduler(make_runtime)
    rt.state.story_branches = branches
    seen: list[bool] = []

    async def run_role(request):
        seen.append(s.main_lock.locked())
        return {"status": "done"}

    rt.run_role = run_role  # type: ignore[method-assign]
    asyncio.run(s.dispatch(Work("manager", None, "review", StepKind.ROLE)))
    return seen[0]


def test_with_story_branches_the_manager_step_does_not_hold_the_lock_r2(make_runtime) -> None:
    assert manager_dispatch(make_runtime, True) is False


def test_before_the_switch_the_manager_step_holds_the_lock_r2(make_runtime) -> None:
    assert manager_dispatch(make_runtime, False) is True


# ---------- R1: the push runs through system.in_thread ----------


def test_the_story_push_runs_through_in_thread_r1(make_runtime, monkeypatch) -> None:
    rt, _ = scheduler(make_runtime)
    story = a_story()
    calls: list[str] = []

    async def in_thread(fn, *args):
        calls.append(getattr(fn, "__name__", repr(fn)))
        return fn(*args)

    monkeypatch.setattr(system, "in_thread", in_thread)

    pushed: list[str] = []

    async def push_off_loop(self, s) -> None:
        pushed.append(s.id)

    monkeypatch.setattr(story_ci.StoryPusher, "push_off_loop", push_off_loop)
    rt.worktree_of = story.id
    plan = SimpleNamespace(story=story)
    asyncio.run(rt.apply_settled(plan, {"status": "done"}))
    # C6: the loop thread runs the push flow; only its commands go through in_thread
    assert pushed == [story.id]
    assert "after_step" not in calls


# ---------- N6: the recorded sha is the sha that was read ----------


class MovingPrs(FakePrs):
    """Its ``sha_checks`` answers red, and the story pushes a newer head while it reads."""

    def __init__(self, story: StoryState) -> None:
        super().__init__()
        self.story = story

    def sha_checks(self, sha: str) -> list:
        self.story.pushed = NEWER
        return [Check("build", Bucket.FAIL, "ci")]


def test_story_ci_records_the_sha_it_read_not_a_newer_head_n6(make_runtime) -> None:
    story = a_story(pushed=HEAD)
    rt, _ = scheduler(make_runtime, story)
    rt.prs = MovingPrs(story)
    got = story_ci.StoryCiPoll(rt).poll(story, 1000.0)
    assert got is not None and got.sha == HEAD and story.ci.sha == HEAD


# ---------- N7: restore pops the story's own stash entry ----------


def stash_args(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands if "stash" in c.argv and "pop" in c.argv]


def test_restore_pops_the_entry_named_by_the_sha_not_the_top_n7(make_runtime, fake) -> None:
    rt, _ = scheduler(make_runtime)
    # `git stash list --format=%H`: one commit sha per line, newest first
    fake.reply(("stash", "list"), Done(0, f"{NEWER}\n{SHA}\n"))
    stashed = rp.Stash("s1", True, SHA)
    rp.StoryReplay(rt).restore_edits(Git(FAKE_REPO), stashed)
    [argv] = stash_args(fake)
    assert argv != ("git", "stash", "pop") and argv[-1] == "stash@{1}"


def test_restore_keeps_the_stash_when_its_entry_is_gone_n7(make_runtime, fake) -> None:
    rt, _ = scheduler(make_runtime)
    fake.reply(("stash", "list"), Done(0, f"{NEWER}\n"))
    rp.StoryReplay(rt).restore_edits(Git(FAKE_REPO), rp.Stash("s1", True, SHA))
    assert stash_args(fake) == []
