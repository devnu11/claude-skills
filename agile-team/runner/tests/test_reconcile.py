"""s10: a start ledgers the spend a crash cut off, estimated from turns.jsonl (ADR-0078)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from agile_team import cli, reconcile, system
from agile_team import state as state_mod
from agile_team.ledger import LEDGER, Entry, Ledger, SessionCost, Tokens
from agile_team.live import TURNS, Turn
from agile_team.po_tools import PoRun, PoTurn, Start
from claude_agent_sdk import AssistantMessage, TextBlock

from .conftest import FakeQuery, result_message
from .test_cli import any_tool, start_args

OPUS = "claude-opus-4-1"
USAGE = {"input_tokens": 1000, "output_tokens": 200}


def tline(at: float, **kw: Any) -> Turn:
    """A turn line; PO by default, 1 dollar, one distinct message id per ``at``."""
    fields: dict[str, Any] = {
        "role": "product-owner",
        "story": None,
        "step": None,
        "turn": 1,
        "model": OPUS,
        "tokens": Tokens(10, 5),
        "tools": [],
        "cost_usd": 1.0,
        "message_id": f"m{at}",
    }
    return Turn(at=at, **{**fields, **kw})


def put_turns(run_dir: Path, *lines: Turn | str) -> None:
    text = "".join((t.line() if isinstance(t, Turn) else t) + "\n" for t in lines)
    system.make_dirs(run_dir)
    system.write_text(run_dir / TURNS, text)


def ledger_of(run_dir: Path) -> Ledger:
    return Ledger(run_dir / LEDGER)


def row(role: str, at: float, story: str | None = None, cost: float = 9.0) -> Entry:
    return Entry(role, OPUS, cost, story, at=at)


class Crashing:
    """A fake PO query: two assistant messages with usage, then a crash (no result)."""

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for mid in ("a", "b"):
            yield AssistantMessage(
                content=[TextBlock(text="t")], model=OPUS, usage=USAGE, message_id=mid
            )
        raise RuntimeError("crash")


class Resumed:
    """A fake PO query that reports one running total."""

    def __init__(self, total: float):
        self.total = total

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        yield result_message("ok", self.total, "sess")


def po_entries(run_dir: Path) -> list[Entry]:
    return [e for e in ledger_of(run_dir).entries() if e.role == "product-owner"]


# ----- the story's test: crash mid PO turn, then the next start -----------------------


def crash(make_runtime) -> Any:
    rt = make_runtime(Crashing())
    with pytest.raises(RuntimeError):
        asyncio.run(PoRun(rt, Start("t"))._turn(PoTurn("go", None)))
    return rt


def test_crash_mid_turn_is_ledgered_at_the_next_start(make_runtime, fake) -> None:
    rt = crash(make_runtime)
    run_dir = rt.config.run_dir
    lines = [Turn.from_line(x) for x in system.read_text(run_dir / TURNS).splitlines()]
    assert len(lines) == 2 and {t.role for t in lines} == {"product-owner"}
    assert po_entries(run_dir) == []
    fake.clock += 60
    written = reconcile.record_cut_off_spend(run_dir)
    got = po_entries(run_dir)
    assert len(got) == 1 and written == got
    assert got[0].story is None and got[0].turns == 2
    assert got[0].cost_usd == pytest.approx(sum(t.cost_usd or 0 for t in lines))
    assert got[0].cost_usd > 0
    assert got[0].tokens == sum((t.tokens for t in lines), Tokens())


def test_a_second_reconcile_writes_nothing(make_runtime, fake) -> None:
    run_dir = crash(make_runtime).config.run_dir
    fake.clock += 60
    reconcile.record_cut_off_spend(run_dir)
    total = ledger_of(run_dir).total()
    fake.clock += 60
    assert reconcile.record_cut_off_spend(run_dir) == []
    assert ledger_of(run_dir).total() == total


def test_the_next_start_ledgers_and_says_so(make_runtime, fake, capsys) -> None:
    rt = crash(make_runtime)
    fake.clock += 60
    cli._reconcile(rt.config)
    got = po_entries(rt.config.run_dir)
    assert len(got) == 1
    err = capsys.readouterr().err
    assert err == (
        f"agile-team start: ledgered ${got[0].cost_usd:.2f} for product-owner, "
        "cut off by the last run (estimated from turns.jsonl)\n"
    )


def test_told_line_names_role_and_story() -> None:
    entry = Entry("developer-cli", OPUS, 1.234, "s7")
    assert reconcile.format_told_line(entry) == (
        "agile-team start: ledgered $1.23 for developer-cli on s7, "
        "cut off by the last run (estimated from turns.jsonl)"
    )


# ----- covered and uncovered turns ----------------------------------------------------


def test_turns_before_their_row_are_covered(scratch: Path) -> None:
    put_turns(
        scratch,
        tline(1, role="developer-cli", story="s7"),
        tline(2, role="developer-cli", story="s7"),
        tline(10),
        tline(11),
    )
    ledger_of(scratch).record(row("developer-cli", 5, "s7"))
    written = reconcile.record_cut_off_spend(scratch)
    assert [(e.role, e.story) for e in written] == [("product-owner", None)]
    assert len(ledger_of(scratch).entries()) == 2


def test_only_turns_after_the_latest_row_count(scratch: Path) -> None:
    put_turns(scratch, tline(1, cost_usd=1.0), tline(2, cost_usd=2.0), tline(8, cost_usd=4.0))
    ledger_of(scratch).record(row("product-owner", 5, cost=2.5))
    (entry,) = reconcile.record_cut_off_spend(scratch)
    assert entry.cost_usd == pytest.approx(4.0) and entry.turns == 1


def test_a_turn_at_the_rows_time_is_covered(scratch: Path) -> None:
    put_turns(scratch, tline(5))
    ledger_of(scratch).record(row("product-owner", 5))
    assert reconcile.record_cut_off_spend(scratch) == []


def test_a_role_step_gets_its_own_row(scratch: Path) -> None:
    put_turns(
        scratch,
        tline(1, role="developer-cli", story="s7", cost_usd=2.0),
        tline(2),
        tline(3, role="developer-cli", story="s7", cost_usd=3.0),
    )
    first, second = reconcile.record_cut_off_spend(scratch)
    assert (first.role, first.story, first.cost_usd) == ("developer-cli", "s7", 5.0)
    assert (second.role, second.story, second.cost_usd) == ("product-owner", None, 1.0)


def test_same_role_other_story_is_a_separate_key(scratch: Path) -> None:
    put_turns(
        scratch, tline(1, role="architect", story="s1"), tline(2, role="architect", story="s2")
    )
    ledger_of(scratch).record(row("architect", 5, "s1"))
    (entry,) = reconcile.record_cut_off_spend(scratch)
    assert entry.story == "s2"


def test_rows_follow_the_first_uncovered_line(scratch: Path) -> None:
    put_turns(scratch, tline(1, role="b-role"), tline(2, role="a-role"), tline(3, role="b-role"))
    assert [e.role for e in reconcile.record_cut_off_spend(scratch)] == ["b-role", "a-role"]


# ----- how a key's turns are summed ---------------------------------------------------


def test_null_cost_counts_zero(scratch: Path) -> None:
    put_turns(scratch, tline(1, cost_usd=None), tline(2, cost_usd=1.5))
    (entry,) = reconcile.record_cut_off_spend(scratch)
    assert entry.cost_usd == pytest.approx(1.5)


def test_turns_count_distinct_message_ids(scratch: Path) -> None:
    put_turns(
        scratch,
        tline(1, message_id="x"),
        tline(2, message_id="x"),
        tline(3, message_id=None),
        tline(4, message_id=None),
        tline(5, message_id="y"),
    )
    (entry,) = reconcile.record_cut_off_spend(scratch)
    assert entry.turns == 4


def test_model_is_the_last_lines(scratch: Path) -> None:
    put_turns(scratch, tline(1, model="claude-opus-4-1"), tline(2, model="claude-sonnet-4-5"))
    (entry,) = reconcile.record_cut_off_spend(scratch)
    assert entry.model == "claude-sonnet-4-5"


def test_tokens_are_summed(scratch: Path) -> None:
    put_turns(scratch, tline(1, tokens=Tokens(1, 2, 3, 4)), tline(2, tokens=Tokens(10, 20, 30, 40)))
    (entry,) = reconcile.record_cut_off_spend(scratch)
    assert entry.tokens == Tokens(11, 22, 33, 44)


def test_the_row_is_stamped_at_the_start(scratch: Path, fake) -> None:
    put_turns(scratch, tline(fake.clock - 5))
    fake.clock += 100
    (entry,) = reconcile.record_cut_off_spend(scratch)
    assert entry.at == pytest.approx(fake.clock)


# ----- bad input ----------------------------------------------------------------------


def test_bad_lines_are_skipped(scratch: Path) -> None:
    good = tline(1, cost_usd=2.0)
    torn = tline(2).line()[:30]
    put_turns(scratch, good, "", "   ", torn, "[1, 2]", "3", '{"at": 1}', "not json", tline(3))
    (entry,) = reconcile.record_cut_off_spend(scratch)
    assert entry.cost_usd == pytest.approx(3.0) and entry.turns == 2


def test_a_torn_last_line_is_skipped(scratch: Path) -> None:
    system.write_text(scratch / TURNS, tline(1).line() + "\n" + tline(2).line()[:20])
    assert [t.at for t in reconcile.read_turns(scratch / TURNS)] == [1]


def test_missing_turns_file_reconciles_nothing(scratch: Path) -> None:
    assert reconcile.read_turns(scratch / TURNS) == []
    assert reconcile.record_cut_off_spend(scratch) == []
    assert not system.exists(scratch / LEDGER)


def test_empty_turns_file_reconciles_nothing(scratch: Path) -> None:
    put_turns(scratch)
    assert reconcile.record_cut_off_spend(scratch) == []


# ----- a live runner ------------------------------------------------------------------


def test_nothing_is_written_while_a_runner_is_alive(scratch: Path, monkeypatch) -> None:
    put_turns(scratch, tline(1))
    system.write_text(scratch / state_mod.PID_FILE, "4242")
    monkeypatch.setattr(system, "kill", lambda pid, sig: None)
    assert reconcile.record_cut_off_spend(scratch) == []
    assert not system.exists(scratch / LEDGER)


def test_a_dead_runner_pid_does_not_stop_it(scratch: Path, monkeypatch) -> None:
    def gone(pid: int, sig: int) -> None:
        raise ProcessLookupError

    put_turns(scratch, tline(1))
    system.write_text(scratch / state_mod.PID_FILE, "4242")
    monkeypatch.setattr(system, "kill", gone)
    assert len(reconcile.record_cut_off_spend(scratch)) == 1


# ----- the PO session's running total (RC7) -------------------------------------------


def test_reconciled_po_cost_is_noted_in_the_state(scratch: Path) -> None:
    state_mod.save(scratch, state_mod.RunState(po_cost=SessionCost("sess", 1.0)))
    put_turns(scratch, tline(1, cost_usd=0.5), tline(2, cost_usd=0.25))
    reconcile.record_cut_off_spend(scratch)
    assert state_mod.load(scratch).po_cost == SessionCost("sess", 1.0, 0.75)


def test_a_role_row_leaves_the_state_alone(scratch: Path) -> None:
    state_mod.save(scratch, state_mod.RunState(po_cost=SessionCost("sess", 1.0)))
    put_turns(scratch, tline(1, role="architect", story="s1"))
    reconcile.record_cut_off_spend(scratch)
    assert state_mod.load(scratch).po_cost == SessionCost("sess", 1.0)


def test_without_a_baseline_the_state_is_not_rewritten(scratch: Path) -> None:
    state_mod.save(scratch, state_mod.RunState())
    put_turns(scratch, tline(1))
    reconcile.record_cut_off_spend(scratch)
    assert state_mod.load(scratch).po_cost is None


def test_the_resumed_query_ledgers_only_what_is_new(make_runtime) -> None:
    rt = make_runtime(Resumed(0.0))
    run_dir = rt.config.run_dir
    state_mod.save(run_dir, state_mod.RunState(po_cost=SessionCost("sess", 1.0)))
    put_turns(run_dir, tline(1, cost_usd=0.5))
    reconcile.record_cut_off_spend(run_dir)
    rt.state = state_mod.load(run_dir)
    assert rt.state.po_cost == SessionCost("sess", 1.0, 0.5)
    rt.query_fn = Resumed(1.0 + 0.5 + 0.2)
    asyncio.run(PoRun(rt, Start("t"))._turn(PoTurn("go", "sess")))
    assert po_entries(run_dir)[-1].cost_usd == pytest.approx(0.2)
    assert state_mod.load(run_dir).po_cost == SessionCost("sess", 1.7, 0.0)


# ----- live.Turn.from_line ------------------------------------------------------------


def test_turn_from_line_round_trips() -> None:
    turn = tline(3, tools=["Bash"], story="s1", step="design", cost_usd=None, message_id=None)
    assert Turn.from_line(turn.line()) == turn


@pytest.mark.parametrize("text", ["", "nope", "[]", "1", '{"at": 1}'])
def test_turn_from_line_rejects_bad_lines(text: str) -> None:
    with pytest.raises((ValueError, TypeError, KeyError)):
        Turn.from_line(text)


def test_turn_line_is_json() -> None:
    assert json.loads(tline(1).line())["role"] == "product-owner"


# ----- a real start reconciles before the runtime loads state (RC1, RC7) ---------------


def test_cmd_start_reconciles_before_make_runtime(
    configured: Path, key_home: Path, fake, capsys, monkeypatch
) -> None:
    any_tool(fake)
    run_dir = cli._load_config(configured).run_dir
    put_turns(run_dir, tline(1.0), tline(2.0))
    seen: list[int] = []
    real = cli.make_runtime

    def spy(place, query):
        seen.append(len(po_entries(run_dir)))
        return real(place, query)

    monkeypatch.setattr(cli, "make_runtime", spy)
    args = start_args(configured, key_home, "--task", "t")
    assert cli.cmd_start(args, FakeQuery()) == 0
    assert seen == [1]
    assert "ledgered $2.00 for product-owner" in capsys.readouterr().err
