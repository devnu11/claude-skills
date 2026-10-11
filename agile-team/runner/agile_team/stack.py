"""Rebuilds the review branches in a scratch worktree, one per sprint, stacked.

The team branch is never touched. Each review branch is made again from it: the
sprint's own unmerged commits are cherry-picked onto the branch below (the
bottom one onto the target). ``git rerere`` replays conflict resolutions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .boundary import StackEntry
from .git_ops import Git, GitError

REVIEW_DIR = "review"
REVIEW_GIT = (
    "-c",
    "rerere.enabled=true",
    "-c",
    "rerere.autoUpdate=true",
    "-c",
    "core.editor=true",
    "-c",
    "core.hooksPath=/dev/null",
)
PICK_HEAD = ("rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD")
CONFLICTED = ("diff", "--name-only", "--diff-filter=U")


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
    """What a review branch is built from: its base and the commits to pick."""

    base: str
    picks: list[str]


@dataclass
class Rebuilder:
    """Makes review branches from the team branch in ``worktree``."""

    git: Git
    worktree: Path
    target: str

    def __post_init__(self) -> None:
        self.wt = Git(self.worktree, REVIEW_GIT)

    def prepare(self) -> None:
        """A clean detached worktree at the target, made if missing."""
        if not (self.worktree / ".git").exists():
            self.git.run("worktree", "prune")
            self.git.run("worktree", "add", "--detach", str(self.worktree), self.target)
            return
        self.wt.attempt("cherry-pick", "--abort")
        self.checkout(self.target)

    def checkout(self, ref: str) -> None:
        """Detach the worktree at ``ref`` and remove anything untracked."""
        self.wt.run("checkout", "--detach", "--force", ref)
        self.wt.run("clean", "-fd")

    def unmerged(self, top_end: str) -> set[str]:
        """Team commits up to ``top_end`` whose patch is not in the target yet."""
        span = f"{self.target}...{top_end}"
        out = self.git.run(
            "log", "--no-merges", "--right-only", "--cherry-pick", "--format=%H", span
        )
        return set(out.split())

    def picks(self, entry: StackEntry, unmerged: set[str]) -> list[str]:
        """The entry's range, oldest first, without commits already in the target."""
        span = f"{entry.start}..{entry.end}"
        shas = self.git.run("rev-list", "--reverse", "--no-merges", span).split()
        return [sha for sha in shas if sha in unmerged]

    def build(self, entry: StackEntry, source: Build) -> Conflict | None:
        """Make the entry's branch from ``source``; a ``Conflict`` leaves the pick in progress."""
        self.wt.run("checkout", "--detach", "--force", source.base)
        conflict = self._cherry_pick(entry.branch, source.picks) if source.picks else None
        if conflict is None:
            self.wt.run("branch", "--force", entry.branch, "HEAD")
            entry.head = self.wt.head()
        return conflict

    def record(self, files: list[str]) -> None:
        """Stage the resolved files, let rerere learn them, and stop the pick."""
        self.wt.run("add", "--", *files)
        self.wt.run("rerere")
        self.wt.attempt("cherry-pick", "--abort")

    def _cherry_pick(self, branch: str, picks: list[str]) -> Conflict | None:
        code, output = self.wt.attempt("cherry-pick", *picks)
        for _ in range(len(picks) + 1):
            if code == 0:
                return None
            move = self._next_move(branch, output)
            if isinstance(move, Conflict):
                return move
            code, output = self.wt.attempt(*move)
        raise GitError(output.strip())

    def _next_move(self, branch: str, output: str) -> Conflict | tuple[str, ...]:
        if self.wt.attempt(*PICK_HEAD)[0] != 0:
            raise GitError(output.strip())
        files = tuple(self.wt.attempt(*CONFLICTED)[1].split())
        if files:
            return self._conflict(branch, files, output)
        empty = self.wt.attempt("diff", "--cached", "--quiet")[0] == 0
        return ("cherry-pick", "--skip" if empty else "--continue")

    def _conflict(self, branch: str, files: tuple[str, ...], output: str) -> Conflict:
        commit = self.wt.run(*PICK_HEAD).strip()
        return Conflict(branch, commit, self.wt.subject(commit), files, output)
