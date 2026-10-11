"""s38 end to end: the budget ceiling through ``cmd_start`` and ``cmd_status``, fake query."""

from __future__ import annotations

import json
import os
from functools import partial
from pathlib import Path

import pytest
import tomli_w
from agile_team import cli, preflight
from agile_team import config as config_mod
from agile_team import state as state_mod
from agile_team.ledger import PO_DELTAS_FROM, Entry, Ledger
from agile_team.state import RunStatus

from ..conftest import PY_CONFIG, git
from ..test_po_cost import Totals

EVIDENCE = os.environ.get("S38_EVIDENCE")


@pytest.fixture(autouse=True)
def real_preflight(monkeypatch) -> None:
    monkeypatch.setattr(cli, "Preflight", partial(preflight.Preflight, which=lambda e: e))


def set_budget(repo: Path, budget: float) -> None:
    team = {**PY_CONFIG["team"], "budget_usd": budget}
    (repo / config_mod.CONFIG_NAME).write_text(tomli_w.dumps({**PY_CONFIG, "team": team}))


def argv(repo: Path, home: Path, *rest: str) -> object:
    return cli.build_parser().parse_args(["--repo", str(repo), "--home", str(home), *rest])


def status(repo: Path, home: Path, capsys) -> dict:
    capsys.readouterr()
    assert cli.cmd_status(argv(repo, home, "status")) == 0
    return json.loads(capsys.readouterr().out)


def record(name: str, code: int, err: str, st: dict) -> None:
    if EVIDENCE:
        block = f"== {name}\nexit: {code}\nstderr: {err.strip()}\nstatus: {json.dumps(st)}\n\n"
        with open(EVIDENCE, "a") as f:
            f.write(block)


def run(repo: Path, home: Path, q, capsys, *rest: str) -> tuple[int, str]:
    capsys.readouterr()
    code = cli.cmd_start(argv(repo, home, "start", *rest), q)
    return code, capsys.readouterr().err


def accept(repo: Path, home: Path, capsys) -> None:
    """Keep the human's commit as the expected checkout (s61 K10)."""
    capsys.readouterr()
    assert cli.cmd_accept_checkout(argv(repo, home, "accept-checkout")) == 0
    assert "accepted checkout main at " in capsys.readouterr().out


def test_ac4_sequence(configured: Path, key_home: Path, capsys) -> None:
    set_budget(configured, 10.0)
    git(configured, "commit", "-q", "--allow-empty", "-am", "budget 10")
    q = Totals([1.0])
    code, err = run(configured, key_home, q, capsys, "--task", "t")
    st = status(configured, key_home, capsys)
    record("below the ceiling", code, err, st)
    assert code == 0 and st["status"] != "blocked"

    set_budget(configured, 4.0)
    git(configured, "commit", "-qam", "budget 4")
    accept(configured, key_home, capsys)
    q = Totals([4.0])
    code, err = run(configured, key_home, q, capsys, "--task", "t2")
    st = status(configured, key_home, capsys)
    record("reaches the ceiling during the run", code, err, st)
    assert code == 77 and st["status"] == "blocked"
    assert "budget reached: spent $" in st["status_reason"] and "of $4.00" in st["status_reason"]
    assert "raise team.budget_usd" in err

    q = Totals([1.0])
    code, err = run(configured, key_home, q, capsys, "--resume")
    st = status(configured, key_home, capsys)
    record("resume without a raise", code, err, st)
    assert code == 77 and q.calls == []

    set_budget(configured, 50.0)
    with pytest.raises(cli.CliError, match=r"dirty \(\.agile-team\.toml\)") as exc:
        run(configured, key_home, q, capsys, "--resume")
    st = status(configured, key_home, capsys)
    record("raise without committing", 1, str(exc.value), st)
    assert q.calls == [] and st["status"] == "blocked"

    git(configured, "commit", "-qam", "raise budget")
    accept(configured, key_home, capsys)
    q = Totals([5.0])
    code, err = run(configured, key_home, q, capsys, "--resume")
    st = status(configured, key_home, capsys)
    record("raise, commit, resume", code, err, st)
    assert code == 0 and len(q.calls) >= 1 and st["status"] != "blocked"


def test_over_at_start_makes_no_query(configured: Path, key_home: Path, capsys) -> None:
    set_budget(configured, 4.0)
    git(configured, "commit", "-qam", "budget 4")
    run_dir = configured / ".team/run"
    run_dir.mkdir(parents=True, exist_ok=True)
    Ledger(run_dir / "ledger.jsonl").record(Entry("scribe", "m", 5.0, "s1", PO_DELTAS_FROM + 100))
    q = Totals([1.0])
    code, err = run(configured, key_home, q, capsys, "--resume")
    st = status(configured, key_home, capsys)
    record("over the ceiling at start", code, err, st)
    assert code == 77 and q.calls == [] and "spent $5.00 of $4.00" in err
    assert state_mod.load(run_dir).status is RunStatus.BLOCKED


def test_status_shows_corrected_spend(configured: Path, key_home: Path, capsys) -> None:
    run_dir = configured / ".team/run"
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")
    for role, cost in [("product-owner", 1.0), ("architect", 0.4), ("product-owner", 1.5)]:
        ledger.record(Entry(role, "m", cost, "s1", 1.0))
    st = status(configured, key_home, capsys)
    assert st["budget"]["spent_usd"] == pytest.approx(1.9)
    assert st["budget"]["po_overcount_usd"] == pytest.approx(1.0)
