"""The one-time switch to story branches (s159 W1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import system
from .git_ops import GitError

if TYPE_CHECKING:
    from .dispatch import Runtime

PENDING_FILE = ".team/pending-tests.json"
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


def refusals(  # house-rules: allow verb-name -- name fixed by the s159 tests
    facts: SwitchFacts,
) -> list[str]:
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


def read_pending(repo: Path) -> list[str]:
    """The story ids with pending tests in ``.team/pending-tests.json`` (the registry is gone)."""
    path = repo / PENDING_FILE
    if not system.is_file(path):
        return []
    try:
        data = json.loads(system.read_text(path))
    except ValueError:
        return []
    return sorted(k for k, v in data.items() if v) if isinstance(data, dict) else []


def count_ahead(runtime: Runtime) -> int:
    """How many commits the team branch has that the target lacks (0 with no target)."""
    try:
        return runtime.upstream.count("HEAD")  # type: ignore[union-attr]
    except GitError:
        return 0


def read_facts(runtime: Runtime, ids: list[str]) -> SwitchFacts:
    """Read what the switch checks from the run."""
    stories = runtime.state.stories
    past = [i for i in ids if runtime.pipeline.is_past_design(stories[i])]
    stack = len(runtime.state.upstream.stack)
    return SwitchFacts(past, read_pending(runtime.config.repo), stack, count_ahead(runtime))
