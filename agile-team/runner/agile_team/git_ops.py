"""Thin git wrapper: status, scoped commits and reverts.

Every commit the runner makes carries ``CO_AUTHOR``. The runner never
autosquashes; ``fixup!`` commits are left for a human to squash.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import stages, system

CO_AUTHOR = "Co-Authored-By: Claude <noreply@anthropic.com>"
RENAME_CODES = frozenset("RC")


class GitError(Exception):
    """A git command exited non-zero."""


@dataclass
class Git:
    """Runs git in one working tree."""

    repo: Path
    options: tuple[str, ...] = ()

    def run(self, *args: str) -> str:
        """Run ``git <args>`` and return stdout; raise ``GitError`` on failure."""
        proc = self._exec(*args)
        if proc.code != 0:
            raise GitError(f"git {' '.join(args)}: {proc.err.strip()}")
        return proc.out

    def attempt(self, *args: str) -> tuple[int, str]:
        """Run ``git <args>``; the exit code and stdout+stderr, never raising."""
        proc = self._exec(*args)
        return proc.code, proc.out + proc.err

    def branch(self) -> str | None:
        """The checked-out branch's name, or ``None`` on a detached HEAD."""
        code, out = self.attempt("symbolic-ref", "--quiet", "--short", "HEAD")
        return out.strip() if code == 0 else None

    def _exec(self, *args: str) -> system.Completed:
        proc = system.run(system.Command(("git", *self.options, *args), self.repo))
        stages.note(f"git {' '.join(args)}", proc.code)
        return proc

    def is_repo(self) -> bool:
        """True when ``repo`` is a directory inside a git work tree."""
        return system.is_dir(self.repo) and self._exec("rev-parse", "--git-dir").code == 0

    def changed_paths(self) -> list[str]:
        """Paths with staged, unstaged or untracked changes (renames give both ends)."""
        out = self.run("status", "--porcelain=v1", "-z", "--untracked-files=all")
        return parse_porcelain_z(out)

    def is_clean(self) -> bool:
        return not self.changed_paths()

    def is_ignored(self, path: str) -> bool:
        """True when ``path`` is covered by a gitignore rule."""
        return self._exec("check-ignore", "-q", "--", path).code == 0

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").strip()

    def content_digest(self, base: str) -> str:
        """Hash of the working tree's content relative to ``base``, committed or not."""
        diff = self.run("diff", "--name-only", "-z", base).split("\0")
        new = self.run("ls-files", "-z", "--others", "--exclude-standard").split("\0")
        paths = sorted({p for p in (*diff, *new) if p})
        blobs = self._blobs([p for p in paths if system.is_file(self.repo / p)])
        lines = [f"{p} {blobs.get(p, '-')}" for p in paths]
        return hashlib.sha256("\n".join([base, *lines]).encode()).hexdigest()

    def _blobs(self, paths: list[str]) -> dict[str, str]:
        """Blob hash for each existing path, from one ``hash-object`` call."""
        if not paths:
            return {}
        return dict(zip(paths, self.run("hash-object", "--", *paths).split(), strict=True))

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

    def is_ancestor(self, sha: str) -> bool:
        """True when ``sha`` is an ancestor of HEAD."""
        return self._exec("merge-base", "--is-ancestor", sha, "HEAD").code == 0

    def log_from(self, first: str) -> list[tuple[str, str]]:
        """(sha, subject) of ``first`` and every commit after it up to HEAD, oldest first."""
        out = self.run("log", "--reverse", "--format=%H%x1f%s", f"{first}..HEAD")
        rest = [tuple(line.split("\x1f", 1)) for line in out.splitlines() if line]
        return [(first, self.subject(first)), *rest]

    def revert_all(self, shas: Sequence[str], message: str) -> str:
        """Revert ``shas`` (newest first) in one commit; on failure abort and raise GitError."""
        self.run("reset", "-q")
        code, out = self.attempt("revert", "--no-commit", *shas)
        if code != 0:
            raise GitError(self._abort_revert(out))
        self.run("commit", "--no-verify", "-m", with_trailer(message))
        return self.head()

    def _abort_revert(self, output: str) -> str:
        """Abort a failed multi-revert; the conflicting paths, or the output."""
        _, names = self.attempt("diff", "--name-only", "--diff-filter=U")
        self.attempt("revert", "--abort")
        paths = ", ".join(names.split())
        return f"conflicts in {paths}" if paths else output.strip()


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
