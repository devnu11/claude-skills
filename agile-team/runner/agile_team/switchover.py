"""The one-time switch to story branches (s159 W1)."""

from __future__ import annotations

from dataclasses import dataclass

PAST_DESIGN = "stories past design: {ids}"
PENDING = "pending tests still registered: {ids}"
STACK = "the upstream stack is not empty ({n} entries)"
AHEAD = "the team branch is {n} commits ahead of the target"


@dataclass(frozen=True)
class SwitchFacts:
    """What the switch checks."""

    past_design: list[str]
    pending_ids: list[str]
    stack: int
    ahead: int


def refusals(facts: SwitchFacts) -> list[str]:
    """Every reason the switch can't happen yet."""
    found = []
    if facts.past_design:
        found.append(PAST_DESIGN.format(ids=", ".join(facts.past_design)))
    if facts.pending_ids:
        found.append(PENDING.format(ids=", ".join(facts.pending_ids)))
    if facts.stack:
        found.append(STACK.format(n=facts.stack))
    if facts.ahead:
        found.append(AHEAD.format(n=facts.ahead))
    return found
