"""s10 end to end: a start ledgers the PO spend a crash cut off, once (AC1, AC2)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from agile_team import cli
from agile_team.po_tools import PoRun, PoTurn, Start
from claude_agent_sdk import AssistantMessage, TextBlock

from ..conftest import FakeQuery
from ..test_cli import start_args


class Crashing:
    """A PO query that writes two model turns, then dies before any ResultMessage."""

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for i in range(2):
            yield AssistantMessage(
                content=[TextBlock(text="t")],
                model="claude-opus-4-1",
                usage={"input_tokens": 1000, "output_tokens": 500},
                message_id=f"m{i}",
            )
        raise RuntimeError("crash")


def crash(make_runtime) -> Any:
    rt = make_runtime(Crashing())
    with pytest.raises(RuntimeError):
        asyncio.run(PoRun(rt, Start("t"))._turn(PoTurn("go", None)))
    return rt.config.run_dir


def po_rows(run_dir) -> list[dict]:
    lines = (
        (run_dir / "ledger.jsonl").read_text().splitlines()
        if (run_dir / "ledger.jsonl").exists()
        else []
    )
    return [r for r in map(json.loads, lines) if r["role"] == "product-owner"]


def test_next_start_ledgers_the_cut_off_po_turns_once(
    make_runtime, configured, key_home, capsys
) -> None:
    run_dir = crash(make_runtime)
    turns = [json.loads(x) for x in (run_dir / "turns.jsonl").read_text().splitlines()]
    assert len(turns) == 2 and po_rows(run_dir) == []
    expected = sum(t["cost_usd"] for t in turns)
    assert expected > 0
    capsys.readouterr()
    args = start_args(configured, key_home, "--task", "again")
    assert cli.cmd_start(args, FakeQuery()) == 0
    assert "cut off by the last run" in capsys.readouterr().err
    rows = [r for r in po_rows(run_dir) if r["turns"] == 2]
    assert len(rows) == 1 and rows[0]["cost_usd"] == pytest.approx(expected)
    assert cli.cmd_start(start_args(configured, key_home, "--task", "x"), FakeQuery()) == 0
    assert len([r for r in po_rows(run_dir) if r["turns"] == 2]) == 1
