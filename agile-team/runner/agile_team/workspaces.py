"""Story worktrees (s159 B1, B2, B5, C3, E1, I3): one ``git worktree`` per open story.

Every path is built from ``config.run_dir``, which ``Config.get_worktree_config`` keeps at
the main checkout's ``.team/run``, so nothing lands outside the repository.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from . import system
from .config import Config
from .gates import StoryState
from .git_ops import Git, parse_porcelain_z
from .story_branches import format_story_branch

WORKTREES = "worktrees"
LAND = "land"
REPLAY = "replay"
SCRATCH_DIRS = (LAND, REPLAY)


class Workspaces:
    """Makes, removes and inspects the story worktrees of one run."""

    def __init__(self, git: Git, config: Config) -> None:
        self.git = git
        self.config = config

    def get_path(
        self,
        story_id: str,
    ) -> Path:
        """B2: where the story's worktree lives."""
        return self.config.run_dir / WORKTREES / story_id

    def ensure(self, story: StoryState, sprint_head: str) -> Path:
        """B1: give the story a branch (once) and a worktree on it; return the worktree."""
        if not story.branch:
            self._fork(story, sprint_head)
        path = self.get_path(story.id)
        if not system.is_dir(path):
            self.git.run("worktree", "add", str(path), story.branch)
        story.worktree_head = Git(path).head()
        return path

    def _fork(self, story: StoryState, sprint_head: str) -> None:
        branch = format_story_branch(self.config.upstream.story_prefix, story.id, story.replays)
        self.git.run("branch", branch, sprint_head)
        story.branch, story.base_sha = branch, sprint_head

    def remove(self, story_id: str) -> None:
        """E1, E2: take the worktree away; the branch stays."""
        self._remove_path(self.get_path(story_id))

    def _remove_path(self, path: Path) -> None:
        self.git.attempt("worktree", "remove", "--force", str(path))
        if system.exists(path):
            system.remove_tree(path)

    def count_open(
        self,
        stories: Iterable[StoryState],
    ) -> int:
        """C3: the stories that have a worktree."""
        return sum(1 for story in stories if story.worktree_head)

    def list_changed_files(
        self,
        story_id: str,
    ) -> list[str]:
        """B5: the paths git reports as changed in the story's worktree."""
        tree = Git(self.get_path(story_id))
        return parse_porcelain_z(tree.run("status", "--porcelain", "-z", "--untracked-files=all"))

    def prune_stale(
        self,
        keep: frozenset[str],
    ) -> list[str]:
        """I3: remove worktrees of stories not in ``keep``, plus the land and replay ones."""
        gone = [name for name in self.stored_worktrees if name not in keep]
        for name in gone:
            self.remove(name)
        for scratch in SCRATCH_DIRS:
            if scratch not in keep:
                self._remove_scratch(self.config.run_dir / scratch)
        self.git.attempt("worktree", "prune")
        return gone

    @property
    def stored_worktrees(self) -> list[str]:
        """The story ids that have a worktree directory."""
        folder = self.config.run_dir / WORKTREES
        return sorted(p.name for p in system.list_dir(folder)) if system.is_dir(folder) else []

    def _remove_scratch(self, path: Path) -> None:
        if system.is_dir(path):
            self._remove_path(path)
