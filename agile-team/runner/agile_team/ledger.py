"""Per-role cost and token ledger, appended after every ``query()``.

Costs come from ``ResultMessage.total_cost_usd`` and tokens from its ``usage``.
The soft budget is the config's ``team.budget_usd``; hard caps belong to the
key's Console workspace.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

LEDGER = "ledger.jsonl"
USAGE_KEYS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_creation": "cache_creation_input_tokens",
}


@dataclass
class Tokens:
    """Token counts for one step, or a sum of steps."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0

    @classmethod
    def from_usage(cls, usage: dict[str, Any] | None) -> Tokens:
        """Counts from an Anthropic ``usage`` dict; missing keys count as 0."""
        usage = usage or {}
        return cls(**{name: int(usage.get(key) or 0) for name, key in USAGE_KEYS.items()})

    def __add__(self, other: Tokens) -> Tokens:
        return Tokens(*(getattr(self, f.name) + getattr(other, f.name) for f in fields(self)))

    def total(self) -> int:
        return sum(asdict(self).values())


@dataclass
class Entry:
    """One role invocation's cost and tokens."""

    role: str
    model: str
    cost_usd: float
    story: str | None = None
    at: float = 0.0
    tokens: Tokens = field(default_factory=Tokens)
    turns: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entry:
        """Parse a ledger line; lines written before token accounting have no tokens."""
        return cls(**{**data, "tokens": Tokens(**data.get("tokens", {}))})


@dataclass
class Totals:
    """Summed cost and tokens over some ledger entries."""

    cost_usd: float = 0.0
    tokens: Tokens = field(default_factory=Tokens)
    steps: int = 0
    turns: int = 0

    def add(self, entry: Entry) -> None:
        self.cost_usd += entry.cost_usd
        self.tokens += entry.tokens
        self.steps += 1
        self.turns += entry.turns


@dataclass
class Ledger:
    """JSONL ledger at ``path``."""

    path: Path

    def record(self, entry: Entry) -> None:
        if not entry.at:
            entry.at = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")

    def entries(self) -> list[Entry]:
        if not self.path.is_file():
            return []
        lines = self.path.read_text().splitlines()
        return [Entry.from_dict(json.loads(line)) for line in lines if line]

    def total(self) -> float:
        return sum(e.cost_usd for e in self.entries())

    def totals(self, key: str) -> dict[str, Totals]:
        """Totals grouped by an entry field (``role``, ``story`` or ``model``)."""
        groups: dict[str, Totals] = defaultdict(Totals)
        for e in self.entries():
            groups[str(getattr(e, key))].add(e)
        return dict(groups)

    def by_role(self) -> dict[str, float]:
        return {role: t.cost_usd for role, t in self.totals("role").items()}


def budget_status(ledger: Ledger, budget_usd: float) -> dict[str, object]:
    """Spend summary handed to the Product Owner and Manager."""
    spent = ledger.total()
    tokens = sum((e.tokens for e in ledger.entries()), Tokens())
    return {
        "spent_usd": round(spent, 4),
        "budget_usd": budget_usd,
        "remaining_usd": round(budget_usd - spent, 4),
        "pct_used": round(100 * spent / budget_usd, 1) if budget_usd else 0.0,
        "by_role": {k: round(v, 4) for k, v in sorted(ledger.by_role().items())},
        "tokens": asdict(tokens),
    }


@dataclass(frozen=True)
class Budget:
    """The soft budget and how often (in percent of it) the Manager checks in."""

    usd: float
    every_pct: int

    def checkpoint_crossed(self, before: float, after: float) -> bool:
        """True when spend moved past a multiple of ``every_pct`` percent of the budget."""
        if self.usd <= 0:
            return False
        step = self.usd * self.every_pct / 100
        return int(after // step) > int(before // step)
