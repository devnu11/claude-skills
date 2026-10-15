"""s153 AC3, AC4, AC5: ``ScratchRebase`` on a scripted git (real git is in e2e)."""

from __future__ import annotations

import importlib
from pathlib import Path

from agile_team import upstream as up
from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git
from agile_team.upstream import Upstream

from .fake_system import FAKE_REPO, Done, FakeSystem

OLD, HEAD, BASE = "a" * 40, "b" * 40, "d" * 40
BRANCH = "agile-team/rebase-sprint-3"
PATH = FAKE_REPO / ".team" / "run" / "rebase"
NO_RENAMES = ("git", "diff", "--name-only", "--no-renames")
WRITERS = {"checkout", "switch", "reset", "rebase", "add", "commit"}


class _Late:
    """The module, imported on first use, so each test fails alone while it is missing."""

    def __getattr__(self, name: str):
        return getattr(importlib.import_module("agile_team.scratch_rebase"), name)


sr = _Late()


def scratch() -> sr.ScratchRebase:
    return sr.ScratchRebase(Upstream(Git(FAKE_REPO), UpstreamSettings()), PATH, BRANCH)


def stamped(sha: str, message: str) -> str:
    return f"{sha}\x1fAda\x1fada@example.com\x1f100 +0000\x1f{message}\x1e\n"


def commands(fake: FakeSystem) -> list[tuple[tuple[str, ...], Path | None]]:
    return [(tuple(c.argv), c.cwd) for c in fake.commands]


def in_team(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [argv for argv, cwd in commands(fake) if cwd == FAKE_REPO]


def test_constants() -> None:
    assert sr.REBASE_DIR == "rebase"
    assert sr.REBASE_BRANCH == "agile-team/rebase-sprint-{sprint}"
    assert (
        sr.ScratchRebase._unfinished,
        sr.ScratchRebase._off_branch,
        sr.ScratchRebase._dirty,
        sr.ScratchRebase._off_target,
        sr.ScratchRebase._merges,
        sr.ScratchRebase._commits_changed,
        sr.ScratchRebase._lost,
    ) == sr.SCRATCH_CHECKS


def test_tree_and_head_are_the_worktrees(fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, HEAD + "\n"))
    assert scratch().tree.repo == PATH
    assert scratch().head() == HEAD
    assert commands(fake)[-1][1] == PATH


# ----- AC3 ------------------------------------------------------------------------


def test_prepare_removes_adds_then_rebases_in_the_worktree(fake: FakeSystem) -> None:
    fake.reply(("git", "rebase"), Done(1, "CONFLICT"))
    scratch().prepare(OLD)
    log = commands(fake)
    argvs = [a for a, _ in log]
    remove = next(i for i, a in enumerate(argvs) if "remove" in a)
    add = next(i for i, a in enumerate(argvs) if "add" in a)
    rebase = next(i for i, a in enumerate(argvs) if "rebase" in a)
    assert remove < add < rebase
    assert argvs[add][-6:] == ("worktree", "add", "-B", BRANCH, str(PATH), OLD)
    assert log[add][1] == FAKE_REPO
    assert argvs[rebase][-len(up.SCRATCH_REBASE_ARGV) - 1 :] == (
        *up.SCRATCH_REBASE_ARGV,
        "origin/main",
    )
    assert log[rebase][1] == PATH


def test_prepare_runs_no_writing_command_in_the_team_checkout(fake: FakeSystem) -> None:
    scratch().prepare(OLD)
    for argv in in_team(fake):
        assert not WRITERS & set(argv[1:])


def test_prepare_replaces_a_leftover_worktree(fake: FakeSystem) -> None:
    fake.put(PATH / "stray.txt", "x")
    scratch().prepare(OLD)
    assert not fake.exists(PATH / "stray.txt")


# ----- remove, drop (AC4) ---------------------------------------------------------


def test_remove_deletes_a_leftover_directory(fake: FakeSystem) -> None:
    fake.put(PATH / "stray.txt", "x")
    scratch().remove()
    assert not fake.exists(PATH)
    argvs = [a for a, _ in commands(fake)]
    assert any(a[1:4] == ("worktree", "remove", "--force") and a[-1] == str(PATH) for a in argvs)
    assert any(a[1:] == ("worktree", "prune") for a in argvs)


def test_remove_leaves_a_missing_path_alone(fake: FakeSystem) -> None:
    scratch().remove()
    assert ("remove_tree", PATH) not in [(n, p) for n, p in fake.ops]
    assert not fake.exists(PATH)


def test_drop_removes_the_worktree_and_deletes_the_branch(fake: FakeSystem) -> None:
    fake.put(PATH / "stray.txt", "x")
    scratch().drop()
    assert not fake.exists(PATH)
    branch = [(a, cwd) for a, cwd in commands(fake) if a[1:3] == ("branch", "-D")]
    assert branch == [(("git", "branch", "-D", BRANCH), FAKE_REPO)]
    argvs = [a for a, _ in commands(fake)]
    first_remove = next(i for i, a in enumerate(argvs) if "remove" in a)
    assert first_remove < argvs.index(branch[0][0])


# ----- AC5: one test per check ------------------------------------------------------


def test_unfinished(fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "--absolute-git-dir"), Done(0, "/gd\n"))
    fake.put(Path("/gd/rebase-merge/x"), "")
    reason = scratch()._unfinished(OLD)
    assert reason == sr.UNFINISHED.format(path=PATH, operation="rebase")


def test_unfinished_passes_on_a_quiet_worktree(fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "--absolute-git-dir"), Done(0, "/gd\n"))
    assert scratch()._unfinished(OLD) == ""


def test_off_branch(fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, "other\n"))
    assert scratch()._off_branch(OLD) == sr.OFF_BRANCH.format(path=PATH, branch=BRANCH)


def test_off_branch_passes_on_the_branch_and_fails_when_detached(fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, BRANCH + "\n"))
    assert scratch()._off_branch(OLD) == ""
    fake.reply(("git", "symbolic-ref"), Done(1, ""))
    assert scratch()._off_branch(OLD) != ""


def test_dirty(fake: FakeSystem) -> None:
    fake.reply(("git", "status", "--porcelain"), Done(0, " M a.py\n"))
    assert scratch()._dirty(OLD) == sr.DIRTY.format(path=PATH, status=" M a.py".strip())


def test_dirty_passes_when_clean(fake: FakeSystem) -> None:
    fake.reply(("git", "status", "--porcelain"), Done(0, ""))
    assert scratch()._dirty(OLD) == ""


def test_off_target(fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base", "--is-ancestor"), Done(1, ""))
    assert scratch()._off_target(OLD) == sr.NOT_ON_TARGET.format(
        branch=BRANCH, target="origin/main"
    )
    [argv] = [a for a in in_team(fake) if "--is-ancestor" in a]
    assert argv[-2:] == ("origin/main", BRANCH)


def test_off_target_passes_when_the_target_is_an_ancestor(fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base", "--is-ancestor"), Done(0, ""))
    assert scratch()._off_target(OLD) == ""


def test_merges(fake: FakeSystem) -> None:
    shas = ["1" * 40, "2" * 40]
    fake.reply(("git", "rev-list", "--merges"), Done(0, "\n".join(shas) + "\n"))
    reason = scratch()._merges(OLD)
    assert reason == sr.HAS_MERGES.format(branch=BRANCH, shas="1" * 12 + ", " + "2" * 12)
    [argv] = [a for a in in_team(fake) if "--merges" in a]
    assert argv[-1] == f"origin/main..{BRANCH}"


def test_merges_passes_without_merge_commits(fake: FakeSystem) -> None:
    fake.reply(("git", "rev-list", "--merges"), Done(0, ""))
    assert scratch()._merges(OLD) == ""


def script_commits(
    fake: FakeSystem, old: list[tuple[str, str]], new: list[tuple[str, str]]
) -> None:
    fake.reply(("git", "log", f"origin/main..{OLD}"), Done(0, "".join(stamped(*c) for c in old)))
    fake.reply(("git", "log", f"origin/main..{BRANCH}"), Done(0, "".join(stamped(*c) for c in new)))
    fake.reply(("git", "cherry"), Done(0, "- u1\n+ k1\n"))


def test_commits_changed_when_a_commit_is_reworded(fake: FakeSystem) -> None:
    script_commits(fake, [("k1", "one"), ("k2", "two")], [("n1", "one"), ("n2", "TWO")])
    assert scratch()._commits_changed(OLD) == sr.COMMITS_CHANGED.format(branch=BRANCH)


def test_commits_changed_when_order_differs(fake: FakeSystem) -> None:
    script_commits(fake, [("k1", "one"), ("k2", "two")], [("n2", "two"), ("n1", "one")])
    assert scratch()._commits_changed(OLD) != ""


def test_commits_changed_when_a_commit_is_dropped(fake: FakeSystem) -> None:
    script_commits(fake, [("k1", "one"), ("k2", "two")], [("n1", "one")])
    assert scratch()._commits_changed(OLD) != ""


def test_commits_changed_passes_for_the_same_commits_rebased(fake: FakeSystem) -> None:
    script_commits(fake, [("k1", "one"), ("k2", "two")], [("n1", "one"), ("n2", "two")])
    assert scratch()._commits_changed(OLD) == ""


def test_commits_changed_ignores_the_ones_already_upstream(fake: FakeSystem) -> None:
    script_commits(fake, [("u1", "up"), ("k1", "one")], [("n1", "one")])
    assert scratch()._commits_changed(OLD) == ""


def script_lost(fake: FakeSystem, mine: str) -> None:
    fake.reply(("git", "rev-parse", "origin/main"), Done(0, "e" * 40 + "\n"))
    fake.reply(("git", "merge-base"), Done(0, BASE + "\n"))
    fake.reply((*NO_RENAMES, OLD, BRANCH), Done(0, mine))


def test_lost(fake: FakeSystem) -> None:
    script_lost(fake, "x.py\ny.py\n")
    assert scratch()._lost(OLD) == sr.LOST_PATHS.format(branch=BRANCH, paths="x.py, y.py")


def test_lost_passes_when_no_path_is_one_sided(fake: FakeSystem) -> None:
    script_lost(fake, "")
    assert scratch()._lost(OLD) == ""


# ----- refusal ------------------------------------------------------------------------


def test_refusal_is_empty_when_every_check_passes(fake: FakeSystem, monkeypatch) -> None:
    passing = tuple(lambda self, old: "" for _ in sr.SCRATCH_CHECKS)
    monkeypatch.setattr(sr, "SCRATCH_CHECKS", passing)
    assert scratch().refusal(OLD) == ""


def test_refusal_reads_the_table_at_call_time_and_stops_at_the_first_reason(
    fake: FakeSystem, monkeypatch
) -> None:
    calls = []

    def check(reason: str):
        def run(self, old: str) -> str:
            calls.append(reason)
            return reason

        return run

    monkeypatch.setattr(sr, "SCRATCH_CHECKS", (check(""), check("first"), check("second")))
    assert scratch().refusal(OLD) == "first"
    assert calls == ["", "first"]


def test_refusal_with_real_checks_names_the_first_problem(fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "--absolute-git-dir"), Done(0, "/gd\n"))
    fake.put(Path("/gd/rebase-merge/x"), "")
    fake.reply(("git", "symbolic-ref"), Done(1, ""))
    fake.reply(("git", "status", "--porcelain"), Done(0, " M a\n"))
    assert scratch().refusal(OLD) == sr.UNFINISHED.format(path=PATH, operation="rebase")


def test_refusal_with_real_checks_is_empty_for_a_clean_resolution(fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "--absolute-git-dir"), Done(0, "/gd\n"))
    fake.reply(("git", "symbolic-ref"), Done(0, BRANCH + "\n"))
    fake.reply(("git", "rev-parse", "origin/main"), Done(0, "e" * 40 + "\n"))
    fake.reply(("git", "merge-base"), Done(0, BASE + "\n"))
    fake.reply(("git", "cherry"), Done(0, ""))
    assert scratch().refusal(OLD) == ""
