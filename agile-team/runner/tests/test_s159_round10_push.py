"""s159 round-9 review S1b: the push rows of upstream and story_ci that no test reached."""

from __future__ import annotations

import asyncio

import pytest
from agile_team import upstream as up

from .fake_system import Done, FakeSystem
from .s29_helpers import FakePrs
from .test_s159_round7 import HEAD, SPRINT_HEAD, Upstream, pusher_for, story_of
from .test_upstream import BASE, NO_RENAMES, OLD, TARGET_SHA, upstream_for


def test_confirm_kept_raises_sync_lost_naming_the_paths_s1b(fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base"), Done(0, BASE + "\n"))
    fake.reply((*NO_RENAMES, OLD, "HEAD"), Done(0, "a.py\n"))
    fake.reply((*NO_RENAMES, "origin/main", "HEAD"), Done(0, ""))
    with pytest.raises(up.UpstreamError, match=r"a\.py"):
        upstream_for().confirm_kept(up.Spans(OLD, OLD, TARGET_SHA))


def test_confirm_kept_is_quiet_when_nothing_is_lost_s1b(fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base"), Done(0, BASE + "\n"))
    upstream_for().confirm_kept(up.Spans(OLD, OLD, TARGET_SHA))


def test_reset_team_branch_refuses_a_moved_branch_and_does_not_reset_s1b(
    fake: FakeSystem,
) -> None:
    fake.reply(("rev-parse", "HEAD"), Done(0, "c" * 40 + "\n"))
    with pytest.raises(up.UpstreamError):
        upstream_for().reset_team_branch(OLD, "f" * 40)
    assert not [c for c in fake.commands if "reset" in c.argv]


def test_reset_team_branch_resets_to_the_sha_when_unmoved_s1b(fake: FakeSystem) -> None:
    fake.reply(("rev-parse", "HEAD"), Done(0, OLD + "\n"))
    upstream_for().reset_team_branch(OLD, "f" * 40)
    [reset] = [c.argv for c in fake.commands if "reset" in c.argv]
    assert tuple(reset[-2:]) == ("--keep", "f" * 40)


def test_a_refused_sprint_branch_push_stops_the_story_push_s1b(make_runtime, monkeypatch) -> None:
    rt, story, entry, _ = pusher_for(make_runtime, monkeypatch, refusal="stale info")
    entry.pushed = ""
    from agile_team.story_ci import StoryPusher

    assert asyncio.run(StoryPusher(rt).push_off_loop(story)) is None
    assert [lease.branch for lease in rt.upstream.leases] == ["team/sprint-1"]
    assert story.pushed == "" and story.pr is None


def test_after_step_stops_when_the_sprint_branch_push_is_refused_s1b(make_runtime) -> None:
    from agile_team.boundary import Permission, StackEntry
    from agile_team.story_ci import StoryPusher

    rt = make_runtime(prs=FakePrs())
    rt.state.sprint = 1
    rt.state.upstream.push = Permission.YES
    entry = StackEntry(1, "team/sprint-1", SPRINT_HEAD, "", head=SPRINT_HEAD)
    rt.state.upstream.stack = [entry]
    rt.upstream = Upstream("stale info")
    story = story_of(branch="team/story-s1", worktree_head=HEAD)
    assert StoryPusher(rt).push_moved_head(story) is None
    assert len(rt.upstream.leases) == 1 and story.pr is None


def replayed(make_runtime, old_pr):
    from agile_team.boundary import Permission, StackEntry
    from agile_team.story_ci import StoryPusher

    rt = make_runtime(prs=FakePrs())
    rt.state.sprint = 1
    rt.state.upstream.push = Permission.YES
    rt.state.upstream.stack = [
        StackEntry(1, "team/sprint-1", SPRINT_HEAD, SPRINT_HEAD, head=SPRINT_HEAD)
    ]
    rt.upstream = Upstream()
    story = story_of(branch="team/story-s1", worktree_head=HEAD)
    refused = StoryPusher(rt).push_replayed(story, old_pr)
    return rt, story, refused


def test_push_replayed_closes_the_old_pr_with_a_link_to_the_new_one_s1b(make_runtime) -> None:
    rt, story, refused = replayed(make_runtime, 7)
    assert refused is None and story.pr == 1
    [close] = [c for c in rt.prs.calls if c[0] == "close"]
    assert close[1] == 7 and "#1" in close[2]


def test_push_replayed_without_an_old_pr_closes_nothing_s1b(make_runtime) -> None:
    rt, _, _ = replayed(make_runtime, None)
    assert not [c for c in rt.prs.calls if c[0] == "close"]
