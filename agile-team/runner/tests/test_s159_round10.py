"""s159 round-9 review: tests for the locks (T3, T4) and the runner note (N8, N3)."""

from __future__ import annotations

import asyncio

from agile_team import system
from agile_team.dispatch import MANAGER
from agile_team.router import _history_lines
from agile_team.story_ci import StoryPusher

from .fake_system import Done
from .test_s159_round7 import HEAD, SHA, SPRINT_HEAD, plan_of, pusher_for, rp, story_of


def test_two_stories_push_the_sprint_branch_once_even_when_threads_interleave_t3(
    make_runtime, monkeypatch
) -> None:
    rt, story, entry, _ = pusher_for(make_runtime, monkeypatch)
    other = story_of("s2", branch="team/story-s2", worktree_head=HEAD)

    async def yielding(fn, *args):
        await asyncio.sleep(0)
        return fn(*args)

    monkeypatch.setattr(system, "in_thread", yielding)

    async def both() -> None:
        pusher = StoryPusher(rt)
        await asyncio.gather(pusher.push_off_loop(story), pusher.push_off_loop(other))

    asyncio.run(both())
    branches = [lease.branch for lease in rt.upstream.leases]
    assert branches.count("team/sprint-1") == 1 and entry.pushed == SPRINT_HEAD
    assert "team/story-s1" in branches and "team/story-s2" in branches
    assert story.pr is not None and other.pr is not None and story.pr != other.pr


def locked_during_settle(make_runtime, role: str) -> list[bool]:
    rt = make_runtime()
    rt.main_lock = asyncio.Lock()
    rt.state.story_branches = True
    seen: list[bool] = []

    def settle(plan, result):
        seen.append(rt.main_lock.locked())
        return {}

    rt.settle = settle  # type: ignore[method-assign]
    asyncio.run(rt.settle_work(plan_of(None, role=role), None))
    return seen


def test_settle_work_holds_the_main_lock_for_the_manager_only_t4(make_runtime) -> None:
    assert locked_during_settle(make_runtime, MANAGER) == [True]
    assert locked_during_settle(make_runtime, "developer-cli") == [False]


def kept_stash(make_runtime, monkeypatch, fake):
    rt = make_runtime()
    story = story_of("s1")
    rt.state.stories["s1"] = story
    posted: list = []
    monkeypatch.setattr(rt.relay, "post", posted.append)
    fake.reply(("stash", "list"), Done(0, f"{SHA}\n"))
    fake.reply(("stash", "pop"), Done(1, "conflict"))
    from agile_team.git_ops import Git

    from .fake_system import FAKE_REPO

    rp.StoryReplay(rt).restore_edits(Git(FAKE_REPO), rp.Stash("s1", True, SHA))
    return rt, story, posted


def test_a_failed_pop_resets_and_tells_the_po_and_the_next_brief_n3_n8(
    make_runtime, monkeypatch, fake
) -> None:
    _, story, posted = kept_stash(make_runtime, monkeypatch, fake)
    argvs = [tuple(c.argv) for c in fake.commands]
    assert any(a[-2:] == ("reset", "--hard") for a in argvs)
    assert any("clean" in a for a in argvs)
    assert story.runner_note and SHA in story.runner_note
    assert [n.text for n in posted] == [story.runner_note]
    assert f"- From the runner: {story.runner_note}" in _history_lines(story)


def test_the_runner_note_is_cleared_when_the_next_step_lands_n8(make_runtime) -> None:
    rt = make_runtime()
    story = story_of("s1")
    story.runner_note = "said"
    rt._land(plan_of(story))
    assert story.runner_note == ""
    assert not any("From the runner" in line for line in _history_lines(story))
