"""s25 end to end: resumed PO queries ledger their own cost, seen through `agile-team status`."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agile_team import cli
from agile_team import config as config_mod
from agile_team import state as state_mod
from agile_team.ledger import SessionCost
from agile_team.po_tools import PoRun, PoTurn, Start

from ..test_po_cost import Totals


def turn(run: PoRun, resume: str | None) -> None:
    asyncio.run(run._turn(PoTurn("go", resume)))


def status(configured: Path, capsys) -> dict:
    assert cli.main(["--repo", str(configured), "status"]) == 0
    return json.loads(capsys.readouterr().out)


def test_status_shows_real_spend_across_a_restart(make_runtime, configured, capsys) -> None:
    """AC2: running totals 1.0, 1.5, 2.25 over two processes give spend 2.25, not 4.75."""
    first = PoRun(make_runtime(Totals([1.0, 1.5])), Start("t"))
    turn(first, None)
    turn(first, "sess")
    first.runtime.save()
    # a new process: state comes back from state.json
    rt = make_runtime(Totals([2.25]))
    rt.state = state_mod.load(config_mod.load(configured).run_dir)
    assert rt.state.po_cost == SessionCost("sess", 1.5)
    turn(PoRun(rt, Start("t")), "sess")
    budget = status(configured, capsys)["budget"]
    assert budget["spent_usd"] == pytest.approx(2.25)
    assert budget["by_role"]["product-owner"] == pytest.approx(2.25)
    costs = [
        json.loads(x)["cost_usd"]
        for x in (rt.config.run_dir / "ledger.jsonl").read_text().splitlines()
    ]
    assert costs == pytest.approx([1.0, 0.5, 0.75])


def test_role_steps_keep_their_reported_cost(make_runtime) -> None:
    """AC2: role steps run in a fresh session, so their cost is already their own."""
    from agile_team.dispatch import StepRequest

    rt = make_runtime(Totals([], role_cost=0.6))
    for _ in range(2):
        asyncio.run(rt.run_role(StepRequest("unit-tester", "go", None)))
    costs = [e.cost_usd for e in rt.ledger.entries() if e.role == "unit-tester"]
    assert costs == pytest.approx([0.6, 0.6])
