"""What the Manager sees at a checkpoint: spend per role and the team's friction notes.

The Manager is a servant leader, not a supervisor of each step. These views let
it spot roles that cost more than their job warrants and hear what slows the
team down, without reading transcripts.
"""

from __future__ import annotations

from typing import Any

from .events import INTERRUPTED, Event, EventKind
from .ledger import Entry, Ledger, Totals

MANAGER = "manager"
LONG_TURNS = 30
RECENT = 3
LONG_OF_RECENT = 2


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
        "turns_per_step": round(t.turns_per_step(), 1),
        "latest_turns": t.latest_turns,
        "context_per_turn": t.context_per_turn(),
    }


def long_running_roles(ledger: Ledger) -> list[dict[str, Any]]:
    """Roles whose recent measured steps often ran past ``LONG_TURNS`` turns."""
    entries = [e for e in ledger.entries() if e.turns > 0]
    totals = ledger.totals("role")
    views = (_long_view(role, entries, totals) for role in sorted(totals))
    return [
        v for v in views if v and sum(t > LONG_TURNS for t in v["recent_turns"]) >= LONG_OF_RECENT
    ]


def _long_view(role: str, entries: list[Entry], totals: dict[str, Totals]) -> dict[str, Any]:
    recent = [e.turns for e in entries if e.role == role][-RECENT:]
    return {
        "role": role,
        "recent_turns": recent,
        "context_per_turn": totals[role].context_per_turn(),
    }


def friction_since_review(events: list[Event]) -> list[dict[str, Any]]:
    """Friction notes from step handoffs since the Manager's last step."""
    recent = events[_after_last_manager(events) :]
    return [_friction(e) for e in recent if e.kind is EventKind.STEP_END and e.data.get("friction")]


def disputes_since_review(events: list[Event]) -> list[dict[str, Any]]:
    """Test disputes raised since the Manager's last step."""
    recent = events[_after_last_manager(events) :]
    return [_dispute(e) for e in recent if e.kind is EventKind.TEST_DISPUTE]


def _dispute(event: Event) -> dict[str, Any]:
    keys = ("test", "rule", "rounds")
    return {"story": event.story, "role": event.role, **{k: event.data[k] for k in keys}}


def _manager_review(event: Event) -> bool:
    """A Manager ``step-end`` that reviewed; an interrupted one did not."""
    done = event.kind is EventKind.STEP_END and event.role == MANAGER
    return done and event.data.get("status") != INTERRUPTED


def _after_last_manager(events: list[Event]) -> int:
    ends = [i for i, e in enumerate(events) if _manager_review(e)]
    return ends[-1] + 1 if ends else 0


def _friction(event: Event) -> dict[str, Any]:
    return {"role": event.role, "story": event.story, "friction": event.data["friction"]}
