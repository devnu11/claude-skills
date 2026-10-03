"""Per-role cost ledger, appended after every ``query()``.

Costs come from ``ResultMessage.total_cost_usd``. The soft budget is the
config's ``team.budget_usd``; hard caps belong to the key's Console workspace.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Entry:
    """One role invocation's cost."""

    role: str
    model: str
    cost_usd: float
    story: str | None = None
    at: float = 0.0


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
        return [Entry(**json.loads(line)) for line in self.path.read_text().splitlines() if line]

    def total(self) -> float:
        return sum(e.cost_usd for e in self.entries())

    def by_role(self) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for e in self.entries():
            totals[e.role] += e.cost_usd
        return dict(totals)


def budget_status(ledger: Ledger, budget_usd: float) -> dict[str, object]:
    """Spend summary handed to the Product Owner and Manager."""
    spent = ledger.total()
    return {
        "spent_usd": round(spent, 4),
        "budget_usd": budget_usd,
        "remaining_usd": round(budget_usd - spent, 4),
        "pct_used": round(100 * spent / budget_usd, 1) if budget_usd else 0.0,
        "by_role": {k: round(v, 4) for k, v in sorted(ledger.by_role().items())},
    }


def checkpoint_crossed(before: float, after: float, budget: float, every_pct: int) -> bool:
    """True when spend moved past a multiple of ``every_pct`` percent of ``budget``."""
    if budget <= 0:
        return False
    step = budget * every_pct / 100
    return int(after // step) > int(before // step)
