"""Git wrapper against real throwaway repos."""

from pathlib import Path

import pytest
from agile_team.git_ops import CO_AUTHOR, Git, GitError, with_trailer

from .conftest import git


def test_clean_and_changed(repo: Path) -> None:
    g = Git(repo)
    assert g.is_clean()
    (repo / "new.txt").write_text("n")
    (repo / "src/app.py").write_text("x = 2\n")
    assert sorted(g.changed_paths()) == ["new.txt", "src/app.py"]


def test_rename_reports_both_paths(repo: Path) -> None:
    git(repo, "mv", "src/app.py", "src/main.py")
    assert sorted(Git(repo).changed_paths()) == ["src/app.py", "src/main.py"]


def test_commit_only_given_paths(repo: Path) -> None:
    g = Git(repo)
    (repo / "a.txt").write_text("a")
    (repo / "b.txt").write_text("b")
    sha = g.commit(["a.txt"], "feat(s1): thing")
    assert g.head() == sha
    assert g.changed_paths() == ["b.txt"]
    msg = git(repo, "log", "-1", "--format=%B")
    assert msg.startswith("feat(s1): thing") and CO_AUTHOR in msg


def test_commit_deletion(repo: Path) -> None:
    (repo / "src/app.py").unlink()
    Git(repo).commit(["src/app.py"], "chore: rm")
    assert Git(repo).is_clean()


def test_revert(repo: Path) -> None:
    g = Git(repo)
    (repo / "a.txt").write_text("a")
    sha = g.commit(["a.txt"], "add a")
    g.revert(sha)
    assert not (repo / "a.txt").exists()
    msg = git(repo, "log", "-1", "--format=%B")
    assert msg.startswith('Revert "add a"') and CO_AUTHOR in msg
    assert g.subject(sha) == "add a"


def test_is_ignored(repo: Path) -> None:
    g = Git(repo)
    assert g.is_ignored(".team/run/api-key")
    assert not g.is_ignored("src/app.py")


def test_error(repo: Path) -> None:
    with pytest.raises(GitError, match="rev-parse"):
        Git(repo).run("rev-parse", "nope-not-a-ref")


def test_with_trailer() -> None:
    assert with_trailer("x\n\n") == f"x\n\n{CO_AUTHOR}\n"
