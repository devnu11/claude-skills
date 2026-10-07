"""Glob matching and repo-relative resolution."""

from pathlib import Path

import pytest
from agile_team.paths import glob_to_regex, literal_root, matches, repo_relative, resolve_in


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
    ("glob", "root"), [("src/**", "src"), ("!tests/**", "tests"), ("**/*.py", ""), ("*.py", "")]
)
def test_literal_root(glob: str, root: str) -> None:
    assert literal_root(glob) == root


def test_repo_relative(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    (repo / "sub").mkdir(parents=True)
    assert repo_relative(repo, resolve_in(repo, "a.py")) == "a.py"
    assert repo_relative(repo, resolve_in(repo, str(repo / "sub/x"))) == "sub/x"
    assert repo_relative(repo, resolve_in(repo / "sub", "../x")) == "x"
    assert repo_relative(repo, resolve_in(repo, "/etc/passwd")) is None
