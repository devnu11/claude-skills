"""Glob matching and repo-relative resolution."""

from pathlib import Path

import pytest
from agile_team.paths import (
    glob_to_regex,
    literal_root,
    matches,
    repo_relative,
    resolve_in,
    under_root,
)


@pytest.mark.parametrize(
    ("glob", "path", "expected"),
    [
        ("src/**", "src/a/b.py", True),
        ("src/**", "srcx/a.py", False),
        ("**/*.test.ts", "a/b/c.test.ts", True),
        ("**/*.test.ts", "c.test.ts", True),
        ("*.py", "a/b.py", False),
        ("*.py", "b.py", True),
        ("file?.md", "file1.md", True),
        ("a.b", "aXb", False),
    ],
)
def test_glob_to_regex(glob: str, path: str, expected: bool) -> None:
    assert bool(glob_to_regex(glob).match(path)) is expected


def test_matches_honours_negation() -> None:
    globs = ["tests/**", "!tests/e2e/**"]
    assert matches("tests/test_a.py", globs)
    assert not matches("tests/e2e/test_b.py", globs)
    assert not matches("src/a.py", globs)


def test_matches_with_only_negations_is_false() -> None:
    assert not matches("x", ["!y"])


@pytest.mark.parametrize(
    ("glob", "root"),
    [
        ("src/**", "src"),
        ("agile-team/runner/agile_team/**", "agile-team/runner/agile_team"),
        ("agile-team/runner/tests/e2e/**", "agile-team/runner/tests/e2e"),
        ("src/*.py", "src"),
        ("src/foo*/bar", "src"),
        ("src/[ab]/x", "src"),
        ("src/pkg/main.py", "src/pkg/main.py"),
        ("main.py", "main.py"),
        ("src/", "src"),
        ("**/*.py", ""),
        ("*.py", ""),
        ("!tests/e2e/**", ""),
        ("!tests/**", ""),
    ],
)
def test_literal_root(glob: str, root: str) -> None:
    assert literal_root(glob) == root


@pytest.mark.parametrize(
    ("path", "root", "expected"),
    [
        ("a", "a", True),
        ("a/b", "a", True),
        ("ab", "a", False),
        ("a", "a/b", False),
        ("agile-team", "agile-team/runner/agile_team", False),
    ],
)
def test_under_root(path: str, root: str, expected: bool) -> None:
    assert under_root(path, root) is expected


def test_repo_relative(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    (repo / "sub").mkdir(parents=True)
    assert repo_relative(repo, resolve_in(repo, "a.py")) == "a.py"
    assert repo_relative(repo, resolve_in(repo, str(repo / "sub/x"))) == "sub/x"
    assert repo_relative(repo, resolve_in(repo / "sub", "../x")) == "x"
    assert repo_relative(repo, resolve_in(repo, "/etc/passwd")) is None
