"""A story branch rebased onto a newer sprint head by a role (s159 O1, S2, S3).

The runner starts the rebase and lets it stop at the conflict; the role resolves it in the
story's worktree; ``refusal`` judges the result before the story adopts the new branch.
"""

from __future__ import annotations

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
STORY_REBASE_LINES = (
    "Story {id}: its branch moves onto the sprint head. The runner started `git rebase --onto "
    "{onto} {base}` in this worktree, on the branch {branch}; it stopped on conflicts in: {files}.",
    "Resolve the conflicts in those files only: edit them, `git add` them and run `git rebase "
    "--continue` until it is done. Never merge, squash, reorder, reword, skip or drop a commit. "
    "Then hand off done.",
)


def needs_devops(  # house-rules: allow verb-name -- name fixed by the tests
    files: list[str],
    owners: Owners,
) -> bool:
    """O1: DevOps resolves it when every file is DevOps's or nobody's; else the developer."""
    writers = (owners.writer_of(f) for f in files)
    return all(w is None or w.role == DEVOPS for w in writers)


def prepare(git: Git, rebase: StoryRebase) -> None:
    """S2: branch from the old tip and start the rebase; it stops at the conflict."""
    if git.branch() == rebase.branch:
        return
    git.run("checkout", "-b", rebase.branch)
    git.attempt(*SCRATCH_REBASE_ARGV, "--onto", rebase.onto, rebase.base)


def refusal(  # house-rules: allow verb-name -- name fixed by the tests
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
