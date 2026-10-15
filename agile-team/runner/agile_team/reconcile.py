"""Ledgers, at start, the spend a crash cut off, estimated from turns.jsonl (s10, ADR-0078)."""

from __future__ import annotations

from pathlib import Path

from . import salvage, system
from . import state as state_mod
from .ledger import LEDGER, PO_ROLE, Entry, Ledger, Tokens
from .live import TURNS, Turn

Key = tuple[str, str | None]  # (role, story), RC2
TOLD = (
    "agile-team start: ledgered ${cost:.2f} for {label}, "
    "cut off by the last run (estimated from turns.jsonl)"
)
BAD_LINE = (ValueError, TypeError, KeyError)


def reconcile_ledger(run_dir: Path) -> list[Entry]:
    """Ledger each key's uncovered turns (RC1-RC7); [] while a runner is alive."""
    if state_mod.runner_alive(run_dir):
        return []
    ledger = Ledger(run_dir / LEDGER)
    found = find_uncovered(read_turns(run_dir / TURNS), ledger.entries())
    entries = [sum_turns(turns) for turns in found.values()]
    for entry in entries:
        ledger.record(entry)
    _net_po_spend(run_dir, entries)
    return entries


def _net_po_spend(run_dir: Path, entries: list[Entry]) -> None:
    """RC7: note the reconciled PO cost in the session baseline."""
    spent = sum(e.cost_usd for e in entries if e.role == PO_ROLE)
    if spent <= 0:
        return
    state = state_mod.load(run_dir)
    if state.po_cost is not None:
        state.po_cost.reconciled += spent
        state_mod.save(run_dir, state)


def read_turns(path: Path) -> list[Turn]:
    """The parseable turn lines of ``path`` in file order; [] when it is missing (RC6)."""
    if not system.is_file(path):
        return []
    parsed = (_parsed(line) for line in system.read_text(path).splitlines())
    return [turn for turn in parsed if turn is not None]


def _parsed(line: str) -> Turn | None:
    try:
        return Turn.from_line(line)
    except BAD_LINE:
        return None


def _latest(entries: list[Entry]) -> dict[Key, float]:
    latest: dict[Key, float] = {}
    for e in entries:
        key = (e.role, e.story)
        latest[key] = max(latest.get(key, e.at), e.at)
    return latest


def find_uncovered(turns: list[Turn], entries: list[Entry]) -> dict[Key, list[Turn]]:
    """Per key, its turns after its latest ledger row (RC3), in first-turn order."""
    latest = _latest(entries)
    found: dict[Key, list[Turn]] = {}
    for turn in turns:
        key = (turn.role, turn.story)
        if key not in latest or turn.at > latest[key]:
            found.setdefault(key, []).append(turn)
    return found


def _turn_count(turns: list[Turn]) -> int:
    ids = {t.message_id for t in turns if t.message_id is not None}
    return len(ids) + sum(1 for t in turns if t.message_id is None)


def sum_turns(turns: list[Turn]) -> Entry:
    """One ledger entry for one key's uncovered turns (RC4); ``at`` left 0."""
    last = turns[-1]
    return Entry(
        last.role,
        last.model,
        sum(t.cost_usd or 0.0 for t in turns),
        last.story,
        tokens=sum((t.tokens for t in turns), Tokens()),
        turns=_turn_count(turns),
    )


def told_line(entry: Entry) -> str:
    """The stderr line for a reconciled entry (RC8)."""
    label = salvage.label(entry.role, entry.story)
    return TOLD.format(cost=entry.cost_usd, label=label)
