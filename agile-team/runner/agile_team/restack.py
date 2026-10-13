"""Finds merged stack PRs and plans the fast rebase of the stack.

Nothing here pushes or moves a branch. ``Restacker.plan`` rebases in the review
worktree and says whether every PR kept its tree; the boundary runner applies it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import takewhile

from .boundary import StackEntry
from .stack import Move, Rebuilder
from .upstream import Prs, PrState

REBASE_STOPPED = "{branch} did not rebase cleanly onto {onto}"
TREE_CHANGED = "{branch} rebased onto {onto} has a different tree"
SHORT = 12


@dataclass(frozen=True)
class Plan:
    """New heads for the remaining entries, bottom first, or why the fast path was refused."""

    heads: list[str] = field(default_factory=list)
    refused: str = ""
    emptied: list[str] = field(default_factory=list)


@dataclass
class Restacker:
    """Finds merged entries and plans the rebase of the rest."""

    prs: Prs
    rebuilder: Rebuilder

    def merged(self, stack: list[StackEntry]) -> list[StackEntry]:
        """The leading entries whose PR is merged; lookups stop at the first that is not."""
        return list(takewhile(self._is_merged, stack))

    def plan(self, rest: list[StackEntry], below: str) -> Plan:
        """Rebase ``rest`` bottom first from ``below``; refuse on a stop or a changed tree."""
        self.rebuilder.prepare()
        plan = Plan()
        move = Move(self.rebuilder.target, below)
        for entry in rest:
            new, refused = self._next(entry, move)
            if refused:
                return Plan(refused=refused)
            self._note(plan, entry, move, new)
            move = Move(new, entry.head)
        return plan

    def _note(self, plan: Plan, entry: StackEntry, move: Move, new: str) -> None:
        plan.heads.append(new)
        if self.rebuilder.count(move.onto, new) == 0:
            plan.emptied.append(entry.branch)

    def _is_merged(self, entry: StackEntry) -> bool:
        if not entry.pr:
            return False
        pr = self.prs.find(entry.branch)
        return pr is not None and pr.number == entry.pr and pr.state is PrState.MERGED

    def _next(self, entry: StackEntry, move: Move) -> tuple[str, str]:
        """The entry's new head and the refusal (empty when it passed)."""
        onto = move.onto if move.onto == self.rebuilder.target else move.onto[:SHORT]
        new = self.rebuilder.rebase(entry.head, move)
        if new is None:
            return "", REBASE_STOPPED.format(branch=entry.branch, onto=onto)
        if not self.rebuilder.same_tree(new, entry.head):
            return "", TREE_CHANGED.format(branch=entry.branch, onto=onto)
        return new, ""
