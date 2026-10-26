"""A story branch rebased onto a newer sprint head by a role (s159 O1, S2, S3).

The runner starts the rebase and lets it stop at the conflict; the role resolves it in the
story's worktree; ``refusal`` judges the result before the story adopts the new branch.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
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
COMMITS_CHANGED = "{branch}'s commits are not {old}'s commits rebased, by subject and in order:"
SHA_WIDTH = 12
EXTRA_LINE = "- extra {sha} {subject} (made by {maker})"
MISSING_LINE = "- missing {sha} {subject} (on {old})"
CHANGED_LINE = "- changed {old_sha} {old_subject} -> {sha} {subject} (made by {maker})"
RUNNER = "the runner"
ROLE = "the role"
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
BRANCH_STUCK = (
    "branch {branch} moved from {old} to {new} and moved again; the runner could not put it back"
)
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
    rows = (
        line.split("\t")
        for line in git.run("for-each-ref", HEADS_FORMAT, "refs/heads").splitlines()
    )
    here = system.resolve(git.repo)
    return {n: sha for n, sha, where in rows if _is_free(where, here) and n != rebase.branch}


def _is_free(where: str, here: Path) -> bool:
    """Whether a branch's worktree path is none or this step's worktree (resolved)."""
    return not where or system.resolve(Path(where)) == here


def list_moved_branches(git: Git, rebase: StoryRebase) -> list[MovedBranch]:
    """s176: the branches whose head is not the one recorded at the step's start."""
    now = read_branch_heads(git, rebase)
    return [
        MovedBranch(n, old, now[n]) for n, old in rebase.heads.items() if now.get(n, old) != old
    ]


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


type Opcode = tuple[str, int, int, int, int]


@dataclass(frozen=True)
class ListedCommit:
    """One commit of a span: its sha and subject."""

    sha: str
    subject: str


@dataclass(frozen=True)
class CommitLists:
    """The old branch's commits, the rebased ones, and the runner's own (R6)."""

    wanted: list[ListedCommit]
    found: list[ListedCommit]
    rebase: StoryRebase


def list_commits(git: Git, span: str) -> list[ListedCommit]:
    """The span's commits, oldest first."""
    out = git.run("log", "--reverse", "--format=%H%x09%s", span)
    rows = (line.split("\t", 1) for line in out.splitlines())
    return [ListedCommit(sha, subject) for sha, subject in rows]


def _get_maker(lists: CommitLists, sha: str) -> str:
    return RUNNER if sha in lists.rebase.made else ROLE


def _list_missing(lists: CommitLists, opcode: Opcode) -> list[str]:
    _, i1, i2, _, _ = opcode
    old = lists.rebase.old
    return [
        MISSING_LINE.format(sha=c.sha[:SHA_WIDTH], subject=c.subject, old=old)
        for c in lists.wanted[i1:i2]
    ]


def _list_extra(lists: CommitLists, opcode: Opcode) -> list[str]:
    _, _, _, j1, j2 = opcode
    return [
        EXTRA_LINE.format(sha=c.sha[:SHA_WIDTH], subject=c.subject, maker=_get_maker(lists, c.sha))
        for c in lists.found[j1:j2]
    ]


def _list_replaced(lists: CommitLists, opcode: Opcode) -> list[str]:
    _, i1, i2, j1, j2 = opcode
    paired = min(i2 - i1, j2 - j1)
    changed = [
        CHANGED_LINE.format(
            old_sha=o.sha[:SHA_WIDTH],
            old_subject=o.subject,
            sha=n.sha[:SHA_WIDTH],
            subject=n.subject,
            maker=_get_maker(lists, n.sha),
        )
        for o, n in zip(lists.wanted[i1 : i1 + paired], lists.found[j1 : j1 + paired], strict=True)
    ]
    missing = _list_missing(lists, ("delete", i1 + paired, i2, j2, j2))
    extra = _list_extra(lists, ("insert", i2, i2, j1 + paired, j2))
    return changed + missing + extra


OPCODE_LINES: dict[str, Callable[[CommitLists, Opcode], list[str]]] = {
    "delete": _list_missing,
    "insert": _list_extra,
    "replace": _list_replaced,
}


def describe_changed_commits(lists: CommitLists) -> list[str]:
    """One line per extra, missing or changed commit (R6)."""
    subjects = ([c.subject for c in lists.wanted], [c.subject for c in lists.found])
    matcher = difflib.SequenceMatcher(None, *subjects, autojunk=False)
    lines: list[str] = []
    for opcode in matcher.get_opcodes():
        if opcode[0] != "equal":
            lines += OPCODE_LINES[opcode[0]](lists, opcode)
    return lines


def _find_changed_commits(git: Git, rebase: StoryRebase) -> str | None:
    wanted = list_commits(git, f"{rebase.base}..{rebase.old}")
    found = list_commits(git, f"{rebase.onto}..HEAD")
    if [c.subject for c in wanted] == [c.subject for c in found]:
        return None
    head = COMMITS_CHANGED.format(branch=rebase.branch, old=rebase.old)
    return "\n".join([head, *describe_changed_commits(CommitLists(wanted, found, rebase))])


def is_foldable(git: Git, rebase: StoryRebase) -> bool:
    """R4: the rebase is finished, on its branch, on ``onto``, with a commit to fold into."""
    checks = (_find_unfinished, _find_off_branch, _find_off_base)
    if any(check(git, rebase) for check in checks):
        return False
    return git.head() != git.run("rev-parse", rebase.onto).strip()


def add_to_tip(git: Git, paths: list[str]) -> str:
    """R3: amend the tip with exactly ``paths``, keeping its message; return the new tip."""
    git.run("reset", "-q")
    git.run("add", "-A", "--", *paths)
    git.run("commit", "--amend", "--no-edit", "--no-verify")
    return git.head()
