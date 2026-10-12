"""Selecting files: globs, tests, paths, git diffs and the index."""

from pathlib import Path

import pytest
from house_rules.config import Settings, TestPolicy
from house_rules.source import Origin, Selection, SourceError, collect_sources, is_selected, matches

from .conftest import git


def test_double_star_may_match_nothing() -> None:
    assert (
        matches("a.py", "**/*.py")
        and matches("x/y/a.py", "**/*.py")
        and not matches("a.txt", "**/*.py")
    )


def test_selection_filters(tmp_path: Path) -> None:
    settings = Settings(tmp_path, exclude=("gen/**",))
    assert is_selected("src/a.py", settings)
    assert not is_selected("gen/a.py", settings)
    assert not is_selected("tests/test_a.py", settings)
    assert not is_selected("README.md", settings)
    assert is_selected("tests/test_a.py", Settings(tmp_path, tests=TestPolicy.CHECK))


def test_walk_skips_virtualenvs_and_caches(tmp_path: Path) -> None:
    for name in ("a.py", "pkg/b.py", ".venv/c.py", "pkg/__pycache__/d.py", "notes.txt"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x = 1\n")
    paths = [source.path for source in collect_sources(Settings(tmp_path), Selection())]
    assert paths == ["a.py", "pkg/b.py"]


def test_given_paths_and_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text("")
    (tmp_path / "a.py").write_text("")
    monkeypatch.chdir(tmp_path)
    sources = collect_sources(Settings(tmp_path), Selection(("a.py", "pkg")))
    assert [source.path for source in sources] == ["a.py", "pkg/b.py"]


def test_paths_outside_the_root_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(SourceError, match="outside"):
        collect_sources(Settings(root), Selection((str(tmp_path),)))


def test_changed_and_staged(git_repo: Path) -> None:
    (git_repo / "old.py").write_text("x = 1\n")
    (git_repo / "gone.py").write_text("x = 1\n")
    git(git_repo, "add", ".")
    git(git_repo, "commit", "-qm", "base")
    (git_repo / "old.py").write_text("x = 2\n")
    (git_repo / "new.py").write_text("y = 1\n")
    (git_repo / "gone.py").unlink()
    git(git_repo, "add", "new.py")
    (git_repo / "new.py").write_text("y = 2\n")
    settings = Settings(git_repo)
    changed = collect_sources(settings, Selection(base="HEAD"))
    assert [source.path for source in changed] == ["new.py", "old.py"]
    staged = collect_sources(settings, Selection(origin=Origin.STAGED))
    assert [(source.path, source.text) for source in staged] == [("new.py", "y = 1\n")]


def test_git_failure_is_a_source_error(git_repo: Path) -> None:
    with pytest.raises(SourceError, match="git diff"):
        collect_sources(Settings(git_repo), Selection(base="no-such-ref"))
