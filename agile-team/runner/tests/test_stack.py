"""s29 U8/U15/U16: the Rebuilder over real repos and bare origins."""

from pathlib import Path

import pytest
from agile_team import stack
from agile_team.boundary import StackEntry
from agile_team.git_ops import Git, GitError
from agile_team.stack import Build, Conflict, Rebuilder

from .conftest import git
from .s29_helpers import commit, land_by_rebase, land_upstream, make_origin, rev

TARGET = "origin/main"


class Setup:
    """Two sprints of team commits on top of origin/main."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.origin, self.work = make_origin(tmp_path)
        self.start = rev(self.work, "HEAD")
        self.setup_commit = self.start  # make_origin's team commit, below sprint 1
        self.s1 = [commit(self.work, "a.txt"), commit(self.work, "b.txt")]
        self.mid = rev(self.work, "HEAD")
        self.s2 = [commit(self.work, "c.txt")]
        self.end = rev(self.work, "HEAD")
        self.rb = Rebuilder(Git(self.work), tmp_path / "wt", TARGET)

    def entries(self) -> list[StackEntry]:
        return [
            StackEntry(1, "team/sprint-1", self.start, self.mid),
            StackEntry(2, "team/sprint-2", self.mid, self.end),
        ]


@pytest.fixture
def s(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


def test_constants() -> None:
    assert stack.REVIEW_DIR == "review"
    for option in (
        "rerere.enabled=true",
        "rerere.autoUpdate=true",
        "core.editor=true",
        "core.hooksPath=/dev/null",
    ):
        assert option in stack.REVIEW_GIT


def test_unmerged_lists_team_commits_only(s: Setup) -> None:
    land_upstream(s.tmp, s.origin, "up.txt")
    git(s.work, "fetch", "-q", "origin")
    assert s.rb.unmerged(s.end) == {s.setup_commit, *s.s1, *s.s2}


def test_picks_are_the_range_in_order(s: Setup) -> None:
    un = s.rb.unmerged(s.end)
    e1, e2 = s.entries()
    assert s.rb.picks(e1, un) == s.s1
    assert s.rb.picks(e2, un) == s.s2


def test_picks_skip_merge_commits_and_main_commits(s: Setup) -> None:
    land_upstream(s.tmp, s.origin, "up.txt")
    git(s.work, "fetch", "-q", "origin")
    git(s.work, "merge", "-q", "--no-edit", "origin/main")
    merge = rev(s.work, "HEAD")
    extra = commit(s.work, "d.txt")
    entry = StackEntry(2, "team/sprint-2", s.mid, extra)
    picks = s.rb.picks(entry, s.rb.unmerged(extra))
    assert picks == [*s.s2, extra] and merge not in picks


def test_picks_empty_after_a_rebase_merge(s: Setup) -> None:
    land_by_rebase(s.tmp, s.origin, s.s1, s.work)
    git(s.work, "fetch", "-q", "origin")
    un = s.rb.unmerged(s.end)
    e1, e2 = s.entries()
    assert s.rb.picks(e1, un) == []
    assert s.rb.picks(e2, un) == s.s2


def build_all(s: Setup) -> list[StackEntry]:
    s.rb.prepare()
    un = s.rb.unmerged(s.end)
    base = TARGET
    entries = s.entries()
    for entry in entries:
        assert s.rb.build(entry, Build(base, s.rb.picks(entry, un))) is None
        base = entry.head
    return entries


def test_prepare_creates_a_detached_worktree_and_is_repeatable(s: Setup) -> None:
    s.rb.prepare()
    wt = s.tmp / "wt"
    assert (wt / ".git").exists() and (wt / "base.txt").exists()
    (wt / "junk.txt").write_text("j")
    s.rb.prepare()
    assert not (wt / "junk.txt").exists()


def test_prepare_survives_a_pruned_worktree(s: Setup) -> None:
    s.rb.prepare()
    import shutil

    shutil.rmtree(s.tmp / "wt")
    s.rb.prepare()
    assert (s.tmp / "wt" / "base.txt").exists()


def test_build_stacks_each_sprint_on_the_one_below(s: Setup) -> None:
    before = rev(s.work, "agile-team")
    e1, e2 = build_all(s)
    assert rev(s.work, e1.branch) == e1.head and rev(s.work, e2.branch) == e2.head
    assert git(s.work, "rev-list", "--count", f"{TARGET}..{e1.branch}").strip() == "2"
    assert git(s.work, "rev-parse", f"{e2.branch}~1").strip() == e1.head
    assert git(s.work, "log", "-1", "--format=%s", e2.branch).strip() == "add c.txt"
    diff = git(s.work, "diff", "--stat", e2.branch, "agile-team", "--", ".", ":!.gitignore")
    assert diff.strip() == ""
    assert rev(s.work, "agile-team") == before and rev(s.work, "agile-team") == s.end


def test_build_keeps_author_and_message(s: Setup) -> None:
    e1, _ = build_all(s)
    msgs = git(s.work, "log", "--format=%an|%s", f"{TARGET}..{e1.branch}").split("\n")
    assert msgs[:2] == ["Test|add b.txt", "Test|add a.txt"]


def test_build_rebases_onto_new_upstream(s: Setup) -> None:
    land_upstream(s.tmp, s.origin, "up.txt")
    git(s.work, "fetch", "-q", "origin")
    e1, e2 = build_all(s)
    assert (s.tmp / "wt" / "up.txt").exists() or "up.txt" in git(
        s.work, "ls-tree", "-r", "--name-only", e2.branch
    )
    assert git(s.work, "merge-base", e1.branch, TARGET).strip() == rev(s.work, TARGET)


def test_pick_already_in_main_is_skipped(s: Setup) -> None:
    land_by_rebase(s.tmp, s.origin, [s.s1[0]], s.work)
    git(s.work, "fetch", "-q", "origin")
    s.rb.prepare()
    e1 = s.entries()[0]
    assert s.rb.build(e1, Build(TARGET, [*s.s1])) is None
    assert git(s.work, "rev-list", "--count", f"{TARGET}..{e1.branch}").strip() == "1"


def test_all_picks_empty_leaves_head_equal_to_base(s: Setup) -> None:
    land_by_rebase(s.tmp, s.origin, s.s1, s.work)
    git(s.work, "fetch", "-q", "origin")
    s.rb.prepare()
    e1 = s.entries()[0]
    assert s.rb.build(e1, Build(TARGET, list(s.s1))) is None
    assert e1.head == rev(s.work, TARGET)


def conflicting(tmp_path: Path) -> tuple[Setup, StackEntry]:
    st = Setup(tmp_path)
    st.mid = commit(st.work, "base.txt", "mine\n", "feat: mine")
    land_upstream(tmp_path, st.origin, "base.txt", "theirs\n")
    git(st.work, "fetch", "-q", "origin")
    return st, StackEntry(3, "team/sprint-3", st.end, st.mid)


def test_conflict_reports_branch_commit_subject_and_files(tmp_path: Path) -> None:
    st, entry = conflicting(tmp_path)
    st.rb.prepare()
    conflict = st.rb.build(entry, Build(TARGET, [st.mid]))
    assert isinstance(conflict, Conflict)
    assert (conflict.branch, conflict.commit, conflict.subject) == (
        "team/sprint-3",
        st.mid,
        "feat: mine",
    )
    assert conflict.files == ("base.txt",) and conflict.output
    assert "<<<<<<<" in (tmp_path / "wt" / "base.txt").read_text()
    assert rev(st.work, "agile-team") == st.mid


def test_recorded_resolution_is_replayed_on_the_next_rebuild(tmp_path: Path) -> None:
    st, entry = conflicting(tmp_path)
    st.rb.prepare()
    assert st.rb.build(entry, Build(TARGET, [st.mid])) is not None
    (tmp_path / "wt" / "base.txt").write_text("resolved\n")
    st.rb.record(["base.txt"])
    st.rb.prepare()
    assert st.rb.build(entry, Build(TARGET, [st.mid])) is None
    assert git(st.work, "show", f"{entry.branch}:base.txt") == "resolved\n"
    assert git(st.work, "log", "-1", "--format=%s", entry.branch).strip() == "feat: mine"


def test_record_aborts_the_pick_in_progress(tmp_path: Path) -> None:
    st, entry = conflicting(tmp_path)
    st.rb.prepare()
    st.rb.build(entry, Build(TARGET, [st.mid]))
    (tmp_path / "wt" / "base.txt").write_text("resolved\n")
    st.rb.record(["base.txt"])
    assert Git(tmp_path / "wt").attempt("rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD")[0] != 0


def test_checkout_switches_the_worktree_to_a_branch(s: Setup) -> None:
    e1, e2 = build_all(s)
    s.rb.checkout(e1.branch)
    wt = s.tmp / "wt"
    assert (wt / "b.txt").exists() and not (wt / "c.txt").exists()
    s.rb.checkout(e2.branch)
    assert (wt / "c.txt").exists()


def test_cherry_pick_without_a_pick_in_progress_is_a_git_error(s: Setup) -> None:
    s.rb.prepare()
    with pytest.raises(GitError):
        s.rb.build(s.entries()[0], Build(TARGET, ["0" * 40]))
