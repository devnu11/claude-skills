"""Carrying the runner's unpushed commits onto a landing merge (s180, ADR-0093)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import rewrite, system
from .gates import FINISHED, StoryState
from .git_ops import Git, GitError
from .priority import natural
from .story_rebase import ListedCommit, list_commits
from .upstream import Upstream, UpstreamError

GIVE_UP_MOVED = "sprint head moved"
CARRY_OFF_HEAD = "the sprint head {head} does not descend from the merge's base {base}"
CARRY_NO_BASE = "the merge {merge} has no first parent"
CARRY_MERGE = "{commit} is a merge"
CARRY_PUSHED = "the remote already has {pushed}, which is past the merge's base {base}"
CARRY_FORKED = "story {story} was forked from {commit}"
CARRY_CONFLICT = "carrying {commit} onto {merge} stopped on a conflict in {files}"
CHERRY_PICK_ARGV = ("cherry-pick", "--keep-redundant-commits")
SHORT = 12


@dataclass(frozen=True)
class CarrySpan:
    """A landing merge, its first parent, the sprint head and what the remote has."""

    merge: str
    base: str
    head: str
    pushed: str


@dataclass(frozen=True)
class Carry:
    """The commits to carry onto the merge and, once replayed, their new tip and pairs."""

    span: CarrySpan
    commits: tuple[ListedCommit, ...] = ()
    tip: str = ""
    moved: dict[str, str] = field(default_factory=dict)
    refusal: str = ""


@dataclass(frozen=True)
class Drop:
    """Why a landing gave up its merge, and what moved the sprint head (C6)."""

    why: str
    moved_by: tuple[str, ...] = ()
    refusal: str = ""


def format_commit(commit: ListedCommit) -> str:
    """A commit as ``<sha7> <subject>``."""
    return f"{commit.sha[:7]} {commit.subject}"


def _forks_from(story: StoryState, shas: set[str]) -> str | None:
    """The carried sha the story was forked from or will be rebased onto, if any."""
    onto = story.rebase.onto if story.rebase else ""
    return next((s for s in (story.base_sha, onto) if s in shas), None)


def find_forked_story(stories: Iterable[StoryState], commits: tuple[ListedCommit, ...]) -> str:
    """C2(d): the refusal text for the first open story forked from a carried commit, or ``""``."""
    by_sha = {c.sha: c for c in commits}
    for story in sorted(stories, key=lambda s: natural(s.id)):
        hit = None if story.status in FINISHED else _forks_from(story, set(by_sha))
        if hit is not None:
            return CARRY_FORKED.format(story=story.id, commit=format_commit(by_sha[hit]))
    return ""


def build_moved_drop(carry: Carry) -> Drop:
    """C6: the drop for a moved sprint head, naming every commit that moved it."""
    return Drop(GIVE_UP_MOVED, tuple(format_commit(c) for c in carry.commits), carry.refusal)


def describe_drop(drop: Drop, merge: str) -> dict[str, Any]:
    """The drop as the event data and the report entry."""
    return {
        "merge": merge,
        "why": drop.why,
        "moved_by": list(drop.moved_by),
        "refusal": drop.refusal,
    }


def remove_land_tree(git: Git, path: Path) -> None:
    """Remove the land worktree if there is one."""
    git.attempt("worktree", "remove", "--force", str(path))
    if system.exists(path):
        system.remove_tree(path)


class Carrier:
    """Checks, replays and adopts a carry (C2, C3, C4's move)."""

    def __init__(self, upstream: Upstream, tree: Path) -> None:
        self.upstream = upstream
        self.tree = tree

    def list_carried(self, span: CarrySpan) -> tuple[ListedCommit, ...]:
        """C1: the commits of ``base..head``, oldest first."""
        if span.base == span.head:
            return ()
        return tuple(list_commits(self.upstream.git, f"{span.base}..{span.head}"))

    def find_refusal(self, span: CarrySpan) -> str:
        """C2(a) to C2(c): the first reason the commits can't be carried, or ``""``."""
        for check in (self._check_head, self._check_merges, self._check_pushed):
            text = check(span)
            if text:
                return text
        return ""

    def _check_head(self, span: CarrySpan) -> str:
        if self.upstream.is_ancestor(span.base, span.head):
            return ""
        return CARRY_OFF_HEAD.format(head=span.head[:SHORT], base=span.base[:SHORT])

    def _check_merges(self, span: CarrySpan) -> str:
        git = self.upstream.git
        out = git.attempt("rev-list", "--reverse", "--merges", f"{span.base}..{span.head}")[1]
        merges = out.split()
        if not merges:
            return ""
        subject = git.attempt("log", "-1", "--format=%s", merges[0])[1].strip()
        return CARRY_MERGE.format(commit=format_commit(ListedCommit(merges[0], subject)))

    def _check_pushed(self, span: CarrySpan) -> str:
        if not span.pushed or self.upstream.is_ancestor(span.pushed, span.base):
            return ""
        return CARRY_PUSHED.format(pushed=span.pushed[:SHORT], base=span.base[:SHORT])

    def carry(self, span: CarrySpan, commits: tuple[ListedCommit, ...]) -> Carry:
        """C3: replay the commits onto the merge in the land worktree; always removes it."""
        remove_land_tree(self.upstream.git, self.tree)
        try:
            self.upstream.git.run("worktree", "add", "--detach", str(self.tree), span.merge)
            return self.run_replay(span, commits)
        finally:
            remove_land_tree(self.upstream.git, self.tree)

    def run_replay(self, span: CarrySpan, commits: tuple[ListedCommit, ...]) -> Carry:
        """Cherry-pick ``base..head`` in the land worktree; the new tip, or the conflict."""
        tree = Git(self.tree)
        code, _ = tree.attempt(*CHERRY_PICK_ARGV, f"{span.base}..{span.head}")
        if code != 0:
            return Carry(span, commits, refusal=self.stop_pick(span, tree))
        tip = tree.head()
        old = self.upstream.listing(f"{span.base}..{span.head}")
        new = rewrite.Listing(span.merge, self.upstream.listing(f"{span.merge}..{tip}"))
        return Carry(span, commits, tip=tip, moved=rewrite.pair(old, new))

    def stop_pick(self, span: CarrySpan, tree: Git) -> str:
        """Abort the stopped cherry-pick and say which commit conflicted, in which files."""
        names = tree.attempt("diff", "--name-only", "--diff-filter=U")[1]
        sha = tree.attempt("rev-parse", "CHERRY_PICK_HEAD")[1].strip()
        subject = tree.attempt("log", "-1", "--format=%s", sha)[1].strip()
        tree.attempt("cherry-pick", "--abort")
        return CARRY_CONFLICT.format(
            commit=format_commit(ListedCommit(sha, subject)),
            merge=span.merge[:SHORT],
            files=", ".join(names.split()),
        )

    def move_checkout(self, carry: Carry) -> bool:
        """C4: move the main checkout to the tip; False when it can't."""
        if not carry.commits:
            return self.upstream.advance_to(carry.tip)
        try:
            self.upstream.reset_team_branch(carry.span.head, carry.tip)
        except (UpstreamError, GitError):
            return False
        return True
