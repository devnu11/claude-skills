"""s126 SC13 end to end: `Git.content_digest` is stable across a commit and moves with content."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team.git_ops import Git

from ..conftest import git, set_git_identity


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with one tracked file."""
    root = tmp_path.resolve() / "r"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    set_git_identity(root)
    (root / "a.txt").write_text("one\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    return root


def test_the_digest_is_the_same_before_and_after_the_commit(repo: Path) -> None:
    """Edited tracked + new untracked file: committing them leaves the digest unchanged."""
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "a.txt").write_text("two\n")
    (repo / "b.txt").write_text("new\n")
    before = Git(repo).content_digest(base)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "step")
    assert Git(repo).content_digest(base) == before


def test_an_edit_or_a_new_file_changes_the_digest(repo: Path) -> None:
    """Each of an edit and a further untracked file moves the digest."""
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "a.txt").write_text("two\n")
    first = Git(repo).content_digest(base)
    (repo / "a.txt").write_text("three\n")
    second = Git(repo).content_digest(base)
    (repo / "c.txt").write_text("more\n")
    third = Git(repo).content_digest(base)
    assert len({first, second, third}) == 3
