"""Replays (s159 R1, R8): a first-parent line onto a new target, and a carried story's branch.

``Replayer`` walks the sprint branch's first-parent line in a scratch worktree: a plain commit is
cherry-picked, a story merge is rebuilt (the story's commits are rebased, then merged again with
the same message). ``StoryReplay`` rebases one story's branch onto the new sprint head.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from . import rewrite, story_rebase, system
from .boundary import ReplayProgress
from .events import Event, EventKind
from .git_ops import Git
from .story_branches import StoryRebase, merge_id, story_branch
from .upstream import SCRATCH_REBASE_ARGV, SyncOutcome
from .workspaces import Workspaces

if TYPE_CHECKING:
    from .dispatch import Runtime
    from .gates import StoryState

STASH_MESSAGE = "agile-team-replay"
LOG_LINE = "%H%x1f%s%x1f%P"


@dataclass(frozen=True)
class ReplaySpec:
    """What to replay: ``base..head`` onto ``target``; a conflict stops on ``scratch_branch``."""

    base: str
    head: str
    target: str
    scratch_branch: str


@dataclass
class ReplayResult:
    """How a replay ended: done (``tip``, ``moved``), or stopped (the story, commit and files)."""

    outcome: SyncOutcome
    tip: str = ""
    moved: dict[str, str] = field(default_factory=dict)
    story: str = ""
    commit: str = ""
    subject: str = ""
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Stopped:
    """The commit a replay stopped at, and what to tell DevOps about it."""

    commit: str
    story: str = ""


def read_log(git: Git, span: str) -> list[rewrite.ReplayLine]:
    """Every commit of ``span`` (``a..b``), oldest first, as ``(sha, subject, parents)``."""
    out = git.run("log", "--reverse", "--topo-order", f"--format={LOG_LINE}", span)
    rows = (line.split("\x1f") for line in out.splitlines() if line)
    return [(sha, subject, tuple(parents.split())) for sha, subject, parents in rows]


class Replayer:
    """Replays a first-parent line in the worktree at ``path``; resumes from its progress."""

    def __init__(self, git: Git, path: Path, save: Callable[[], None] = lambda: None) -> None:
        self.git = git
        self.path = path
        self.save = save

    @property
    def tree(self) -> Git:
        """Git in the replay worktree."""
        return Git(self.path)

    def run(self, spec: ReplaySpec, progress: ReplayProgress) -> ReplayResult:
        """R1: replay from ``progress.done``; stop at the first conflict, leaving it in the tree."""
        self.open_tree(spec, progress)
        progress.tip = progress.tip or spec.target
        commits = self.list_commits(spec)
        for index in range(progress.done, len(commits)):
            stopped = self.run_commit(commits[index], spec, progress)
            if stopped is not None:
                return self.describe_stop(stopped, spec, progress)
            progress.done = index + 1
            self.save()
        return self.finish(spec, progress)

    def is_stopped(self, spec: ReplaySpec, progress: ReplayProgress) -> bool:
        """True while the commit at ``progress.done`` is the one the replay stopped at."""
        return progress.done < len(self.list_commits(spec))

    def settle_stopped(self, spec: ReplaySpec, progress: ReplayProgress) -> None:
        """After DevOps resolved the stopped commit: take its result and count it done."""
        resolved = self.tree.head()
        if progress.story:
            commit = self.list_commits(spec)[progress.done]
            resolved = self.merge_story(commit, progress.tip, resolved)
        progress.tip, progress.story = resolved, ""
        progress.done += 1
        self.save()

    def remove(self) -> None:
        """Remove the replay worktree and its git entry."""
        self.git.attempt("worktree", "remove", "--force", str(self.path))
        self.git.attempt("worktree", "prune")

    def open_tree(self, spec: ReplaySpec, progress: ReplayProgress) -> None:
        """Make the detached worktree at the target (or at the tip, on a resume)."""
        if not system.is_dir(self.path):
            at = progress.tip or spec.target
            self.git.run("worktree", "add", "--detach", str(self.path), at)

    def list_commits(self, spec: ReplaySpec) -> list[str]:
        """The first-parent commits of ``base..head``, oldest first."""
        out = self.git.run("rev-list", "--first-parent", "--reverse", f"{spec.base}..{spec.head}")
        return out.split()

    def run_commit(self, commit: str, spec: ReplaySpec, progress: ReplayProgress) -> Stopped | None:
        """Replay one commit; the stop, or ``None`` when it went through."""
        parents = self.git.run("log", "-1", "--format=%P", commit).split()
        if len(parents) == 2:
            return self.run_story(commit, parents, (spec, progress))
        code, _ = self.tree.attempt("cherry-pick", "--allow-empty", commit)
        progress.tip = self.tree.head() if code == 0 else progress.tip
        return Stopped(commit) if code else None

    def run_story(
        self, merge: str, parents: list[str], at: tuple[ReplaySpec, ReplayProgress]
    ) -> Stopped | None:
        """Rebase the story's commits onto the tip, then merge them again."""
        spec, progress = at
        story = merge_id(self.git.subject(merge)) or merge
        self.git.run("branch", "-f", spec.scratch_branch, parents[1])
        argv = (*SCRATCH_REBASE_ARGV, "--onto", progress.tip, parents[0], spec.scratch_branch)
        if self.tree.attempt(*argv)[0] != 0:
            return Stopped(merge, story)
        progress.tip = self.merge_story(merge, progress.tip, self.tree.head())
        return None

    def merge_story(self, merge: str, tip: str, rebased: str) -> str:
        """Merge the rebased story onto ``tip`` with the original merge's full message."""
        message = self.git.run("log", "-1", "--format=%B", merge).rstrip("\n")
        self.tree.run("checkout", "--detach", tip)
        self.tree.run("merge", "--no-ff", "--no-edit", "-m", message, rebased)
        return self.tree.head()

    def describe_stop(
        self, stopped: Stopped, spec: ReplaySpec, progress: ReplayProgress
    ) -> ReplayResult:
        """Leave the stopped operation in the worktree, on the scratch branch for DevOps."""
        progress.story = stopped.story
        names = self.tree.attempt("diff", "--name-only", "--diff-filter=U")[1]
        files = tuple(n for n in names.splitlines() if n)
        subject = self.git.attempt("log", "-1", "--format=%s", stopped.commit)[1].strip()
        if not stopped.story:
            self.git.attempt("branch", "-f", spec.scratch_branch, self.tree.head())
            self.tree.attempt("symbolic-ref", "HEAD", f"refs/heads/{spec.scratch_branch}")
        return ReplayResult(
            SyncOutcome.CONFLICT, progress.tip, {}, stopped.story, stopped.commit, subject, files
        )

    def finish(self, spec: ReplaySpec, progress: ReplayProgress) -> ReplayResult:
        """Pair the old and the new commits, story by story (R4)."""
        old = read_log(self.git, f"{spec.base}..{spec.head}")
        new = read_log(self.git, f"{spec.target}..{progress.tip}")
        progress.moved = rewrite.pair_replay(old, new)
        return ReplayResult(SyncOutcome.REBASED, progress.tip, dict(progress.moved))


class StoryReplay:
    """R8: rebases a carried story's branch onto the new sprint head, on a new ``-r<k>`` branch."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def run(self, story: StoryState, head: str) -> ReplayResult:
        """Rebase ``story`` onto ``head``; a conflict queues a story rebase and changes nothing."""
        rt = self.runtime
        tree = Git(Workspaces(rt.git, rt.config).ensure(story, head))
        old = story.branch
        self.save_edits(tree, story)
        prefix = rt.config.upstream.story_prefix
        branch = story_branch(prefix, story.id, story.replays + 1)
        queued = StoryRebase(head, story.base_sha, old, branch, [], "")
        tree.run("checkout", "-b", branch)
        if tree.attempt(*SCRATCH_REBASE_ARGV, "--onto", head, story.base_sha)[0] != 0:
            return self.queue_rebase(tree, story, queued)
        self.restore_edits(tree, story)
        return self.take_over(story, queued)

    def save_edits(self, tree: Git, story: StoryState) -> None:
        """Stash a cut-off step's edits so the rebase starts clean."""
        if story.in_flight is not None:
            tree.run("stash", "push", "--include-untracked", "-m", STASH_MESSAGE)

    def restore_edits(self, tree: Git, story: StoryState) -> None:
        """Put the stashed edits back."""
        if story.in_flight is not None:
            tree.run("stash", "pop")

    def queue_rebase(self, tree: Git, story: StoryState, queued: StoryRebase) -> ReplayResult:
        """Abort the stopped rebase and queue it as the story's next step, with no round."""
        names = tree.attempt("diff", "--name-only", "--diff-filter=U")[1]
        files = [n for n in names.splitlines() if n]
        undo = (("rebase", "--abort"), ("checkout", queued.old), ("branch", "-D", queued.branch))
        for argv in undo:
            tree.attempt(*argv)
        devops = story_rebase.needs_devops(files, self.runtime.owners(story))
        role = "devops" if devops else story.developer or "developer"
        story.rebase = StoryRebase(queued.onto, queued.base, queued.old, queued.branch, files, role)
        return ReplayResult(SyncOutcome.CONFLICT, files=tuple(files))

    def take_over(self, story: StoryState, queued: StoryRebase) -> ReplayResult:
        """Remap the story's shas, take the new branch and tell the events."""
        rt, head = self.runtime, queued.onto
        up = rt.upstream
        new = rewrite.Listing(head, up.listing(f"{head}..{queued.branch}"))
        moved = rewrite.pair(up.listing(f"{story.base_sha}..{queued.old}"), new)
        rewrite.remap_state(rt.state, moved)
        tip = Git(Workspaces(rt.git, rt.config).path_of(story.id)).head()
        story.branch, story.base_sha, story.pushed = queued.branch, head, ""
        story.replays, story.worktree_head = story.replays + 1, tip
        data = {"action": "replayed", "branch": queued.branch, "base_sha": head}
        data["replays"] = story.replays
        rt.events.emit(Event(EventKind.STORY_BRANCH, None, story.id, data))
        return ReplayResult(SyncOutcome.REBASED, tip, moved)
