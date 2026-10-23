"""The s159 story-rebase step in the runner: its git workspace, its settle and its push."""

from __future__ import annotations

from agile_team import dispatch, guard, system
from agile_team.dispatch import Plan
from agile_team.gates import StoryState
from agile_team.roles import RoleBook
from agile_team.story_branches import StoryRebase
from agile_team.workspaces import Workspaces

from .fake_system import Done, FakeSystem

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
