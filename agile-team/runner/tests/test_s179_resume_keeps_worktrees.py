"""s179: a resume keeps the worktree of every open sprint story and removes only stale ones."""

from __future__ import annotations

import pytest
from agile_team import system
from agile_team.events import Event, EventKind
from agile_team.gates import StoryState, StoryStatus
from agile_team.salvage import Cause, InFlight
from agile_team.workspaces import PruneReason, find_prune_reason

from .fake_system import Done, FakeSystem

SHA = "a" * 40


def story(sid: str, **kw) -> StoryState:
    kw.setdefault("sprint", 1)
    return StoryState(sid, "T", "implement", worktree_head=SHA, **kw)


def resumed(make_runtime, *stories: StoryState):
    """A runtime in sprint 1 holding ``stories``, each with a worktree dir, then resumed."""
    rt = make_runtime()
    rt.state.sprint = 1
    rt.state.stories = {s.id: s for s in stories}
    for s in stories:
        system.make_dirs(rt.config.run_dir / "worktrees" / s.id)
    rt.recover_stories(Cause.CRASH)
    return rt


def removals(fake: FakeSystem) -> list[str]:
    return [" ".join(c.argv) for c in fake.commands if "worktree" in c.argv and "remove" in c.argv]


def pruned(rt) -> list:
    return [e for e in rt.events.events() if e.kind == EventKind.WORKTREE_PRUNED]


# ---------- find_prune_reason ----------


def test_an_open_story_in_the_sprint_has_no_prune_reason() -> None:
    assert find_prune_reason(story("s1"), 1) is None


@pytest.mark.parametrize("status", [StoryStatus.NEEDS_MANAGER, StoryStatus.BLOCKED])
def test_a_stuck_open_story_in_the_sprint_is_kept(status: StoryStatus) -> None:
    assert find_prune_reason(story("s1", status=status), 1) is None


def test_a_done_story_is_pruned_as_done() -> None:
    assert find_prune_reason(story("s1", status=StoryStatus.DONE), 1) == PruneReason.DONE


def test_a_cancelled_story_is_pruned_as_cancelled() -> None:
    assert find_prune_reason(story("s1", status=StoryStatus.CANCELLED), 1) == PruneReason.CANCELLED


def test_a_story_outside_the_sprint_is_pruned_as_not_in_sprint() -> None:
    assert find_prune_reason(story("s1", sprint=None), 1) == "not_in_sprint"
    assert find_prune_reason(story("s1", sprint=2), 1) == "not_in_sprint"


def test_a_worktree_with_no_story_is_pruned_as_unknown() -> None:
    assert find_prune_reason(None, 1) == "unknown"


def test_a_story_with_a_step_in_flight_is_never_pruned() -> None:
    flying = InFlight("architect", "s1", "brief")
    done = story("s1", status=StoryStatus.DONE, sprint=2, in_flight=flying)
    assert find_prune_reason(done, 1) is None


# ---------- AC1: the worktree stays ----------


def test_a_resume_keeps_the_worktree_of_an_idle_open_story_ac1(make_runtime, fake) -> None:
    rt = resumed(make_runtime, story("s1"), story("s2"))
    assert removals(fake) == []
    assert system.is_dir(rt.config.run_dir / "worktrees" / "s1")
    assert system.is_dir(rt.config.run_dir / "worktrees" / "s2")
    assert pruned(rt) == []


def test_the_next_step_adds_no_worktree_after_a_resume_ac1(make_runtime, fake) -> None:
    s1 = story("s1", branch="team/story-s1", base_sha=SHA)
    rt = resumed(make_runtime, s1)
    fake.reply(("symbolic-ref",), Done(0, "team/story-s1\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, SHA + "\n"))
    assert rt.prepare_story(s1) is None
    assert not [c for c in fake.commands if "worktree" in c.argv and "add" in c.argv]


# ---------- AC2: only stale ones go, each with an event ----------


def test_a_resume_removes_done_cancelled_and_unsprinted_worktrees_ac2(make_runtime, fake) -> None:
    rt = resumed(
        make_runtime,
        story("s1"),
        story("s2", status=StoryStatus.DONE),
        story("s3", status=StoryStatus.CANCELLED),
        story("s4", sprint=None),
    )
    root = rt.config.run_dir / "worktrees"
    assert system.is_dir(root / "s1")
    assert not any(system.exists(root / n) for n in ("s2", "s3", "s4"))
    assert len(removals(fake)) == 3


def test_each_removal_writes_one_event_naming_story_and_reason_ac2(make_runtime) -> None:
    rt = resumed(
        make_runtime,
        story("s1"),
        story("s2", status=StoryStatus.DONE),
        story("s3", status=StoryStatus.CANCELLED),
        story("s4", sprint=None),
    )
    got = {(e.story, e.data["worktree"], e.data["reason"]) for e in pruned(rt)}
    assert got == {
        ("s2", "s2", "done"),
        ("s3", "s3", "cancelled"),
        ("s4", "s4", "not_in_sprint"),
    }
    assert len(pruned(rt)) == 3
    assert all(e.role is None for e in pruned(rt))


def test_a_removed_story_worktree_head_is_cleared_ac2(make_runtime) -> None:
    rt = resumed(make_runtime, story("s1"), story("s2", status=StoryStatus.DONE))
    assert rt.state.stories["s1"].worktree_head == SHA
    assert rt.state.stories["s2"].worktree_head == ""


def test_a_kept_worktree_logs_no_event_ac2(make_runtime) -> None:
    rt = resumed(make_runtime, story("s1"), story("s2", status=StoryStatus.BLOCKED))
    assert pruned(rt) == []


def test_a_worktree_of_an_unknown_story_is_removed_with_an_event_ac2(make_runtime, fake) -> None:
    rt = make_runtime()
    rt.state.sprint = 1
    system.make_dirs(rt.config.run_dir / "worktrees" / "s9")
    rt.recover_stories(Cause.CRASH)
    assert [(e.story, e.data["reason"]) for e in pruned(rt)] == [("s9", "unknown")]
    assert pruned(rt)[0].data == {"worktree": "s9", "reason": "unknown"}
    assert len(removals(fake)) == 1


def test_land_and_replay_scratch_dirs_are_still_removed_ac2(make_runtime, fake) -> None:
    rt = make_runtime()
    rt.state.sprint = 1
    for name in ("land", "replay"):
        system.make_dirs(rt.config.run_dir / name)
    rt.recover_stories(Cause.CRASH)
    assert len(removals(fake)) == 2
    got = {(e.story, e.role, e.data["worktree"], e.data["reason"]) for e in pruned(rt)}
    assert got == {(None, None, "land", "scratch"), (None, None, "replay", "scratch")}


def test_a_cut_off_step_end_is_the_last_event_of_a_resume_ac2(make_runtime) -> None:
    rt = make_runtime()
    rt.state.sprint = 1
    flying = story("s1", in_flight=InFlight("architect", "s1", "brief"))
    rt.state.stories = {"s1": flying, "s2": story("s2", status=StoryStatus.DONE)}
    for sid in rt.state.stories:
        system.make_dirs(rt.config.run_dir / "worktrees" / sid)
    rt.events.emit(Event(EventKind.STEP_START, "architect", "s1", {"brief": "brief"}))
    rt.recover_stories(Cause.CRASH)
    kinds = [e.kind for e in rt.events.events()]
    assert EventKind.WORKTREE_PRUNED in kinds
    assert kinds[-1] == EventKind.STEP_END


def test_a_pinned_replay_dir_is_kept_ac2(make_runtime, fake) -> None:
    from agile_team.boundary import Boundary, Edge, ReplayProgress

    rt = make_runtime()
    rt.state.sprint = 1
    progress = ReplayProgress(old_head="h" * 40, base="b" * 40, target="t" * 40)
    rt.state.boundary = Boundary(Edge.END, 1, replay=progress)
    system.make_dirs(rt.config.run_dir / "replay")
    rt.recover_stories(Cause.CRASH)
    assert removals(fake) == []
    assert pruned(rt) == []


# ---------- AC3: drift is reported at the next step, not removed ----------


def test_a_kept_worktree_with_a_moved_head_is_drift_at_the_next_step_ac3(
    make_runtime, fake
) -> None:
    s1 = story("s1", branch="team/story-s1", base_sha=SHA)
    rt = resumed(make_runtime, s1)
    assert removals(fake) == []
    fake.reply(("symbolic-ref",), Done(0, "team/story-s1\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, "b" * 40 + "\n"))
    fake.reply(("status", "--porcelain"), Done(0, " M a.py\0"))
    assert rt.prepare_story(s1) is not None
    assert not [c for c in fake.commands if "worktree" in c.argv and "add" in c.argv]
    assert s1.drift == ["a.py"]
