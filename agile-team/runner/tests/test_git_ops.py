"""Git wrapper on the fake: argv and options, exit codes, porcelain parsing (s76).

What git itself does with a real repo (renames, reverts, ignore rules) is the e2e tests'.
"""

from pathlib import Path

import pytest
from agile_team import system
from agile_team.git_ops import CO_AUTHOR, Git, GitError, parse_porcelain_z, with_trailer

from .fake_system import FAKE_HEAD, Done, FakeSystem


def argvs(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [c.argv for c in fake.commands]


def status(fake: FakeSystem, porcelain: str) -> None:
    fake.reply(("git", "status"), Done(0, porcelain))


def test_status_is_asked_for_every_untracked_file_in_the_repo(repo: Path, fake: FakeSystem) -> None:
    status(fake, "")
    Git(repo).changed_paths()
    (command,) = [c for c in fake.commands if "status" in c.argv]
    assert command.argv == ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all")
    assert command.cwd == repo


def test_clean_and_changed(repo: Path, fake: FakeSystem) -> None:
    g = Git(repo)
    status(fake, "")
    assert g.is_clean()
    status(fake, "?? new.txt\0 M src/app.py\0")
    assert not g.is_clean()
    assert sorted(g.changed_paths()) == ["new.txt", "src/app.py"]


def test_rename_reports_both_paths(repo: Path, fake: FakeSystem) -> None:
    status(fake, "R  src/main.py\0src/app.py\0")
    assert sorted(Git(repo).changed_paths()) == ["src/app.py", "src/main.py"]


def test_copy_reports_both_paths_and_the_next_entry_is_separate(
    repo: Path, fake: FakeSystem
) -> None:
    status(fake, "C  b.txt\0a.txt\0?? c.txt\0")
    assert Git(repo).changed_paths() == ["b.txt", "a.txt", "c.txt"]


def test_parse_porcelain_ignores_empty_entries() -> None:
    assert parse_porcelain_z("") == []
    assert parse_porcelain_z("\0\0 M a\0\0") == ["a"]


def test_commit_stages_only_the_given_paths_then_commits(repo: Path, fake: FakeSystem) -> None:
    sha = Git(repo).commit(["a.txt"], "feat(s1): thing")
    assert sha == FAKE_HEAD
    git = [a for a in argvs(fake) if a[:1] == ("git",) and "rev-parse" not in a]
    assert git[:2] == [("git", "reset", "-q"), ("git", "add", "-A", "--", "a.txt")]
    commit = git[2]
    assert commit[:4] == ("git", "commit", "--no-verify", "-m")
    assert commit[4].startswith("feat(s1): thing") and CO_AUTHOR in commit[4]
    assert argvs(fake)[-1] == ("git", "rev-parse", "HEAD")


def test_commit_deletion_stages_the_removed_path(repo: Path, fake: FakeSystem) -> None:
    Git(repo).commit(["src/app.py"], "chore: rm")
    assert ("git", "add", "-A", "--", "src/app.py") in argvs(fake)


def test_commit_failure_raises(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "commit"), Done(1, "", "nothing to commit"))
    with pytest.raises(GitError, match="nothing to commit"):
        Git(repo).commit(["a.txt"], "x")


def test_revert_reverts_without_committing_then_commits_with_our_message(
    repo: Path, fake: FakeSystem
) -> None:
    fake.reply(("git", "log"), Done(0, "add a\n"))
    g = Git(repo)
    assert g.revert("abc123") == FAKE_HEAD
    seen = argvs(fake)
    assert ("git", "revert", "--no-commit", "abc123") in seen
    commit = next(a for a in seen if "commit" in a)
    assert commit[4].startswith('Revert "add a"') and CO_AUTHOR in commit[4]
    assert g.subject("abc123") == "add a"
    assert ("git", "log", "-1", "--format=%s", "abc123") in argvs(fake)


@pytest.mark.parametrize(("code", "ignored"), [(0, True), (1, False)])
def test_is_ignored_follows_check_ignore(
    repo: Path, fake: FakeSystem, code: int, ignored: bool
) -> None:
    fake.reply(("git", "check-ignore"), Done(code))
    assert Git(repo).is_ignored(".team/run/api-key") is ignored
    assert ("git", "check-ignore", "-q", "--", ".team/run/api-key") in argvs(fake)


def test_error_carries_the_command_and_stderr(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "nope-not-a-ref"), Done(128, "", "fatal: bad revision\n"))
    with pytest.raises(GitError, match="rev-parse") as info:
        Git(repo).run("rev-parse", "nope-not-a-ref")
    assert str(info.value) == "git rev-parse nope-not-a-ref: fatal: bad revision"


def test_run_returns_stdout(repo: Path, fake: FakeSystem) -> None:
    assert Git(repo).run("rev-parse", "HEAD") == FAKE_HEAD + "\n"


def test_with_trailer() -> None:
    assert with_trailer("x\n\n") == f"x\n\n{CO_AUTHOR}\n"


# ----- s13: is_repo (E11) ----------------------------------------------------


def test_is_repo_true_in_a_work_tree(repo: Path) -> None:
    assert Git(repo).is_repo()
    assert Git(repo / "src").is_repo()


def test_is_repo_false_outside_git(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "--git-dir"), Done(128, "", "fatal: not a git repository"))
    assert not Git(repo).is_repo()


def test_is_repo_false_for_a_missing_directory_without_asking_git(
    repo: Path, fake: FakeSystem
) -> None:
    assert not Git(repo / "nope").is_repo()
    assert not system.is_dir(repo / "nope")
    assert fake.commands == []


# ----- s29: options, attempt, branch ----------------------------------------


def test_attempt_returns_code_and_output_without_raising(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "--verify"), Done(128, "", "fatal: bad\n"))
    assert Git(repo).attempt("rev-parse", "--verify", "nope") == (128, "fatal: bad\n")


def test_attempt_joins_stdout_then_stderr(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "fetch"), Done(0, "out\n", "warn\n"))
    assert Git(repo).attempt("fetch") == (0, "out\nwarn\n")


def test_options_are_prepended_to_every_command(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "config"), Done(0, "Option Name\n"))
    g = Git(repo, ("-c", "user.name=Option Name"))
    assert g.run("config", "user.name").strip() == "Option Name"
    assert g.attempt("config", "user.name") == (0, "Option Name\n")
    assert (
        fake.commands
        == [system.Command(("git", "-c", "user.name=Option Name", "config", "user.name"), repo)] * 2
    )


@pytest.mark.parametrize(("code", "branch"), [(0, "main"), (1, None)])
def test_branch_names_the_checked_out_branch_or_none(
    repo: Path, fake: FakeSystem, code: int, branch: str | None
) -> None:
    fake.reply(("git", "symbolic-ref"), Done(code, "main\n" if code == 0 else "", ""))
    assert Git(repo).branch() == branch
    assert ("git", "symbolic-ref", "--quiet", "--short", "HEAD") in argvs(fake)
