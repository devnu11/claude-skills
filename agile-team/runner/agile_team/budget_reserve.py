"""Budget headroom: what each running step may still cost (s159 C4, AC12.1)."""

from __future__ import annotations

import statistics
from typing import NamedTuple

from .ledger import Entry

RESERVE_MIN_STEPS = 5
REFUSAL = "budget headroom: spent {spend:.2f} plus reserves {reserves:.2f} reaches {ceiling:.2f}"


class Who(NamedTuple):
    """The step a reserve is for: its role, model and the floor."""

    role: str
    model: str
    floor: float


class Headroom(NamedTuple):
    """Spend so far and the ceiling."""

    spend: float
    ceiling: float


def _list_fresh(entries: list[Entry], who: Who) -> list[float]:
    role, model, _floor = who
    return [
        e.cost_usd
        for e in entries
        if (e.role, e.model) == (role, model) and not e.resumed and not e.estimated
    ]


def reserve(
    entries: list[Entry],
    who: Who,
) -> float:
    """``max(mean + 3 sigma, floor)`` over fresh entries; the floor under five of them."""
    costs = _list_fresh(entries, who)
    floor = who[2]
    if len(costs) < RESERVE_MIN_STEPS:
        return floor
    return max(statistics.mean(costs) + 3 * statistics.pstdev(costs), floor)


def start_refusal(headroom: Headroom, reserves: list[float]) -> str | None:
    """Why nothing new may start, or None while spend plus reserves stays under the ceiling."""
    spend, ceiling = headroom
    total = sum(reserves)
    if spend + total < ceiling:
        return None
    return REFUSAL.format(spend=spend, reserves=total, ceiling=ceiling)
