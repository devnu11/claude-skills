"""s10: a start ledgers the spend a crash cut off, estimated from turns.jsonl."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from agile_team import cli, live, reconcile, system
from agile_team import state as state_mod
from agile_team.ledger import Entry, Ledger, SessionCost, Tokens
from agile_team.po_tools import PoRun, Start
from claude_agent_sdk import AssistantMessage, TextBlock

from .conftest import FakeQuery
from .fake_system import FAKE_IDS, START_CLOCK, FakeSystem
from .test_cli import any_tool, start_args
from .test_po_cost import Totals, po_costs, po_run, turn

PO = "product-owner"
OPUS = "claude-opus-4-1"
EARLY = START_CLOCK - 1000.0


class Crashing:
    """A fake PO query: two model messages, then a crash before any ResultMessage."""

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for n in (1, 2):
            usage = {"input_tokens": 1000 * n, "output_tokens": 500 * n}
            yield AssistantMessage(
                content=[TextBlock(text="t")], model=OPUS, usage=usage, message_id=f"m{n}"
            )
        raise RuntimeError("crash")


def a_turn(
    n: int,
    role: str = PO,
    story: str | None = None,
    cost: float | None = 1.0,
    mid: str | None = None,
    model: str = OPUS,
) -> live.Turn:
    """A turn line at ``EARLY + n`` with 10 input and 5 output tokens."""
    return live.Turn(
        at=EARLY + n, role=role, story=story, step=None, turn=n, model=model,
        tokens=Tokens(input=10, output=5), tools=[], cost_usd=cost,
        message_id=mid or f"id{n}",
    )  # fmt: skip


def write_turns(run_dir: Path, turns: list[live.Turn]) -> None:
    system.make_dirs(run_dir)
    system.write_text(run_dir / live.TURNS, "".join(t.line() + "\n" for t in turns))


def row(role: str, at: float, story: str | None = None, cost: float = 1.0) -> Entry:
    return Entry(role, OPUS, cost, story=story, at=at)


def ledger_of(run_dir: Path) -> Ledger:
    return Ledger(run_dir / "ledger.jsonl")


def crashed_po(make_runtime) -> PoRun:
    """A PO run whose query crashed mid-turn: two turn lines, no ledger row."""
    run = po_run(make_runtime, Crashing())
    with pytest.raises(RuntimeError):
        turn(run, None)
    return run


def turn_lines(run: PoRun) -> list[dict]:
    text = system.read_text(run.runtime.config.run_dir / live.TURNS)
    return [json.loads(x) for x in text.splitlines()]


# ----- AC1: the story's test ---------------------------------------------------------


def test_a_crash_mid_po_turn_is_ledgered_from_turns_jsonl(make_runtime) -> None:
    run = crashed_po(make_runtime)
    run_dir = run.runtime.config.run_dir
    lines = [x for x in turn_lines(run) if x["role"] == PO]
    assert len(lines) == 2
    assert po_costs(run) == []
    written = reconcile.reconcile_ledger(run_dir)
    rows = [e for e in ledger_of(run_dir).entries() if e.role == PO]
    assert rows == written
    assert len(rows) == 1
    assert rows[0].story is None
    assert rows[0].cost_usd == pytest.approx(sum(x["cost_usd"] for x in lines))
    assert rows[0].cost_usd > 0
    assert rows[0].tokens == Tokens(input=3000, output=1500)
    assert rows[0].turns == 2


def test_a_second_reconcile_writes_nothing(make_runtime) -> None:
    run = crashed_po(make_runtime)
    run_dir = run.runtime.config.run_dir
    reconcile.reconcile_ledger(run_dir)
    total = sum(e.cost_usd for e in ledger_of(run_dir).entries())
    assert reconcile.reconcile_ledger(run_dir) == []
    assert sum(e.cost_usd for e in ledger_of(run_dir).entries()) == pytest.approx(total)


def test_covered_turns_get_no_row(scratch: Path) -> None:
    write_turns(scratch, [a_turn(1, "developer-cli", "s7"), a_turn(2, "developer-cli", "s7")])
    ledger_of(scratch).record(row("developer-cli", EARLY + 3, "s7"))
    assert reconcile.reconcile_ledger(scratch) == []
    assert len(ledger_of(scratch).entries()) == 1


def test_covered_role_alongside_crashed_po(scratch: Path) -> None:
    write_turns(scratch, [a_turn(1, "developer-cli", "s7"), a_turn(2), a_turn(3)])
    ledger_of(scratch).record(row("developer-cli", EARLY + 4, "s7"))
    written = reconcile.reconcile_ledger(scratch)
    assert [(e.role, e.story) for e in written] == [(PO, None)]
    assert written[0].turns == 2


# ----- next start --------------------------------------------------------------------


def test_the_next_start_ledgers_the_cut_off_po_and_says_so(
    configured: Path, key_home: Path, capsys, fake: FakeSystem
) -> None:
    any_tool(fake)
    run_dir = configured / ".team/run"
    write_turns(run_dir, [a_turn(1, cost=0.25), a_turn(2, cost=0.5)])
    args = start_args(configured, key_home, "--task", "t")
    assert not isinstance(
        cli._prepared(args, cli.Place(configured, key_home), Start("t"), FakeQuery()), int
    )
    rows = ledger_of(run_dir).entries()
    assert [(e.role, e.cost_usd) for e in rows] == [(PO, pytest.approx(0.75))]
    assert (
        "agile-team start: ledgered $0.75 for product-owner, "
        "cut off by the last run (estimated from turns.jsonl)"
    ) in capsys.readouterr().err


# ----- RC3 / RC4 / RC2 ----------------------------------------------------------------


def test_only_turns_after_the_latest_row_count(scratch: Path) -> None:
    write_turns(scratch, [a_turn(1, cost=5), a_turn(2, cost=5), a_turn(4, cost=2), a_turn(5)])
    ledger_of(scratch).record(row(PO, EARLY + 3))
    (written,) = reconcile.reconcile_ledger(scratch)
    assert written.cost_usd == pytest.approx(3.0)
    assert written.turns == 2


def test_sum_turns_null_cost_counts_zero_and_last_model_wins() -> None:
    entry = reconcile.sum_turns([a_turn(1, cost=None, model="old"), a_turn(2, cost=0.5)])
    assert (entry.cost_usd, entry.model, entry.at) == (0.5, OPUS, 0)
    assert entry.tokens == Tokens(input=20, output=10)


def test_sum_turns_counts_distinct_message_ids() -> None:
    same = [a_turn(1, mid="x"), a_turn(2, mid="x"), a_turn(3, mid="y")]
    assert reconcile.sum_turns(same).turns == 2


def test_sum_turns_null_ids_count_one_each() -> None:
    nulls = [a_turn(1), a_turn(2), a_turn(3)]
    for t in nulls:
        object.__setattr__(t, "message_id", None)
    assert reconcile.sum_turns(nulls).turns == 3


def test_a_role_step_gets_its_own_row_after_the_po_row(scratch: Path) -> None:
    write_turns(
        scratch, [a_turn(1, "developer-cli", "s7"), a_turn(2), a_turn(3, "developer-cli", "s7")]
    )
    written = reconcile.reconcile_ledger(scratch)
    assert [(e.role, e.story, e.turns) for e in written] == [
        ("developer-cli", "s7", 2),
        (PO, None, 1),
    ]


def test_find_uncovered_keys_in_first_turn_order() -> None:
    turns = [a_turn(1, "b", "s1"), a_turn(2, "a"), a_turn(3, "b", "s1")]
    found = reconcile.find_uncovered(turns, [])
    assert list(found) == [("b", "s1"), ("a", None)]
    assert len(found[("b", "s1")]) == 2


# ----- RC6 ----------------------------------------------------------------------------


def test_bad_lines_are_skipped(scratch: Path) -> None:
    good = a_turn(1).line()
    system.write_text(scratch / live.TURNS, f'{good}\n\n[1]\n{{"x": 1}}\n{good}\n{good[:20]}')
    assert reconcile.read_turns(scratch / live.TURNS) == [a_turn(1), a_turn(1)]


def test_a_missing_turns_file_reconciles_nothing(scratch: Path) -> None:
    assert reconcile.read_turns(scratch / live.TURNS) == []
    assert reconcile.reconcile_ledger(scratch) == []
    assert not system.exists(scratch / "ledger.jsonl")


def test_turn_from_line_round_trips() -> None:
    assert live.Turn.from_line(a_turn(3).line()) == a_turn(3)


@pytest.mark.parametrize("text", ["{torn", "[1]", '{"at": 1}', ""])
def test_turn_from_line_rejects_bad_lines(text: str) -> None:
    with pytest.raises((ValueError, TypeError, KeyError)):
        live.Turn.from_line(text)


# ----- RC1 ----------------------------------------------------------------------------


def test_nothing_is_written_while_a_runner_is_alive(scratch: Path) -> None:
    write_turns(scratch, [a_turn(1)])
    system.write_text(scratch / state_mod.PID_FILE, str(FAKE_IDS[0]))
    assert reconcile.reconcile_ledger(scratch) == []
    assert not system.exists(scratch / "ledger.jsonl")


# ----- RC7 ----------------------------------------------------------------------------


def test_the_resumed_session_does_not_charge_the_reconciled_cost_twice(make_runtime) -> None:
    run = po_run(make_runtime, Totals([1.0 + 0.75 + 0.25], ["sess"]))
    run_dir = run.runtime.config.run_dir
    state_mod.save(run_dir, state_mod.RunState(po_cost=SessionCost("sess", 1.0)))
    write_turns(run_dir, [a_turn(1, cost=0.25), a_turn(2, cost=0.5)])
    reconcile.reconcile_ledger(run_dir)
    assert state_mod.load(run_dir).po_cost == SessionCost("sess", 1.0, 0.75)
    run.runtime.state = state_mod.load(run_dir)
    turn(run)
    assert po_costs(run)[-1] == pytest.approx(0.25)
    assert state_mod.load(run_dir).po_cost == SessionCost("sess", 2.0)


def test_without_a_baseline_state_is_left_alone(scratch: Path) -> None:
    state_mod.save(scratch, state_mod.RunState())
    write_turns(scratch, [a_turn(1)])
    reconcile.reconcile_ledger(scratch)
    assert state_mod.load(scratch).po_cost is None


def test_a_role_row_does_not_touch_the_po_baseline(scratch: Path) -> None:
    state_mod.save(scratch, state_mod.RunState(po_cost=SessionCost("sess", 1.0)))
    write_turns(scratch, [a_turn(1, "developer-cli", "s7")])
    reconcile.reconcile_ledger(scratch)
    assert state_mod.load(scratch).po_cost == SessionCost("sess", 1.0)


def test_told_line_formats_cost_and_label() -> None:
    line = reconcile.told_line(Entry("developer-cli", OPUS, 1.234, story="s7"))
    assert line == (
        "agile-team start: ledgered $1.23 for developer-cli on s7, "
        "cut off by the last run (estimated from turns.jsonl)"
    )
