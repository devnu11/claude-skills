"""The s159 story-rebase step in the runner: its git workspace, its settle and its push."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from agile_team import dispatch, guard, system
from agile_team.dispatch import Plan
from agile_team.gates import StoryState, Verdict
from agile_team.roles import RoleBook
from agile_team.story_branches import StoryRebase
from agile_team.story_ci import StoryPusher
from agile_team.workspaces import Workspaces

from .conftest import handoff
from .fake_system import Done, FakeSystem
from .test_s159_round7 import pusher_for

ONTO, BASE, OLD_TIP = "c" * 40, "b" * 40, "a" * 40
BRANCH, REBASED = "team/story-s1", "team/story-s1-r1"
CONFLICTS = ["src/app.py", "agile-team/docs/requirements/REQ-001.md"]


def rebasing_story() -> StoryState:
    story = StoryState("s1", "Title", "land", sprint=1, branch=BRANCH, base_sha=BASE)
    story.worktree_head = story.pushed = OLD_TIP
    story.rebase = StoryRebase(ONTO, BASE, BRANCH, REBASED, list(CONFLICTS), "developer-cli")
    return story


def rebase_plan(make_runtime) -> tuple[dispatch.Runtime, Plan]:
    rt = make_runtime()
    story = rebasing_story()
    rt.state.stories["s1"] = story
    view = rt.at(story)
    role = RoleBook.for_repo(rt.config.repo, {}).resolve("developer-cli")
    scope = guard.Scope("developer-cli", view.config.repo, [], [])
    return view, Plan(role, scope, story, kind=dispatch.StepKind.STORY_REBASE)


# ---------- A: the step's git runs in the story's worktree (s159 S2) ----------


def test_the_story_rebase_step_confines_git_to_the_story_worktree(make_runtime, fake) -> None:
    view, plan = rebase_plan(make_runtime)
    fake.reply(("symbolic-ref",), Done(0, REBASED + "\n"))
    view._set_story_rebase_scope(plan)
    worktree = Workspaces(view.main, view.config).path_of("s1")
    assert plan.scope.git_workspace == system.resolve(worktree)
    assert plan.scope.write == CONFLICTS


def test_the_story_rebase_step_may_add_and_continue_the_rebase(make_runtime, fake) -> None:
    view, plan = rebase_plan(make_runtime)
    fake.reply(("symbolic-ref",), Done(0, REBASED + "\n"))
    view._set_story_rebase_scope(plan)
    for command in ("git add src/app.py", "git rebase --continue"):
        assert guard.check_bash(plan.scope, command) is None, command


# ---------- B: an unfinished story rebase is left as it is (s159 S3) ----------

GIT_DIR = "/fake/repo/.git/worktrees/s1"


def mid_rebase(fake: FakeSystem, *changed: str) -> None:
    """The worktree stopped mid-rebase (detached), with ``changed`` edited."""
    fake.reply(("symbolic-ref",), Done(1, ""))
    fake.reply(("rev-parse", "--absolute-git-dir"), Done(0, GIT_DIR + "\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, ONTO + "\n"))
    fake.reply(("status", "--porcelain=v1"), Done(0, "".join(f" M {p}\0" for p in changed)))
    system.make_dirs(Path(GIT_DIR) / "rebase-merge")


def settle(view: dispatch.Runtime, plan: Plan, text: str) -> dict:
    return view.settle(plan, dispatch.StepResult(text, 0.1))


def git_writes(fake: FakeSystem) -> list[list[str]]:
    writes = ("commit", "add", "revert", "push")
    return [c.argv for c in fake.commands if c.argv[:1] == ("git",) and c.argv[1] in writes]


@pytest.mark.parametrize(
    "text",
    [
        handoff("blocked", summary="git add is denied"),
        handoff("failed", summary="gave up"),
        "no handoff at all",
        handoff("done", summary="resolved"),
    ],
    ids=["blocked", "failed", "bad_handoff", "done_but_unfinished"],
)
def test_an_unfinished_story_rebase_commits_nothing_and_holds(make_runtime, fake, text) -> None:
    view, plan = rebase_plan(make_runtime)
    mid_rebase(fake, "src/app.py", "docs/elsewhere.md")
    report = settle(view, plan, text)
    story = plan.story
    assert git_writes(fake) == []
    assert report["commit"] is None and report["quarantine"] is None
    assert story.worktree_head == OLD_TIP and story.branch == BRANCH
    assert story.rebase is not None and story.rebase.branch == REBASED
    assert report["gate"]["verdict"] == Verdict.HOLD
    assert "nothing was committed or pushed" in report["gate"]["reason"]


def test_a_held_story_rebase_says_why_it_stopped(make_runtime, fake) -> None:
    view, plan = rebase_plan(make_runtime)
    mid_rebase(fake)
    reason = settle(view, plan, handoff("done", summary="ok"))["gate"]["reason"]
    assert "rebase in progress" in reason and ONTO in reason and REBASED in reason


def test_a_finished_rebase_with_another_problem_still_bounces_a_round(make_runtime, fake) -> None:
    view, plan = rebase_plan(make_runtime)
    fake.reply(("symbolic-ref",), Done(0, BRANCH + "\n"))
    fake.reply(("rev-parse", "--absolute-git-dir"), Done(0, GIT_DIR + "\n"))
    report = settle(view, plan, handoff("done", summary="resolved"))
    assert report["gate"]["verdict"] == Verdict.BOUNCE
    assert REBASED in report["gate"]["reason"]


def test_a_story_with_a_pending_rebase_never_pushes(make_runtime, monkeypatch) -> None:
    rt, story, _, _ = pusher_for(make_runtime, monkeypatch)
    story.pushed, story.rebase = OLD_TIP, rebasing_story().rebase
    story.worktree_head = ONTO
    assert asyncio.run(StoryPusher(rt).push_off_loop(story)) is None
    assert StoryPusher(rt).after_step(story) is None
    assert rt.upstream.leases == [] and story.pushed == OLD_TIP
