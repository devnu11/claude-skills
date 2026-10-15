"""Per-role cost and token ledger, appended after every ``query()``.

Costs come from ``ResultMessage.total_cost_usd`` and tokens from its ``usage``.
The budget is the config's ``team.budget_usd``: a ceiling at which the
runner halts (s38). Readers get corrected entries: PO entries written before
s25 held the session's running total and are turned into each query's own
cost when read (``corrected``, ADR-007). A resumed PO query records only its own share of the
session's running total (``SessionCost``, ADR-004).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from . import system

LEDGER = "ledger.jsonl"
USAGE_KEYS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_creation": "cache_creation_input_tokens",
}
PO_ROLE = "product-owner"
PO_DELTAS_FROM = 1791694950.0  # 2026-10-11 05:02:30 UTC; ADR-007
LEGACY_SESSION = "pre-s25"


@dataclass
class SessionCost:
    """The running ``total_cost_usd`` Claude Code last reported for one session."""

    session: str | None = None
    reported: float = 0.0
    reconciled: float = 0.0  # estimate a start already ledgered from turns.jsonl (s10, RC7)

    def own_cost(self, resumed: str | None, reported: float) -> float:
        """The part of ``reported`` that one query spent.

        ``resumed`` is the session the query resumed (``None`` for a fresh one).
        A fall below the stored figure means the counter restarted. A same-session
        delta is reduced by what a start already ledgered for it (s10, RC7).
        """
        if resumed is None or resumed != self.session or reported < self.reported:
            return reported
        delta = reported - self.reported
        return delta - min(self.reconciled, delta)


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

    def prompt(self) -> int:
        """The context one step re-sent: input plus cache reads and creation."""
        return self.input + self.cache_read + self.cache_creation


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


def corrected(entries: list[Entry]) -> list[Entry]:
    """``entries`` with each pre-s25 PO running total turned into that query's own cost (K2, K3)."""
    seen = SessionCost(LEGACY_SESSION)
    return [_own_share(e, seen) for e in entries]


def _own_share(entry: Entry, seen: SessionCost) -> Entry:
    if entry.role != PO_ROLE or entry.at >= PO_DELTAS_FROM:
        return entry
    own = seen.own_cost(LEGACY_SESSION, entry.cost_usd)
    seen.reported = entry.cost_usd
    return replace(entry, cost_usd=own)


@dataclass
class Totals:
    """Summed cost and tokens over some ledger entries."""

    cost_usd: float = 0.0
    tokens: Tokens = field(default_factory=Tokens)
    steps: int = 0
    turns: int = 0
    measured: int = 0
    measured_prompt: int = 0
    latest_turns: int = 0

    def add(self, entry: Entry) -> None:
        self.cost_usd += entry.cost_usd
        self.tokens += entry.tokens
        self.steps += 1
        self.turns += entry.turns
        if entry.turns > 0:
            self._measure(entry)

    def _measure(self, entry: Entry) -> None:
        self.measured += 1
        self.measured_prompt += entry.tokens.prompt()
        self.latest_turns = entry.turns

    def turns_per_step(self) -> float:
        """Average turns over steps whose turns were recorded."""
        return self.turns / self.measured if self.measured else 0.0

    def context_per_turn(self) -> int:
        """Average prompt tokens re-sent per turn, over measured steps."""
        return round(self.measured_prompt / self.turns) if self.turns else 0


@dataclass
class Ledger:
    """JSONL ledger at ``path``."""

    path: Path

    def record(self, entry: Entry) -> None:
        if not entry.at:
            entry.at = system.now()
        system.make_dirs(self.path.parent)
        system.append_text(self.path, json.dumps(asdict(entry)) + "\n")

    def entries(self) -> list[Entry]:
        """Entries with the PO overcount corrected (K4)."""
        return corrected(self._raw())

    def overcount(self) -> float:
        """What the correction takes off the raw ledger (K6)."""
        raw = self._raw()
        return sum(e.cost_usd for e in raw) - sum(e.cost_usd for e in corrected(raw))

    def _raw(self) -> list[Entry]:
        if not system.is_file(self.path):
            return []
        lines = system.read_text(self.path).splitlines()
        return [Entry.from_dict(json.loads(line)) for line in lines if line]

    def total(self) -> float:
        return sum(e.cost_usd for e in self.entries())

    def totals(self, key: str) -> dict[str, Totals]:
        """Totals grouped by an entry field (``role``, ``story`` or ``model``)."""
        groups: dict[str, Totals] = defaultdict(Totals)
        for e in self.entries():
            groups[str(getattr(e, key))].add(e)
        return dict(groups)

    def last_cost(self, role: str) -> float:
        """The most recent cost ledgered for ``role`` as written; 0.0 if it has none."""
        costs = [e.cost_usd for e in self._raw() if e.role == role]
        return costs[-1] if costs else 0.0

    def by_role(self) -> dict[str, float]:
        return {role: t.cost_usd for role, t in self.totals("role").items()}


def budget_status(ledger: Ledger, budget_usd: float) -> dict[str, object]:
    """Corrected spend against the budget ceiling, for the PO, the Manager and ``status``."""
    spent = ledger.total()
    tokens = sum((e.tokens for e in ledger.entries()), Tokens())
    return {
        "spent_usd": round(spent, 4),
        "budget_usd": budget_usd,
        "remaining_usd": round(budget_usd - spent, 4),
        "pct_used": round(100 * spent / budget_usd, 1) if budget_usd else 0.0,
        "po_overcount_usd": round(ledger.overcount(), 4),
        "by_role": {k: round(v, 4) for k, v in sorted(ledger.by_role().items())},
        "tokens": asdict(tokens),
    }


@dataclass(frozen=True)
class Budget:
    """The budget and how often (in percent of it) the Manager checks in."""

    usd: float
    every_pct: int

    def checkpoint_crossed(self, before: float, after: float) -> bool:
        """True when spend moved past a multiple of ``every_pct`` percent of the budget."""
        if self.usd <= 0:
            return False
        step = self.usd * self.every_pct / 100
        return int(after // step) > int(before // step)
