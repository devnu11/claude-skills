"""s25: each PO query ledgers only its own cost, not the session's running total."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from agile_team import state as state_mod
from agile_team.dispatch import StepRequest
from agile_team.ledger import Entry, Ledger, SessionCost, budget_status
from agile_team.po_tools import PoRun, PoTurn, Start
from claude_agent_sdk import AssistantMessage, TextBlock

from .conftest import handoff, result_message
from .test_dispatch import LOCAL


class Totals:
    """A fake query: PO calls report the next running total; role steps a fixed cost."""

    def __init__(self, totals: list[float], sessions: list[str] | None = None, role_cost=0.0):
        self.totals, self.sessions, self.role_cost = list(totals), list(sessions or []), role_cost
        self.calls: list[Any] = []

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        self.calls.append(options)
        return self._gen("team" in (options.mcp_servers or {}))

    async def _gen(self, is_po: bool) -> AsyncIterator[Any]:
        yield AssistantMessage(content=[TextBlock(text="t")], model="m")
        if not is_po:
            yield result_message(handoff(), self.role_cost, "role-sess")
            return
        session = self.sessions.pop(0) if self.sessions else "sess"
        yield result_message("ok", self.totals.pop(0), session)


class Silent:
    """A fake query that never yields a ResultMessage."""

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        yield AssistantMessage(content=[TextBlock(text="t")], model="m")


def po_run(make_runtime, query: Any, **kw: Any) -> PoRun:
    rt = make_runtime(query, **kw)
    return PoRun(rt, Start("t"))


def turn(run: PoRun, resume: str | None = "sess") -> None:
    asyncio.run(run._turn(PoTurn("go", resume)))


def po_costs(run: PoRun) -> list[float]:
    return [e.cost_usd for e in run.runtime.ledger.entries() if e.role == "product-owner"]


# ----- SessionCost.own_cost -----------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "resumed", "reported", "own"),
    [
        (SessionCost("s", 1.0), None, 1.5, 1.5),  # fresh session
        (SessionCost("s", 1.0), "s", 1.5, 0.5),  # same session: delta
        (SessionCost("s", 1.0), "u", 0.9, 0.9),  # other session
        (SessionCost("s", 1.5), "s", 1.5, 0.0),  # nothing new
        (SessionCost("s", 5.0), "s", 0.2, 0.2),  # counter restarted
        (SessionCost(), "s", 0.7, 0.7),  # default stores nothing
        (SessionCost(None, 3.0), None, 0.4, 0.4),  # no session is not a match
    ],
)
def test_own_cost(stored: SessionCost, resumed, reported: float, own: float) -> None:
    assert stored.own_cost(resumed, reported) == pytest.approx(own)


def test_session_cost_defaults() -> None:
    assert (SessionCost().session, SessionCost().reported) == (None, 0.0)


# ----- Ledger.last_cost ---------------------------------------------------------------


def test_last_cost_without_a_file(scratch: Path) -> None:
    assert Ledger(scratch / "none.jsonl").last_cost("product-owner") == 0.0


def test_last_cost_is_the_last_entry_of_that_role(scratch: Path) -> None:
    led = Ledger(scratch / "l.jsonl")
    for role, cost in [("product-owner", 3.0), ("product-owner", 7.0), ("architect", 1.0)]:
        led.record(Entry(role, "m", cost))
    assert led.last_cost("product-owner") == 7.0
    assert led.last_cost("architect") == 1.0
    assert led.last_cost("devops") == 0.0


# ----- RunState -----------------------------------------------------------------------


def test_po_cost_round_trips_as_a_session_cost() -> None:
    st = state_mod.RunState(po_cost=SessionCost("s", 2.5))
    back = state_mod.RunState.from_json(st.to_json())
    assert back.po_cost == SessionCost("s", 2.5)
    assert isinstance(back.po_cost, SessionCost)


def test_state_without_po_cost_loads_none() -> None:
    data = json.loads(state_mod.RunState().to_json())
    data.pop("po_cost", None)
    assert state_mod.RunState.from_json(json.dumps(data)).po_cost is None
    assert state_mod.RunState().po_cost is None


# ----- PO turns -----------------------------------------------------------------------


def test_resumed_session_ledgers_deltas(make_runtime) -> None:
    run = po_run(make_runtime, Totals([1.0, 1.5, 2.25]))
    for resume in (None, "sess", "sess"):
        turn(run, resume)
    assert po_costs(run) == pytest.approx([1.0, 0.5, 0.75])
    assert run.runtime.state.po_cost == SessionCost("sess", 2.25)
    spent = budget_status(run.runtime.ledger, 10.0)["spent_usd"]
    assert spent == pytest.approx(2.25)


def test_baseline_survives_a_new_process(make_runtime) -> None:
    run = po_run(make_runtime, Totals([2.4]))
    run.runtime.state.po_cost = SessionCost("sess", 2.0)
    run.runtime.state.po_session = "sess"
    run.runtime.save()
    run.runtime.state = state_mod.RunState.from_json(run.runtime.state.to_json())
    turn(run)
    assert po_costs(run) == pytest.approx([0.4])


def test_the_baseline_is_saved_with_the_entry(make_runtime) -> None:
    run = po_run(make_runtime, Totals([1.2]))
    turn(run, None)
    saved = state_mod.load(run.runtime.config.run_dir)
    assert saved.po_cost == SessionCost("sess", 1.2)


def test_fresh_session_after_renewal_ledgers_full_cost(make_runtime) -> None:
    run = po_run(make_runtime, Totals([0.3], ["new"]))
    run.runtime.state.po_cost = SessionCost("sess", 5.0)
    turn(run, None)
    assert po_costs(run) == pytest.approx([0.3])
    assert run.runtime.state.po_cost == SessionCost("new", 0.3)


def test_legacy_state_seeds_from_the_last_po_entry(make_runtime) -> None:
    run = po_run(make_runtime, Totals([7.4], ["old"]))
    rt = run.runtime
    for role, cost in [("product-owner", 3.0), ("product-owner", 7.0), ("architect", 0.5)]:
        rt.ledger.record(Entry(role, "m", cost))
    rt.state.po_session, rt.state.po_cost = "old", None
    turn(run, "old")
    assert po_costs(run)[-1] == pytest.approx(0.4)
    assert rt.state.po_cost == SessionCost("old", 7.4)


def test_fresh_state_has_no_baseline(make_runtime) -> None:
    run = po_run(make_runtime, Totals([1.0]))
    turn(run, None)
    assert po_costs(run) == [1.0]


def test_a_drop_in_the_running_total_is_a_restart(make_runtime) -> None:
    run = po_run(make_runtime, Totals([0.2]))
    run.runtime.state.po_cost = SessionCost("sess", 5.0)
    turn(run)
    assert po_costs(run) == pytest.approx([0.2])
    assert run.runtime.state.po_cost == SessionCost("sess", 0.2)


def test_a_session_saved_by_an_error_is_charged_in_full(make_runtime) -> None:
    run = po_run(make_runtime, Totals([0.9], ["u"]))
    run.runtime.state.po_cost = SessionCost("s", 2.0)
    run.runtime.state.po_session = "u"
    turn(run, "u")
    assert po_costs(run) == pytest.approx([0.9])
    assert run.runtime.state.po_cost == SessionCost("u", 0.9)


def test_no_result_ledgers_nothing_and_keeps_the_baseline(make_runtime) -> None:
    run = po_run(make_runtime, Silent())
    run.runtime.state.po_cost = SessionCost("sess", 2.0)
    turn(run)
    assert po_costs(run) == [0.0]
    assert run.runtime.state.po_cost == SessionCost("sess", 2.0)


def test_free_provider_ledgers_zero_but_keeps_the_raw_baseline(make_runtime) -> None:
    run = po_run(make_runtime, Totals([1.0, 1.5]), providers=LOCAL)
    run.runtime.book.config_roles["product-owner"] = {"provider": "local", "model": "qwen3-coder"}
    turn(run, None)
    turn(run)
    assert po_costs(run) == [0.0, 0.0]
    assert run.runtime.state.po_cost == SessionCost("sess", 1.5)


def test_crash_before_the_record_leaves_the_ledger_and_baseline_unsaved(make_runtime) -> None:
    run = po_run(make_runtime, Totals([1.0, 1.5]))
    turn(run, None)

    def boom() -> dict:
        raise RuntimeError("settle failed")

    run.runtime.settle_po = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        turn(run)
    assert po_costs(run) == [1.0]
    assert state_mod.load(run.runtime.config.run_dir).po_cost == SessionCost("sess", 1.0)


# ----- budget and role steps ----------------------------------------------------------


def test_checkpoint_reflects_real_spend(make_runtime) -> None:
    run = po_run(make_runtime, Totals([1.0, 1.5], role_cost=0.6))
    rt = run.runtime
    rt.config.team.budget_usd, rt.config.team.manager_every_pct = 4.0, 25
    turn(run, None)
    turn(run)
    assert rt.ledger.total() == pytest.approx(1.5)
    asyncio.run(rt.run_role(StepRequest("devops", "go", None)))
    assert rt.state.manager_due == ["budget checkpoint at $2.10"]


def test_role_steps_run_fresh_and_ledger_their_reported_cost(make_runtime) -> None:
    q = Totals([], role_cost=0.4)
    rt = make_runtime(q)
    for _ in range(2):
        asyncio.run(rt.run_role(StepRequest("devops", "go", None)))
    assert [o.resume for o in q.calls] == [None, None]
    assert [e.cost_usd for e in rt.ledger.entries()] == pytest.approx([0.4, 0.4])
    assert rt.state.po_cost is None
