"""Carrying the runner's own commits over a green landing (s180, ADR-0090).

The runner commits story files and storyless steps on the sprint branch while a landing
waits on CI. Instead of dropping the landing, those commits are cherry-picked onto it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .git_ops import Git

NOT_ABOVE = "the sprint head does not descend from the merge's first parent"
MERGED = "a merge moved the sprint head: {line}"
PUSHED = "the remote sprint branch is at {pushed}, which the merge does not contain"
FORKED = "story {story}'s branch starts on the moved commit {sha}"
STOPPED = "carrying the moved commits stopped on a conflict in {files}"
UNEVEN = "carrying {old} moved commits made {new}"
LINE_FORMAT = "--format=%h %s"
SHORT = 12


@dataclass(frozen=True)
class Move:
    """How the sprint head moved since a landing's merge was made (C1)."""

    merge: str
    base: str
    head: str
    pushed: str = ""
    forks: tuple[tuple[str, str], ...] = ()

    @property
    def span(self) -> str:
        """The commits the head gained: ``base..head``."""
        return f"{self.base}..{self.head}"

    @property
    def is_unmoved(self) -> bool:
        """True when the head is still the merge's first parent."""
        return self.base == self.head


@dataclass(frozen=True)
class Carried:
    """Where the sprint branch ends after a green landing, and the copies made (C3)."""

    tip: str
    head: str
    moved: dict[str, str] = field(default_factory=dict)


def split_lines(code: int, out: str) -> list[str]:
    """The non-blank lines of a successful git output, else nothing."""
    return [line for line in out.splitlines() if line.strip()] if code == 0 else []


def list_moved(git: Git, move: Move) -> list[str]:
    """The ``%h %s`` lines of the moved commits, oldest first."""
    return split_lines(*git.attempt("log", "--reverse", LINE_FORMAT, move.span))


def list_shas(git: Git, span: str) -> list[str]:
    """The shas of a span, oldest first."""
    return split_lines(*git.attempt("rev-list", "--reverse", span))


def find_not_above(git: Git, move: Move) -> str | None:
    """Refuse a head that does not descend from the base, or an empty span."""
    code, _ = git.attempt("merge-base", "--is-ancestor", move.base, move.head)
    shas = split_lines(*git.attempt("rev-list", move.span))
    return NOT_ABOVE if code != 0 or not shas else None


def find_merge(git: Git, move: Move) -> str | None:
    """Refuse a span holding a merge."""
    lines = split_lines(*git.attempt("log", "--merges", LINE_FORMAT, move.span))
    return MERGED.format(line=lines[0]) if lines else None


def find_pushed(git: Git, move: Move) -> str | None:
    """Refuse when the remote already has a moved commit."""
    if not move.pushed:
        return None
    code, _ = git.attempt("merge-base", "--is-ancestor", move.pushed, move.merge)
    return PUSHED.format(pushed=move.pushed[:SHORT]) if code != 0 else None


def find_fork(git: Git, move: Move) -> str | None:
    """Refuse when a story's branch starts on a moved commit."""
    spanned = set(split_lines(*git.attempt("rev-list", move.span)))
    for story, sha in move.forks:
        if sha in spanned:
            return FORKED.format(story=story, sha=sha[:SHORT])
    return None


REFUSALS = (find_not_above, find_merge, find_pushed, find_fork)


def find_refusal(git: Git, move: Move) -> str | None:
    """The first reason the move can't be carried, or ``None``."""
    for check in REFUSALS:
        text = check(git, move)
        if text is not None:
            return text
    return None


def stop_carry(tree: Git) -> str:
    """Name the conflicting files, abort the cherry-pick, and say it stopped."""
    files = split_lines(*tree.attempt("diff", "--name-only", "--diff-filter=U"))
    tree.attempt("cherry-pick", "--abort")
    return STOPPED.format(files=", ".join(files))


def carry_commits(tree: Git, move: Move) -> Carried | str:
    """Cherry-pick the moved span onto the merge checked out in ``tree`` (C3)."""
    old = list_shas(tree, move.span)
    code, _ = tree.attempt("cherry-pick", "--allow-empty", "--keep-redundant-commits", move.span)
    if code != 0:
        return stop_carry(tree)
    new = list_shas(tree, f"{move.merge}..HEAD")
    if len(old) != len(new):
        return UNEVEN.format(old=len(old), new=len(new))
    return Carried(tree.head(), move.head, dict(zip(old, new, strict=True)))
