"""Thin git wrapper: status, scoped commits, fixups and reverts.

Every commit the runner makes carries ``CO_AUTHOR``. The runner never
autosquashes; ``fixup!`` commits are left for a human to squash.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

CO_AUTHOR = "Co-Authored-By: Claude <noreply@anthropic.com>"


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
        return _parse_porcelain_z(out)

    def is_clean(self) -> bool:
        return not self.changed_paths()

    def is_ignored(self, path: str) -> bool:
        """True when ``path`` is covered by a gitignore rule."""
        return self._exec("check-ignore", "-q", "--", path).returncode == 0

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").strip()

    def commit(self, paths: Sequence[str], message: str) -> str:
        """Stage exactly ``paths`` (including deletions) and commit them."""
        self._stage_only(paths)
        self.run("commit", "--no-verify", "-m", with_trailer(message))
        return self.head()

    def commit_fixup(self, paths: Sequence[str], target: str) -> str:
        """Commit ``paths`` as ``fixup! <target subject>``; never autosquashes."""
        self._stage_only(paths)
        subject = self.run("log", "-1", "--format=%s", target).strip()
        self.run("commit", "--no-verify", "-m", with_trailer(f"fixup! {subject}"))
        return self.head()

    def revert(self, sha: str, message: str) -> str:
        """Revert ``sha`` with our own message (so it carries the trailer)."""
        self.run("revert", "--no-commit", sha)
        self.run("commit", "--no-verify", "-m", with_trailer(message))
        return self.head()

    def _stage_only(self, paths: Sequence[str]) -> None:
        self.run("reset", "-q")
        self.run("add", "-A", "--", *paths)


def with_trailer(message: str) -> str:
    """Append the co-author trailer to ``message``."""
    return f"{message.rstrip()}\n\n{CO_AUTHOR}\n"


def _parse_porcelain_z(out: str) -> list[str]:
    paths: list[str] = []
    entries = iter(out.split("\0"))
    for entry in entries:
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in status or "C" in status:
            paths.append(next(entries))
    return paths
