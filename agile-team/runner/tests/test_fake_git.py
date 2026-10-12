"""The working-tree model behind the fake's git commands (``FakeSystem.track``, s77)."""

from pathlib import Path

import pytest
from agile_team import system
from agile_team.git_ops import Git, GitError

from .fake_system import FAKE_HEAD, FAKE_REPO, Done, FakeSystem


@pytest.fixture
def git(repo: Path, fake: FakeSystem) -> Git:
    """A git on the tracked fake repo (its seeded files are the first commit)."""
    fake.track()
    return Git(repo)


def write(name: str, text: str = "x\n") -> None:
    system.make_dirs((FAKE_REPO / name).parent)
    system.write_text(FAKE_REPO / name, text)


def test_a_tracked_repo_starts_clean_at_the_seeded_head(git: Git) -> None:
    assert git.is_clean() and git.head() == FAKE_HEAD
    assert git.branch() == "main"


def test_status_lists_untracked_modified_and_deleted_paths(git: Git) -> None:
    write("new.txt")
    write("src/app.py", "changed\n")
    system.remove(FAKE_REPO / ".gitignore")
    assert git.changed_paths() == [".gitignore", "new.txt", "src/app.py"]
    out = git.run("status", "--porcelain=v1", "-z")
    assert out == " D .gitignore\0?? new.txt\0 M src/app.py\0"


def test_status_without_z_is_newline_separated(git: Git) -> None:
    write("new.txt")
    assert git.run("status", "--porcelain") == "?? new.txt\n"


def test_ignored_paths_are_not_reported(git: Git) -> None:
    write(".team/run/state.json", "{}")
    assert git.is_clean()
    assert git.is_ignored(".team/run/state.json")
    assert not git.is_ignored("src/app.py")


def test_commit_takes_exactly_the_named_paths(git: Git) -> None:
    write("a.txt")
    write("b.txt")
    sha = git.commit(["a.txt"], "add a")
    assert git.head() == sha != FAKE_HEAD
    assert git.changed_paths() == ["b.txt"]
    assert git.subject(sha) == "add a"


def test_commit_of_a_deletion(git: Git) -> None:
    system.remove(FAKE_REPO / "src" / "app.py")
    git.commit(["src/app.py"], "drop app")
    assert git.is_clean()


def test_commit_with_nothing_to_commit_is_an_error(git: Git) -> None:
    code, out = git.attempt("commit", "--no-verify", "-m", "empty")
    assert code == 1 and "nothing to commit" in out
    with pytest.raises(GitError):
        git.commit(["src/app.py"], "empty")


def test_commit_a_flag_takes_every_tracked_change(git: Git) -> None:
    write("src/app.py", "y\n")
    write("untracked.txt")
    git.run("commit", "-qam", "all")
    assert git.changed_paths() == []


def test_log_shows_subjects_newest_first(git: Git) -> None:
    write("a.txt")
    git.commit(["a.txt"], "one")
    write("b.txt")
    git.commit(["b.txt"], "two")
    assert git.run("log", "--format=%s", "-2") == "two\n" + "one\n"
    assert git.run("log", "-1", "--format=%s") == "two\n"
    assert git.run("log", "--format=%s").splitlines() == ["two", "one", "init"]


def test_log_of_a_sha_shows_its_message_in_full(git: Git) -> None:
    write("a.txt")
    sha = git.commit(["a.txt"], "one")
    body = git.run("log", "-1", "--format=%B", sha)
    assert body.startswith("one") and "Co-Authored-By" in body


def test_revert_restores_the_files_and_stages_the_reverse(git: Git) -> None:
    write("a.txt")
    write("src/app.py", "changed\n")
    sha = git.commit(["a.txt", "src/app.py"], "work")
    git.revert(sha)
    assert not system.exists(FAKE_REPO / "a.txt")
    assert system.read_text(FAKE_REPO / "src" / "app.py") == "x = 1\n"
    assert git.is_clean()
    assert git.subject(git.head()) == 'Revert "work"'


def test_show_name_only_lists_the_commit_s_paths(git: Git) -> None:
    write("b.txt")
    write("a.txt")
    git.commit(["b.txt", "a.txt"], "two files")
    assert git.run("show", "--name-only", "--format=", "HEAD").split() == ["a.txt", "b.txt"]


def test_show_a_file_at_a_revision(git: Git) -> None:
    assert git.run("show", "HEAD:src/app.py") == "x = 1\n"
    with pytest.raises(GitError):
        git.run("show", "HEAD:nope.txt")


def test_rev_list_counts_commits_since(git: Git) -> None:
    before = git.head()
    write("a.txt")
    git.commit(["a.txt"], "one")
    write("b.txt")
    git.commit(["b.txt"], "two")
    assert git.run("rev-list", "--count", f"{before}..HEAD").strip() == "2"


def test_rev_parse_short_and_git_dir(git: Git) -> None:
    assert git.run("rev-parse", "--short=7", "HEAD").strip() == FAKE_HEAD[:7]
    assert git.run("rev-parse", "--absolute-git-dir").strip() == str(FAKE_REPO / ".git")


def test_checkout_detach_and_branch_and_the_reflog(git: Git) -> None:
    assert git.run("log", "-g", "-1", "--format=%gd %gs", "HEAD").strip() == ""
    git.run("checkout", "-q", "--detach")
    assert git.branch() is None
    assert "checkout: moving from main to" in git.run("log", "-g", "-1", "HEAD")
    git.run("checkout", "-q", "-b", "other")
    assert git.branch() == "other"
    git.run("checkout", "-q", "main")
    assert git.branch() == "main"


def test_reset_hard_drops_commits_and_restores_files(git: Git) -> None:
    write("src/app.py", "two\n")
    git.run("commit", "-qam", "two")
    git.run("reset", "-q", "--hard", "HEAD~1")
    assert git.head() == FAKE_HEAD
    assert system.read_text(FAKE_REPO / "src" / "app.py") == "x = 1\n"


def test_scripted_replies_win_over_the_model(git: Git, fake: FakeSystem) -> None:
    fake.reply(("git", "status"), Done(0, "?? scripted\0"))
    assert git.changed_paths() == ["scripted"]


def test_commands_the_model_does_not_know_get_the_default(git: Git) -> None:
    assert git.attempt("fetch", "origin") == (0, "")


def test_options_before_the_subcommand_are_skipped(git: Git) -> None:
    write("a.txt")
    assert Git(FAKE_REPO, ("-c", "core.editor=true")).changed_paths() == ["a.txt"]


def test_an_untracked_fake_answers_with_the_default(repo: Path) -> None:
    assert Git(repo).changed_paths() == []
    assert Git(repo).head() == FAKE_HEAD
