"""What the Manager sees at a checkpoint: spend per role and the team's friction notes.

The Manager is a servant leader, not a supervisor of each step. These views let
it spot roles that cost more than their job warrants and hear what slows the
team down, without reading transcripts.
"""

from __future__ import annotations

from typing import Any

from .events import Event, EventKind
from .ledger import Ledger, Totals

MANAGER = "manager"


def spend_by_role(ledger: Ledger) -> dict[str, dict[str, Any]]:
    """Cost, tokens and turns per role, most expensive first."""
    totals = sorted(ledger.totals("role").items(), key=lambda kv: -kv[1].cost_usd)
    return {role: _role_view(t) for role, t in totals}


def _role_view(t: Totals) -> dict[str, Any]:
    steps = max(1, t.steps)
    return {
        "steps": t.steps,
        "cost_usd": round(t.cost_usd, 2),
        "cost_per_step": round(t.cost_usd / steps, 3),
        "tokens": t.tokens.total(),
        "turns_per_step": round(t.turns / steps, 1),
    }


def friction_since_review(events: list[Event]) -> list[dict[str, Any]]:
    """Friction notes from step handoffs since the Manager's last step."""
    recent = events[_after_last_manager(events) :]
    return [_friction(e) for e in recent if e.kind is EventKind.STEP_END and e.data.get("friction")]


def _after_last_manager(events: list[Event]) -> int:
    ends = [i for i, e in enumerate(events) if e.kind is EventKind.STEP_END and e.role == MANAGER]
    return ends[-1] + 1 if ends else 0


def _friction(event: Event) -> dict[str, Any]:
    return {"role": event.role, "story": event.story, "friction": event.data["friction"]}
