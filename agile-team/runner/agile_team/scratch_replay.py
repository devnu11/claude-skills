"""The replay worktree where DevOps resolves a replay conflict (s159 R2).

The stopped cherry-pick or rebase is already in the worktree; ``ScratchReplay`` attaches it to a
scratch branch, judges DevOps's result story by story, and drops the worktree. The team checkout
is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import system
from .boundary import ReplayProgress
from .checkout import operation
from .git_ops import Git
from .story_branches import merge_id

REPLAY_DIR = "replay"
REPLAY_BRANCH = "agile-team/replay-sprint-{sprint}"
UNFINISHED = "the operation in {path} is not finished ({operation} in progress)"
OFF_BRANCH = "{path} is not on {branch}"
DIRTY = "{path} has uncommitted changes:\n{status}"
NOT_ON_TIP = "{branch} is not based on the replay so far ({tip})"
STORY_COMMITS = (
    "{branch}'s commits for {story} are not the old ones replayed: a commit was added, dropped, "
    "squashed, reordered or reworded, or one is a merge"
)
LOST_PATHS = "{branch} changed paths only one side touched: {paths}"
SHA_WIDTH = 12


@dataclass(frozen=True)
class ScratchReplay:
    """The replay worktree and scratch branch of one sprint's replay conflict."""

    git: Git  # the team checkout's
    path: Path
    branch: str

    @property
    def tree(self) -> Git:
        """Git in the replay worktree."""
        return Git(self.path)

    def prepare(self) -> None:
        """Put the stopped operation's worktree on the scratch branch (a cherry-pick already is)."""
        self.git.attempt("branch", "-f", self.branch, self.tree.head())
        self.tree.attempt("symbolic-ref", "HEAD", f"refs/heads/{self.branch}")

    def remove(self) -> None:
        """Remove the worktree, its git entry and a leftover directory."""
        self.git.attempt("worktree", "remove", "--force", str(self.path))
        self.git.attempt("worktree", "prune")
        if system.exists(self.path):
            system.remove_tree(self.path)

    def drop(self) -> None:
        """Remove the worktree and delete its branch."""
        self.remove()
        self.git.attempt("branch", "-D", self.branch)

    def find_refusal(self, progress: ReplayProgress) -> str:
        """The first problem with DevOps's result, else an empty string."""
        reasons = (check(self, progress) for check in SCRATCH_CHECKS)
        return next((r for r in reasons if r), "")

    def _check_unfinished(self, progress: ReplayProgress) -> str:
        found = operation(self.tree)
        return UNFINISHED.format(path=self.path, operation=found) if found else ""

    def _check_dirty(self, progress: ReplayProgress) -> str:
        status = self.tree.run("status", "--porcelain").strip()
        return DIRTY.format(path=self.path, status=status) if status else ""

    def _check_off_branch(self, progress: ReplayProgress) -> str:
        if self.tree.branch() == self.branch:
            return ""
        return OFF_BRANCH.format(path=self.path, branch=self.branch)

    def _check_off_tip(self, progress: ReplayProgress) -> str:
        tip = progress.tip or progress.target
        code = self.tree.attempt("merge-base", "--is-ancestor", tip, "HEAD")[0]
        return NOT_ON_TIP.format(branch=self.branch, tip=tip[:SHA_WIDTH]) if code else ""

    def _check_story_commits(self, progress: ReplayProgress) -> str:
        if progress.done >= len(self._list_old_line(progress)):
            return ""
        wanted, story = self._list_old_subjects(progress)
        found = self._list_new_subjects(progress)
        merges = self.tree.run("rev-list", "--merges", f"{progress.tip}..HEAD").split()
        if wanted == found and not merges:
            return ""
        return STORY_COMMITS.format(branch=self.branch, story=story or "the commit")

    def _list_old_line(self, progress: ReplayProgress) -> list[str]:
        line = f"{progress.base}..{progress.old_head}"
        return self.git.run("rev-list", "--first-parent", "--reverse", line).split()

    def _find_old_commit(self, progress: ReplayProgress) -> str:
        return self._list_old_line(progress)[progress.done]

    def _list_old_subjects(self, progress: ReplayProgress) -> tuple[list[str], str]:
        commit = self._find_old_commit(progress)
        subject = self.git.subject(commit)
        if not progress.story:
            return [subject], ""
        span = f"{commit}^1..{commit}^2"
        out = self.git.run("log", "--reverse", "--format=%s", span)
        return out.splitlines(), merge_id(subject) or progress.story

    def _list_new_subjects(self, progress: ReplayProgress) -> list[str]:
        out = self.tree.run("log", "--reverse", "--format=%s", f"{progress.tip}..HEAD")
        return out.splitlines()


SCRATCH_CHECKS = (
    ScratchReplay._check_unfinished,
    ScratchReplay._check_dirty,
    ScratchReplay._check_off_branch,
    ScratchReplay._check_off_tip,
    ScratchReplay._check_story_commits,
)
