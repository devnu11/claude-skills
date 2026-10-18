"""s159 slice 6: the replay (R1 to R5, R7, R8), the scratch replay (R2) and the open stage.

The merge-shaped cases run real git in the s151 e2e files; here git is scripted.
"""

from __future__ import annotations

from agile_team import boundary as b
from agile_team import rewrite, state
from agile_team.gates import StoryState
from agile_team.git_ops import Git
from agile_team.revert_log import RevertEntry
from agile_team.story_branches import Landed

from .fake_system import FAKE_REPO, Done, FakeSystem
from .late import Late

rp = Late("replay")
sr = Late("scratch_replay")
NEW, OLD, TIP = "n" * 40, "o" * 40, "t" * 40
RUN = FAKE_REPO / ".team" / "run"


def argvs(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands]


# ---------- the data (R5, R8, section 3) ----------


def test_stack_entry_carries_the_replay_fields_r5() -> None:
    e = b.StackEntry(1, "team/sprint-1", "a", "b")
    assert (e.as_is_branch, e.as_is_pr, e.replays) == ("", None, 0)


def test_replay_progress_defaults_and_boundary_holds_it_r1() -> None:
    p = b.ReplayProgress(old_head=OLD, base="b", target="t")
    assert (p.done, p.tip, p.story, p.moved) == (0, "", "", {})
    assert b.Boundary(b.Edge.END, 1).replay is None
    assert b.Boundary(b.Edge.END, 1, replay=p).replay is p


def test_failure_names_the_stopped_story_r2() -> None:
    f = b.Failure(b.Stage.REPLAY, b.FixCase.REBASE_CONFLICT, "x", story="s1")
    assert f.story == "s1"


def test_push_permission_is_no_longer_a_boundary_hold_p1() -> None:
    assert "push_permission" not in {h.value for h in b.BoundaryHold}


def test_the_old_sync_from_is_loaded_as_replay_old_head_r1() -> None:
    loaded = state._boundary({"edge": "end", "sprint": 1, "sync_from": OLD})
    assert loaded.replay is not None and loaded.replay.old_head == OLD


# ---------- the remap (R4) ----------


def line(sha: str, subject: str, *parents: str):
    return (sha, subject, tuple(parents))


def test_pair_replay_pairs_a_merge_by_story_id_and_its_commits_by_subject_r4() -> None:
    old = [line("c1", "work", "m0", "x"), line("M", "merge(s1): T", "m0", "c1")]
    new = [line("d1", "work", "n0"), line("N", "merge(s1): T", "n0", "d1")]
    moved = rewrite.pair_replay(old, new)
    assert moved["M"] == "N"


def test_remap_rewrites_base_sha_landed_merge_and_revert_entries_r4() -> None:
    st = state.RunState(sprint=1)
    story = StoryState("s1", "One", "land", base_sha="o1", landed=Landed(merge="o2"))
    st.stories["s1"] = story
    entry = RevertEntry("d", 1, "r", [], revert="o3", merge="o2")
    story.reverted = [entry]
    count = rewrite.remap_state(st, {"o1": "n1", "o2": "n2", "o3": "n3"})
    assert story.base_sha == "n1" and story.landed.merge == "n2" and count >= 4
    assert (entry.merge, entry.revert) == ("n2", "n3")


# ---------- Replayer (R1) ----------


def spec():
    return rp.ReplaySpec(base="b" * 40, head="h" * 40, target=NEW, scratch_branch="scratch")


def test_the_replay_worktree_is_detached_at_the_target_r1(fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--first-parent", "--reverse"), Done(0, ""))
    progress = b.ReplayProgress(old_head="h" * 40, base="b" * 40, target=NEW)
    rp.Replayer(Git(FAKE_REPO), RUN / "replay").run(spec(), progress)
    add = next(a for a in argvs(fake) if "worktree" in a and "add" in a)
    assert "--detach" in add and str(RUN / "replay") in add and NEW in add


def test_a_plain_commit_is_cherry_picked_and_progress_saved_r1(fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--first-parent", "--reverse"), Done(0, "c1\n"))
    progress = b.ReplayProgress(old_head="h" * 40, base="b" * 40, target=NEW)
    result = rp.Replayer(Git(FAKE_REPO), RUN / "replay").run(spec(), progress)
    assert any("cherry-pick" in a and "--allow-empty" in a and "c1" in a for a in argvs(fake))
    assert progress.done == 1 and result.outcome.value == "rebased"


def test_a_resumed_replay_skips_the_commits_already_done_r1(fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--first-parent", "--reverse"), Done(0, "c1\nc2\n"))
    progress = b.ReplayProgress(old_head="h" * 40, base="b" * 40, target=NEW, done=1, tip=TIP)
    rp.Replayer(Git(FAKE_REPO), RUN / "replay").run(spec(), progress)
    picks = [a for a in argvs(fake) if "cherry-pick" in a]
    assert len(picks) == 1 and "c2" in picks[0] and progress.done == 2


def test_a_cherry_pick_conflict_stops_with_the_files_r2(fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--first-parent", "--reverse"), Done(0, "c1\n"))
    fake.reply(("cherry-pick",), Done(1, "CONFLICT (content)"))
    fake.reply(("diff", "--name-only"), Done(0, "a.py\n"))
    progress = b.ReplayProgress(old_head="h" * 40, base="b" * 40, target=NEW)
    result = rp.Replayer(Git(FAKE_REPO), RUN / "replay").run(spec(), progress)
    assert result.outcome.value == "conflict" and "a.py" in result.files
    assert progress.done == 0


def test_remove_takes_the_worktree_away(fake: FakeSystem) -> None:
    rp.Replayer(Git(FAKE_REPO), RUN / "replay").remove()
    assert any("worktree" in a and "remove" in a for a in argvs(fake))


# ---------- ScratchReplay (R2) ----------


def test_the_has_merges_refusal_is_gone_and_story_commits_is_in_r2() -> None:
    assert not hasattr(sr, "HAS_MERGES") and hasattr(sr, "STORY_COMMITS")
    names = [c.__name__ for c in sr.SCRATCH_CHECKS]
    assert "_merges" not in names and any("story" in n for n in names)


def test_scratch_branch_and_dir_names_r2() -> None:
    assert sr.REPLAY_BRANCH.format(sprint=3) == "agile-team/replay-sprint-3"
    assert sr.REPLAY_DIR == "replay"


def test_an_unfinished_operation_is_refused_first_r2(fake: FakeSystem) -> None:
    progress = b.ReplayProgress(old_head=OLD, base="b", target=NEW, tip=TIP, story="s1")
    scratch = sr.ScratchReplay(Git(FAKE_REPO), RUN / "replay", "agile-team/replay-sprint-1")
    fake.reply(("symbolic-ref",), Done(0, "elsewhere\n"))
    assert "agile-team/replay-sprint-1" in scratch.find_refusal(progress)


# ---------- StoryReplay (R8) ----------


def test_a_carried_story_is_rebased_onto_the_head_on_a_new_branch_r8(make_runtime, fake) -> None:
    rt = make_runtime()
    story = StoryState(
        "s1", "t", "implement", branch="team/story-s1", base_sha=OLD, worktree_head="w" * 40
    )
    rt.state.stories["s1"] = story
    fake.reply(("rev-parse", "HEAD"), Done(0, TIP + "\n"))
    result = rp.StoryReplay(rt).run(story, NEW)
    got = argvs(fake)
    assert any("checkout" in a and "-b" in a and "team/story-s1-r1" in a for a in got)
    assert any("rebase" in a and "--onto" in a and NEW in a and OLD in a for a in got)
    assert result.outcome.value == "rebased"
    assert (story.branch, story.base_sha, story.pushed, story.replays) == (
        "team/story-s1-r1",
        NEW,
        "",
        1,
    )


def test_an_interrupted_step_is_stashed_and_popped_r8(make_runtime, fake) -> None:
    from agile_team.salvage import InFlight

    rt = make_runtime()
    story = StoryState("s1", "t", "implement", branch="team/story-s1", base_sha=OLD)
    story.in_flight = InFlight("developer", "s1", "brief", session="sess")
    rt.state.stories["s1"] = story
    rp.StoryReplay(rt).run(story, NEW)
    got = argvs(fake)
    stash = next(a for a in got if "stash" in a and "push" in a)
    pop = next(a for a in got if "stash" in a and "pop" in a)
    assert "--include-untracked" in stash and got.index(stash) < got.index(pop)


def test_a_story_replay_conflict_aborts_and_queues_a_rebase_without_a_round_r8(
    make_runtime, fake
) -> None:
    rt = make_runtime()
    story = StoryState("s1", "t", "implement", branch="team/story-s1", base_sha=OLD, rounds=2)
    rt.state.stories["s1"] = story
    fake.reply(("rebase", "--onto"), Done(1, "CONFLICT"))
    fake.reply(("diff", "--name-only"), Done(0, "src/a.py\n"))
    result = rp.StoryReplay(rt).run(story, NEW)
    assert result.outcome.value == "conflict"
    assert any("rebase" in a and "--abort" in a for a in argvs(fake))
    assert story.rebase is not None and story.rebase.onto == NEW and story.rebase.role
    assert story.rounds == 2 and story.branch == "team/story-s1"


def test_boundary_runner_has_follow_remote_r9() -> None:
    from agile_team.boundary_runner import BoundaryRunner

    assert hasattr(BoundaryRunner, "follow_remote")
