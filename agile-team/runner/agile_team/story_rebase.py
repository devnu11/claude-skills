"""A story branch rebased onto a newer sprint head by a role (s159 O1, S2, S3).

The runner starts the rebase and lets it stop at the conflict; the role resolves it in the
story's worktree; ``refusal`` judges the result before the story adopts the new branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import system
from .checkout import operation
from .git_ops import Git
from .owners import Owners
from .story_branches import StoryRebase
from .upstream import SCRATCH_REBASE_ARGV

UNFINISHED = "the rebase is not finished ({operation} in progress)"
DIRTY = "the worktree has uncommitted changes:\n{status}"
OFF_BRANCH = "HEAD is not on {branch}"
NOT_ON_BASE = "{branch} is not based on {onto}"
COMMITS_CHANGED = (
    "{branch}'s commits are not {old}'s commits rebased: a commit was added, dropped, squashed, "
    "reordered or reworded"
)
DEVOPS = "devops"
HEAD_NAME = "rebase-merge/head-name"
STORY_REBASE_LINES = (
    "Story {id}: its branch moves onto the sprint head. The runner started `git rebase --onto "
    "{onto} {base}` in this worktree, on the branch {branch}; it stopped on conflicts in: {files}.",
    "Resolve the conflicts in those files only: edit them, `git add` them and run `git rebase "
    "--continue` until it is done. Never merge, squash, reorder, reword, skip or drop a commit. "
    "Then hand off done.",
    "Move no other branch: {branch} is the one local branch this step may move, and the runner "
    "refuses git commands that move another.",
)
BRANCH_MOVED = "branch {branch} moved from {old} to {new}; the runner put it back"
BRANCH_STUCK = "branch {branch} moved from {old} to {new} and moved again; the runner could not put it back"
PUT_BACK_MESSAGE = "agile-team: put back after a story rebase step"
HEADS_FORMAT = "--format=%(refname:short)\t%(objectname)\t%(worktreepath)"


@dataclass(frozen=True)
class MovedBranch:
    """A local branch whose head differs from its value at the step's start (s176)."""

    branch: str
    old: str
    new: str


def is_for_devops(
    files: list[str],
    owners: Owners,
) -> bool:
    """O1: DevOps resolves it when every file is DevOps's or nobody's; else the developer."""
    writers = (owners.writer_of(f) for f in files)
    return all(w is None or w.role == DEVOPS for w in writers)


def prepare(git: Git, rebase: StoryRebase) -> None:
    """S2: branch from the old tip and start the rebase; it stops at the conflict.

    A worktree already on the rebase branch, or stopped part-way through rebasing it, is
    left as it is: the step resumes it. A leftover rebase branch is reset to the old tip.
    """
    if is_resumable(git, rebase):
        return
    git.run("checkout", "-B", rebase.branch)
    git.attempt(*SCRATCH_REBASE_ARGV, "--onto", rebase.onto, rebase.base)


def read_branch_heads(git: Git, rebase: StoryRebase) -> dict[str, str]:
    """s176: the heads of the local branches the step could move, but the rebase branch.

    Branches checked out in another worktree are left out: git refuses to move them.
    """
    rows = (line.split("\t") for line in git.run("for-each-ref", HEADS_FORMAT, "refs/heads").splitlines())
    free = ("", str(git.repo))
    return {n: sha for n, sha, where in rows if where in free and n != rebase.branch}


def list_moved_branches(git: Git, rebase: StoryRebase) -> list[MovedBranch]:
    """s176: the branches whose head is not the one recorded at the step's start."""
    now = read_branch_heads(git, rebase)
    return [MovedBranch(n, old, now[n]) for n, old in rebase.heads.items() if now.get(n, old) != old]


def put_back_branch(git: Git, moved: MovedBranch) -> str:
    """s176: set the branch back to its old sha if it is still at its new one; say what happened."""
    code, _ = git.attempt(
        "update-ref", "-m", PUT_BACK_MESSAGE, f"refs/heads/{moved.branch}", moved.old, moved.new
    )
    template = BRANCH_STUCK if code else BRANCH_MOVED
    return template.format(branch=moved.branch, old=moved.old, new=moved.new)


def is_resumable(git: Git, rebase: StoryRebase) -> bool:
    """S3: the worktree is on the rebase branch, or stopped part-way through rebasing it."""
    if operation(git) is None:
        return git.branch() == rebase.branch
    return _read_rebased_ref(git) == f"refs/heads/{rebase.branch}"


def _read_rebased_ref(git: Git) -> str:
    """The branch an interrupted ``rebase --merge`` is rebasing, or ``""``."""
    path = Path(git.run("rev-parse", "--absolute-git-dir").strip()) / HEAD_NAME
    return system.read_text(path).strip() if system.exists(path) else ""


def find_refusal(
    git: Git,
    rebase: StoryRebase,
) -> str | None:
    """S3: the first problem with the role's result, else ``None``."""
    checks = (
        _find_unfinished,
        _find_dirty,
        _find_off_branch,
        _find_off_base,
        _find_changed_commits,
    )
    reasons = (check(git, rebase) for check in checks)
    return next((r for r in reasons if r), None)


def find_unfinished(git: Git) -> str | None:
    """S3: the git operation still in progress in the worktree, as a refusal; else ``None``."""
    found = operation(git)
    return UNFINISHED.format(operation=found) if found else None


def _find_unfinished(git: Git, rebase: StoryRebase) -> str | None:
    return find_unfinished(git)


def _find_dirty(git: Git, rebase: StoryRebase) -> str | None:
    status = git.run("status", "--porcelain").strip()
    return DIRTY.format(status=status) if status else None


def _find_off_branch(git: Git, rebase: StoryRebase) -> str | None:
    return None if git.branch() == rebase.branch else OFF_BRANCH.format(branch=rebase.branch)


def _find_off_base(git: Git, rebase: StoryRebase) -> str | None:
    code = git.attempt("merge-base", "--is-ancestor", rebase.onto, "HEAD")[0]
    return NOT_ON_BASE.format(branch=rebase.branch, onto=rebase.onto) if code else None


def _find_changed_commits(git: Git, rebase: StoryRebase) -> str | None:
    wanted = _list_subjects(git, f"{rebase.base}..{rebase.old}")
    found = _list_subjects(git, f"{rebase.onto}..HEAD")
    if wanted == found:
        return None
    return COMMITS_CHANGED.format(branch=rebase.branch, old=rebase.old)


def _list_subjects(git: Git, span: str) -> list[str]:
    return git.run("log", "--reverse", "--format=%s", span).splitlines()
