"""s159 slice 4: Workspaces, the story worktrees (B1, B2, B5, C3, E1, I3)."""

from __future__ import annotations

from pathlib import Path

from agile_team import system
from agile_team.config import Config
from agile_team.gates import StoryState
from agile_team.git_ops import Git

from .fake_system import FAKE_REPO, Done, FakeSystem
from .late import Late

HEAD = "a" * 40
RUN = FAKE_REPO / ".team" / "run"


ws = Late("workspaces")


def make():
    return ws.Workspaces(Git(FAKE_REPO), Config(repo=FAKE_REPO))


def argvs(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands]


def has(fake: FakeSystem, *words: str) -> bool:
    return any(all(w in argv for w in words) for argv in argvs(fake))


def test_path_of_is_under_the_run_dir_b2() -> None:
    assert make().path_of("s1") == RUN / "worktrees" / "s1"


def test_ensure_makes_the_branch_then_the_worktree_b1(fake: FakeSystem) -> None:
    fake.reply(("rev-parse", "HEAD"), Done(0, HEAD + "\n"))
    story = StoryState(id="s1", title="t", step="design")
    path = make().ensure(story, HEAD)
    assert path == RUN / "worktrees" / "s1"
    branch = [a for a in argvs(fake) if "branch" in a and "team/story-s1" in a]
    tree = [a for a in argvs(fake) if "worktree" in a and "add" in a]
    assert branch and tree
    assert argvs(fake).index(branch[0]) < argvs(fake).index(tree[0])
    assert story.branch == "team/story-s1" and story.base_sha == HEAD
    assert story.worktree_head != ""


def test_ensure_keeps_an_existing_branch_and_rebuilds_the_worktree_b1(fake: FakeSystem) -> None:
    story = StoryState(id="s1", title="t", step="design", branch="team/story-s1", base_sha="b" * 40)
    make().ensure(story, HEAD)
    assert not [a for a in argvs(fake) if "branch" in a and "team/story-s1" in a and "add" not in a]
    assert has(fake, "worktree", "add")
    assert story.base_sha == "b" * 40


def test_ensure_resumes_an_existing_worktree_without_adding_one_ac1_1(fake: FakeSystem) -> None:
    """AC1.1/AC11.2: a branch and a worktree already there are reused, not recreated."""
    system.make_dirs(RUN / "worktrees" / "s1")
    story = StoryState(id="s1", title="t", step="design", branch="team/story-s1", base_sha="b" * 40)
    path = make().ensure(story, HEAD)
    assert path == RUN / "worktrees" / "s1"
    assert not has(fake, "worktree", "add")
    assert not [a for a in argvs(fake) if "branch" in a and "team/story-s1" in a]
    assert story.base_sha == "b" * 40


def test_remove_drops_the_worktree_but_not_the_branch_e1(fake: FakeSystem) -> None:
    make().remove("s1")
    assert has(fake, "worktree", "remove")
    assert not has(fake, "branch", "-D") and not has(fake, "branch", "-d")


def test_open_count_counts_stories_with_a_worktree_c3() -> None:
    open_ = StoryState(id="s1", title="t", step="design", worktree_head="c" * 40)
    shut = StoryState(id="s2", title="t", step="design")
    assert make().open_count([open_, shut]) == 1
    assert make().open_count([]) == 0


def test_changed_files_reads_the_worktree_status_b5(fake: FakeSystem) -> None:
    fake.reply(("status", "--porcelain"), Done(0, " M a.py\0?? b.py\0"))
    assert make().changed_files("s1") == ["a.py", "b.py"]


def test_prune_stale_removes_worktrees_without_in_flight_i3(fake: FakeSystem) -> None:
    system.make_dirs(RUN / "worktrees" / "s1")
    system.make_dirs(RUN / "worktrees" / "s2")
    gone = make().prune_stale(frozenset({"s2"}))
    assert gone == ["s1"]
    assert has(fake, "worktree", "prune")


def test_prune_stale_removes_land_and_replay_dirs_i3(fake: FakeSystem) -> None:
    system.make_dirs(RUN / "land")
    system.make_dirs(RUN / "replay")
    make().prune_stale(frozenset())
    removed = [a for a in argvs(fake) if "worktree" in a and "remove" in a]
    assert any(str(RUN / "land") in a for a in removed)
    assert any(str(RUN / "replay") in a for a in removed)


def test_at_worktree_keeps_the_main_run_dir_b3() -> None:
    cfg = Config(repo=FAKE_REPO).at_worktree(Path("/wt"))
    assert cfg.repo == Path("/wt") and cfg.run_dir == RUN


def test_prune_stale_keeps_the_scratch_dirs_named_in_keep_i3(fake: FakeSystem) -> None:
    system.make_dirs(RUN / "land")
    system.make_dirs(RUN / "replay")
    make().prune_stale(frozenset({"land"}))
    removed = [a for a in argvs(fake) if "worktree" in a and "remove" in a]
    assert not any(str(RUN / "land") in a for a in removed)
    assert any(str(RUN / "replay") in a for a in removed)
