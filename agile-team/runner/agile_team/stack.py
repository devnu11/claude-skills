"""Rebuilds the review branches in a scratch worktree.

Each review branch is derived from the team branch: the sprint's own unmerged
commits are cherry-picked onto the latest target (or the branch below). The
team branch is never touched. Conflict resolutions are made in the worktree and
replayed by ``git rerere`` on every later rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .boundary import StackEntry
from .git_ops import Git, GitError

REVIEW_DIR = "review"
REVIEW_GIT = (
    "-c", "rerere.enabled=true",
    "-c", "rerere.autoUpdate=true",
    "-c", "core.editor=true",
    "-c", "core.hooksPath=/dev/null",
)  # fmt: skip
PICK_HEAD = ("rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD")
UNMERGED_FILES = ("diff", "--name-only", "--diff-filter=U")


@dataclass(frozen=True)
class Conflict:
    """A cherry-pick that stopped on conflicting files."""

    branch: str
    commit: str
    subject: str
    files: tuple[str, ...]
    output: str


@dataclass(frozen=True)
class Build:
    """What one review branch is built from: its base and the commits to pick."""

    base: str
    picks: list[str]


@dataclass
class Rebuilder:
    """Builds review branches from the team branch in ``worktree``."""

    git: Git
    worktree: Path
    target: str
    wt: Git = field(init=False)

    def __post_init__(self) -> None:
        self.wt = Git(self.worktree, REVIEW_GIT)

    def prepare(self) -> None:
        """A clean detached worktree at the target."""
        if (self.worktree / ".git").exists():
            self.wt.attempt("cherry-pick", "--abort")
            self.checkout(self.target)
            return
        self.git.attempt("worktree", "prune")
        self.git.run("worktree", "add", "--detach", str(self.worktree), self.target)

    def checkout(self, ref: str) -> None:
        """Detach the worktree at ``ref`` and clear anything untracked."""
        self.wt.run("checkout", "--detach", "--force", ref)
        self.wt.run("clean", "-fd")

    def unmerged(self, top_end: str) -> set[str]:
        """Team commits whose patch is not in the target yet."""
        span = f"{self.target}...{top_end}"
        out = self.git.run(
            "log", "--no-merges", "--right-only", "--cherry-pick", "--format=%H", span
        )
        return set(out.split())

    def picks(self, entry: StackEntry, unmerged: set[str]) -> list[str]:
        """The entry's own commits that are not in the target, oldest first."""
        span = f"{entry.start}..{entry.end}"
        shas = self.git.run("rev-list", "--reverse", "--no-merges", span).split()
        return [sha for sha in shas if sha in unmerged]

    def build(self, entry: StackEntry, source: Build) -> Conflict | None:
        """Cherry-pick onto the base and point the branch at the result."""
        self.wt.run("checkout", "--detach", "--force", source.base)
        conflict = self._cherry_pick(entry, source.picks) if source.picks else None
        if conflict is None:
            entry.head = self.wt.head()
            self.wt.run("branch", "--force", entry.branch, "HEAD")
        return conflict

    def record(self, files: list[str]) -> None:
        """Keep the human-resolved files for rerere and end the pick."""
        self.wt.run("add", "--", *files)
        self.wt.attempt("rerere")
        self.wt.attempt("cherry-pick", "--abort")

    def _cherry_pick(self, entry: StackEntry, picks: list[str]) -> Conflict | None:
        code, output = self.wt.attempt("cherry-pick", *picks)
        for _ in range(len(picks) + 1):
            if code == 0:
                return None
            stopped = self._stopped(entry, output)
            if stopped:
                return stopped
            code, output = self.wt.attempt("cherry-pick", self._advance())
        raise GitError(output)

    def _stopped(self, entry: StackEntry, output: str) -> Conflict | None:
        """A conflict, ``None`` when the pick can go on, or a git error."""
        code, head = self.wt.attempt(*PICK_HEAD)
        if code != 0:
            raise GitError(output)
        files = tuple(self.wt.attempt(*UNMERGED_FILES)[1].split())
        if not files:
            return None
        commit = head.strip()
        return Conflict(entry.branch, commit, self.git.subject(commit), files, output)

    def _advance(self) -> str:
        """``--skip`` an empty pick, else ``--continue`` a resolved one."""
        empty = self.wt.attempt("diff", "--cached", "--quiet")[0] == 0
        return "--skip" if empty else "--continue"
