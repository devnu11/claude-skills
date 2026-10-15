"""The scratch worktree where DevOps resolves a sprint-end rebase conflict (s151 AC6).

Prepare it, judge its result, drop it. The team checkout is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import system
from .checkout import operation
from .git_ops import Git
from .upstream import SCRATCH_REBASE_ARGV, Spans, Upstream

REBASE_DIR = "rebase"
REBASE_BRANCH = "agile-team/rebase-sprint-{sprint}"
UNFINISHED = "the rebase in {path} is not finished ({operation} in progress)"
OFF_BRANCH = "{path} is not on {branch}"
DIRTY = "{path} has uncommitted changes:\n{status}"
NOT_ON_TARGET = "{branch} is not based on {target}"
HAS_MERGES = "{branch} has merge commits: {shas}"
COMMITS_CHANGED = (
    "{branch}'s commits are not the team branch's commits rebased: a commit was added, "
    "dropped, squashed, reordered or reworded"
)
LOST_PATHS = "{branch} changed paths only one side touched: {paths}"
SHA_WIDTH = 12


@dataclass(frozen=True)
class ScratchRebase:
    """The scratch worktree and branch for one sprint's rebase conflict."""

    upstream: Upstream  # its git is the team checkout's
    path: Path
    branch: str

    @property
    def tree(self) -> Git:
        """Git in the scratch worktree."""
        return Git(self.path)

    def prepare(self, head: str) -> None:
        """Replace any leftover worktree and stop the same rebase in a fresh one."""
        self.remove()
        self.upstream.git.run("worktree", "add", "-B", self.branch, str(self.path), head)
        self.tree.attempt(*SCRATCH_REBASE_ARGV, self.upstream.target)

    def remove(self) -> None:
        """Remove the worktree, its git entry and a leftover directory."""
        team = self.upstream.git
        team.attempt("worktree", "remove", "--force", str(self.path))
        team.attempt("worktree", "prune")
        if system.exists(self.path):
            system.remove_tree(self.path)

    def drop(self) -> None:
        """Remove the worktree and delete its branch."""
        self.remove()
        self.upstream.git.attempt("branch", "-D", self.branch)

    def head(self) -> str:
        """The scratch worktree's HEAD."""
        return self.tree.head()

    def refusal(self, old: str) -> str:
        """The first problem with DevOps's result, else an empty string."""
        reasons = (check(self, old) for check in SCRATCH_CHECKS)
        return next((r for r in reasons if r), "")

    def _unfinished(self, old: str) -> str:
        found = operation(self.tree)
        return UNFINISHED.format(path=self.path, operation=found) if found else ""

    def _off_branch(self, old: str) -> str:
        if self.tree.branch() == self.branch:
            return ""
        return OFF_BRANCH.format(path=self.path, branch=self.branch)

    def _dirty(self, old: str) -> str:
        status = self.tree.run("status", "--porcelain").strip()
        return DIRTY.format(path=self.path, status=status) if status else ""

    def _off_target(self, old: str) -> str:
        target = self.upstream.target
        code = self.upstream.git.attempt("merge-base", "--is-ancestor", target, self.branch)[0]
        return NOT_ON_TARGET.format(branch=self.branch, target=target) if code else ""

    def _merges(self, old: str) -> str:
        span = f"{self.upstream.target}..{self.branch}"
        shas = self.upstream.git.run("rev-list", "--merges", span).split()
        if not shas:
            return ""
        return HAS_MERGES.format(branch=self.branch, shas=", ".join(s[:SHA_WIDTH] for s in shas))

    def _commits_changed(self, old: str) -> str:
        up, target = self.upstream, self.upstream.target
        done = up.find_upstreamed(old)
        wanted = [s.stamp for s in up.listing(f"{target}..{old}") if s.sha not in done]
        found = [s.stamp for s in up.listing(f"{target}..{self.branch}")]
        return "" if wanted == found else COMMITS_CHANGED.format(branch=self.branch)

    def _lost(self, old: str) -> str:
        up = self.upstream
        target_sha = up.git.run("rev-parse", up.target).strip()
        lost = up.find_lost_paths(Spans(old, old, target_sha, head=self.branch))
        if not lost:
            return ""
        return LOST_PATHS.format(branch=self.branch, paths=", ".join(lost))


SCRATCH_CHECKS = (
    ScratchRebase._unfinished,
    ScratchRebase._off_branch,
    ScratchRebase._dirty,
    ScratchRebase._off_target,
    ScratchRebase._merges,
    ScratchRebase._commits_changed,
    ScratchRebase._lost,
)
