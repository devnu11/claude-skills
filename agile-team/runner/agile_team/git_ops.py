"""Thin git wrapper: status, scoped commits and reverts.

Every commit the runner makes carries ``CO_AUTHOR``. The runner never
autosquashes; ``fixup!`` commits are left for a human to squash.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

CO_AUTHOR = "Co-Authored-By: Claude <noreply@anthropic.com>"
RENAME_CODES = frozenset("RC")


class GitError(Exception):
    """A git command exited non-zero."""


@dataclass
class Git:
    """Runs git in one working tree."""

    repo: Path

    def run(self, *args: str) -> str:
        """Run ``git <args>`` and return stdout; raise ``GitError`` on failure."""
        proc = self._exec(*args)
        if proc.returncode != 0:
            raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
        return proc.stdout

    def _exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.repo, capture_output=True, text=True, check=False
        )

    def changed_paths(self) -> list[str]:
        """Paths with staged, unstaged or untracked changes (renames give both ends)."""
        out = self.run("status", "--porcelain=v1", "-z", "--untracked-files=all")
        return parse_porcelain_z(out)

    def is_clean(self) -> bool:
        return not self.changed_paths()

    def is_ignored(self, path: str) -> bool:
        """True when ``path`` is covered by a gitignore rule."""
        return self._exec("check-ignore", "-q", "--", path).returncode == 0

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").strip()

    def subject(self, sha: str) -> str:
        return self.run("log", "-1", "--format=%s", sha).strip()

    def commit(self, paths: Sequence[str], message: str) -> str:
        """Stage exactly ``paths`` (including deletions) and commit them."""
        self.run("reset", "-q")
        self.run("add", "-A", "--", *paths)
        self.run("commit", "--no-verify", "-m", with_trailer(message))
        return self.head()

    def revert(self, sha: str) -> str:
        """Revert ``sha`` with our own message (so it carries the trailer)."""
        self.run("revert", "--no-commit", sha)
        self.run("commit", "--no-verify", "-m", with_trailer(f'Revert "{self.subject(sha)}"'))
        return self.head()


def with_trailer(message: str) -> str:
    """Append the co-author trailer to ``message``."""
    return f"{message.rstrip()}\n\n{CO_AUTHOR}\n"


def parse_porcelain_z(out: str) -> list[str]:
    """Paths from ``git status --porcelain -z``; a rename's source follows its target."""
    return list(_porcelain_paths(iter(out.split("\0"))))


def _porcelain_paths(entries: Iterator[str]) -> Iterator[str]:
    for entry in filter(None, entries):
        yield entry[3:]
        if RENAME_CODES & set(entry[:2]):
            yield next(entries)
