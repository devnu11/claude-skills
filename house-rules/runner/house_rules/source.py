"""Which files to check, and their text: the work tree, the index or a diff against a base."""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .config import Settings, TestPolicy

PRUNED_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", ".tox", ".mypy_cache",
     ".pytest_cache", ".ruff_cache"}
)  # fmt: skip


class SourceError(Exception):
    """A git command failed or a path is outside the checked root."""


class Origin(StrEnum):
    """Where file contents come from."""

    WORKTREE = "worktree"
    STAGED = "staged"


@dataclass(frozen=True)
class Selection:
    """What to check: explicit paths, files changed against a base, or everything."""

    paths: tuple[str, ...] = ()
    base: str | None = None
    origin: Origin = Origin.WORKTREE


@dataclass(frozen=True)
class Source:
    """One file to check: its path relative to the root, and its text."""

    path: str
    text: str


def matches(path: str, pattern: str) -> bool:
    """Glob match where ``*`` crosses directories and ``**/`` may match nothing."""
    if fnmatch.fnmatchcase(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])


def is_selected(path: str, settings: Settings) -> bool:
    """Included, not excluded, and not a test unless tests are checked."""
    if not any(matches(path, pattern) for pattern in settings.include):
        return False
    if any(matches(path, pattern) for pattern in settings.exclude):
        return False
    is_test = any(matches(path, pattern) for pattern in settings.test_globs)
    return settings.tests is TestPolicy.CHECK or not is_test


def collect_sources(settings: Settings, selection: Selection) -> list[Source]:
    """The selected files with their text, sorted by path."""
    paths = sorted({path for path in list_candidates(settings, selection)})
    chosen = [path for path in paths if is_selected(path, settings)]
    return [Source(path, read_text(settings, path, selection.origin)) for path in chosen]


def list_candidates(settings: Settings, selection: Selection) -> list[str]:
    """Paths before filtering: from git when asked, else the given paths, else every file."""
    if selection.origin is Origin.STAGED:
        return run_git(
            settings.root, ["diff", "--cached", "--name-only", "--relative", "--diff-filter=d"]
        )
    if selection.base:
        return run_git(
            settings.root, ["diff", "--name-only", "--relative", "--diff-filter=d", selection.base]
        )
    if selection.paths:
        return [
            path for given in selection.paths for path in expand_path(settings.root, Path(given))
        ]
    return list_files(settings.root, settings.root)


def expand_path(root: Path, given: Path) -> list[str]:
    """A file as itself, a directory as every file under it; relative to ``root``."""
    resolved = given.resolve()
    if not resolved.is_relative_to(root):
        raise SourceError(f"{given} is outside {root}")
    if resolved.is_dir():
        return list_files(root, resolved)
    return [resolved.relative_to(root).as_posix()]


def list_files(root: Path, directory: Path) -> list[str]:
    """Every file under ``directory``, skipping VCS, virtualenv and cache directories."""
    found = []
    for current, directories, files in os.walk(directory):
        directories[:] = [name for name in directories if name not in PRUNED_DIRECTORIES]
        base = Path(current).relative_to(root)
        found += [(base / name).as_posix() for name in files]
    return found


def read_text(settings: Settings, path: str, origin: Origin) -> str:
    """The file's text from the work tree or, for staged checks, from the index."""
    if origin is Origin.STAGED:
        return "\n".join(run_git(settings.root, ["show", f":./{path}"])) + "\n"
    return (settings.root / path).read_text(encoding="utf-8", errors="replace")


def run_git(root: Path, arguments: list[str]) -> list[str]:
    """The output lines of ``git -C root <arguments>``, or a ``SourceError``."""
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SourceError(f"git {' '.join(arguments)}: {result.stderr.strip()}")
    return result.stdout.splitlines()
