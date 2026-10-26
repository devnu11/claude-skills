"""e2e: a finished story rebase is settled without a new commit, with real git (s182).

Real git in ``tmp_path`` through the runner's own ``_settle_step_tree`` and ``_apply_rebase``:
AC1/AC2 (set aside and fold into the tip), AC3 (advance refused while a rebase is queued) and
AC4 (a renumbering conflict resolved by hand is adopted).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agile_team import dispatch, guard, story_rebase
from agile_team.dispatch import Plan, Runtime
from agile_team.gates import StoryState
from agile_team.git_ops import Git
from agile_team.roles import Handoff, RoleBook
from agile_team.router import Router
from agile_team.story_branches import StoryRebase

from ..conftest import git, set_git_identity

BRANCH, REBASED = "team/story-s1", "team/story-s1-r1"
REQ = "agile-team/docs/requirements"


def commit(repo: Path, files: dict[str, str], message: str, author: str = "") -> str:
    """Write ``files``, commit them (as ``author`` when given) and return the sha."""
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git(repo, "add", "-A")
    extra = ["--author", f"{author} <{author}@example.com>"] if author else []
    git(repo, "commit", "-q", "-m", message, *extra)
    return git(repo, "rev-parse", "HEAD").strip()


def head(repo: Path) -> str:
    """The sha at HEAD."""
    return git(repo, "rev-parse", "HEAD").strip()


def queue(repo: Path, story_files: dict[str, str], main_files: dict[str, str]) -> StoryRebase:
    """Story branch with two commits, a newer main, and the story rebase queued onto it."""
    set_git_identity(repo)
    main = git(repo, "branch", "--show-current").strip()
    base = commit(repo, {"a.py": "1\n2\n3\n", "other.txt": "o\n"}, "setup")
    git(repo, "checkout", "-q", "-b", BRANCH)
    commit(repo, {"a.py": "1\nstory\n3\n", **story_files}, "story one", author="Ann")
    old = commit(repo, {"c.py": "c\n"}, "story two", author="Ann")
    git(repo, "checkout", "-q", main)
    onto = commit(repo, {"m.txt": "m\n", **main_files}, "main moves")
    git(repo, "checkout", "-q", "-b", REBASED, BRANCH)
    return StoryRebase(onto, base, old, REBASED, ["a.py", "c.py"], "developer-cli")


def run_rebase(repo: Path, rebase: StoryRebase) -> None:
    """Rebase the story branch onto ``onto``; it may stop where git cannot go on alone."""
    Git(repo).attempt("rebase", rebase.onto)


def finish(repo: Path) -> None:
    """Continue the rebase without opening an editor."""
    git(repo, "add", "-A")
    Git(repo, ("-c", "core.editor=true")).run("rebase", "--continue")


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[StoryState]:
    """Replace the push-and-replay step of adoption; record the stories that took the branch."""
    taken: list[StoryState] = []
    monkeypatch.setattr(Runtime, "_take_rebase", lambda self, story, rebase: taken.append(story))
    return taken


def plan_for(make_runtime, rebase: StoryRebase, write: list[str]) -> tuple[Runtime, Plan]:
    """A runtime whose git is the repo (as a story worktree) and a rebase-step plan."""
    rt = make_runtime()
    story = StoryState("s1", "t", "land", sprint=1, branch=BRANCH, base_sha=rebase.base)
    story.rebase = rebase
    rt.state.stories["s1"] = story
    rt.worktree_of = "s1"
    role = RoleBook.for_repo(rt.config.repo, {}).resolve("developer-cli")
    scope = guard.Scope("developer-cli", rt.config.repo, write)
    return rt, Plan(role, scope, story, kind=dispatch.StepKind.STORY_REBASE)


def settle(rt: Runtime, plan: Plan) -> dict[str, Any]:
    """The runner's settle of the finished step."""
    return rt._settle_step_tree(plan, Handoff("done"))


def test_ac1_ac2_settle_sets_aside_and_folds_into_the_replayed_tip(
    make_runtime, configured, seen
) -> None:
    """Out-of-scope edits go to a ref, the in-scope edit joins the tip, no commit is added."""
    rebase = queue(configured, {}, {})
    run_rebase(configured, rebase)
    rt, plan = plan_for(make_runtime, rebase, ["a.py", "c.py"])
    tip = head(configured)
    (configured / "c.py").write_text("c\nedited\n")
    (configured / "other.txt").write_text("changed\n")
    (configured / "junk.txt").write_text("junk\n")
    report = settle(rt, plan)
    ref = report["set_aside"]["ref"]
    assert sorted(report["set_aside"]["paths"]) == ["junk.txt", "other.txt"]
    aside = git(configured, "show", "--name-only", "--format=", ref).split()
    assert sorted(aside) == ["junk.txt", "other.txt"]
    assert (configured / "other.txt").read_text() == "o\n"
    assert not (configured / "junk.txt").exists()
    assert (configured / "c.py").read_text() == "c\nedited\n"
    assert git(configured, "status", "--porcelain").strip() == ""
    assert git(configured, "log", "-1", "--format=%s|%an").strip() == "story two|Ann"
    assert git(configured, "rev-list", "--count", f"{rebase.onto}..HEAD").strip() == "2"
    assert head(configured) != tip and rebase.made == [head(configured)]
    assert report["folded"]["paths"] == ["c.py"]
    assert story_rebase.find_refusal(rt.git, rebase) is None
    assert rt._apply_rebase(plan, Handoff("done")) == {
        "rebased": {"branch": BRANCH, "onto": rebase.onto}
    }
    assert seen == [plan.story]


def test_ac1_a_tip_the_role_added_is_never_amended(make_runtime, configured) -> None:
    """The role adds a commit and leaves an edit: nothing is folded, the dirty file is named."""
    rebase = queue(configured, {}, {})
    run_rebase(configured, rebase)
    rt, plan = plan_for(make_runtime, rebase, ["a.py", "c.py"])
    extra = commit(configured, {"c.py": "role\n"}, "role adds this")
    (configured / "a.py").write_text("leftover\n")
    assert not story_rebase.is_foldable(rt.git, rebase)
    report = settle(rt, plan)
    assert "folded" not in report and rebase.made == [] and head(configured) == extra
    refusal = story_rebase.find_refusal(rt.git, rebase)
    assert refusal and "a.py" in refusal
    assert (configured / "a.py").read_text() == "leftover\n"


def test_ac3_commits_refusal_lists_sha_subject_and_who_made_it(make_runtime, configured) -> None:
    """A commit the role added is listed by short sha and subject, marked as the role's."""
    rebase = queue(configured, {}, {})
    run_rebase(configured, rebase)
    extra = commit(configured, {"c.py": "role\n"}, "role adds this")
    refusal = story_rebase.find_refusal(Git(configured), rebase)
    assert refusal and f"extra {extra[:12]} role adds this (made by the role)" in refusal
    assert "the role" in refusal


def test_ac4_a_renumbered_requirement_is_adopted(make_runtime, configured, seen) -> None:
    """A REQ id taken on main is renumbered by hand; the finished rebase checks out."""
    mine, taken = f"{REQ}/REQ-005.md", f"{REQ}/REQ-006.md"
    rebase = queue(configured, {mine: "story req\n"}, {mine: "main req\n"})
    rebase.files = [mine, taken, "a.py", "c.py"]
    rt, plan = plan_for(make_runtime, rebase, rebase.files)
    run_rebase(configured, rebase)
    assert story_rebase.find_unfinished(rt.git)
    (configured / taken).write_text("story req\n")
    git(configured, "checkout", "--ours", mine)
    finish(configured)
    assert story_rebase.find_unfinished(rt.git) is None
    report = settle(rt, plan)
    assert report == {"commit": None, "quarantine": None}
    assert story_rebase.find_refusal(rt.git, rebase) is None
    assert (configured / mine).read_text() == "main req\n"
    assert (configured / taken).read_text() == "story req\n"
    assert rt._apply_rebase(plan, Handoff("done"))["rebased"]["onto"] == rebase.onto
    assert seen == [plan.story]


def test_ac3_advance_through_dispatch_leaves_a_queued_rebase_alone(
    make_runtime, configured
) -> None:
    """The Manager's advance is refused; the step and the rebase stay, and the next pick is it."""
    rebase = queue(configured, {}, {})
    rt, plan = plan_for(make_runtime, rebase, ["a.py"])
    plan.story.step = rt.pipeline.steps[0]
    step = plan.story.step
    report = rt._rule(plan, Handoff("done", ruling="advance"))["ruling"]
    assert report["applied"] is False and rebase.onto in report["why"]
    assert plan.story.step == step and plan.story.rebase is rebase
    work = Router(rt)._pick_work(plan.story)
    assert work.kind is dispatch.StepKind.STORY_REBASE and work.role == "developer-cli"
