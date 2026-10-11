"""s38: corrected ledger reads (ADR-007), the budget ceiling and its halt (exit 77)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agile_team import cli, halt, salvage
from agile_team import state as state_mod
from agile_team.dashboard import snapshot
from agile_team.dispatch import StepRequest
from agile_team.ledger import (
    PO_DELTAS_FROM,
    Entry,
    Ledger,
    budget_status,
    corrected,
)
from agile_team.po_tools import PoRun, PoTurn, Start, StartMode
from agile_team.relay import Relay
from agile_team.state import RunStatus

from .conftest import FakeQuery
from .test_po_cost import Totals

PO = "product-owner"
LATER = PO_DELTAS_FROM + 100.0
REASON = "budget reached: spent $4.00 of $4.00"
ADVICE = (
    "raise team.budget_usd in .agile-team.toml and commit it, then run `agile-team start --resume`"
)


def entry(role: str, cost: float, at: float = 1.0) -> Entry:
    return Entry(role, "m", cost, "s1", at)


def worked_example() -> list[Entry]:
    return [
        entry(PO, 1.00),
        entry("architect", 0.40),
        entry(PO, 1.50),
        entry(PO, 2.25),
        entry(PO, 0.30),
        entry(PO, 0.80),
        entry(PO, 0.90, LATER),
        entry(PO, 1.20, LATER + 1),
    ]


def write_ledger(path: Path, entries: list[Entry]) -> Ledger:
    ledger = Ledger(path)
    for e in entries:
        ledger.record(e)
    return ledger


# ----- corrected (K2, K3) ------------------------------------------------------------


def test_corrected_matches_the_worked_example() -> None:
    entries = worked_example()
    before = [e.cost_usd for e in entries]
    costs = [e.cost_usd for e in corrected(entries)]
    assert costs == pytest.approx([1.00, 0.40, 0.50, 0.75, 0.30, 0.50, 0.90, 1.20])
    assert [e.cost_usd for e in entries] == before


def test_corrected_keeps_everything_but_cost() -> None:
    raw = [entry(PO, 1.0), entry(PO, 1.5)]
    out = corrected(raw)[1]
    assert (out.role, out.model, out.story, out.at) == (PO, "m", "s1", 1.0)


def test_corrected_passes_through() -> None:
    rising = [entry("developer-cli", c) for c in (1.0, 2.0, 3.0)]
    later = [entry(PO, c, LATER) for c in (1.0, 2.0, 3.0)]
    assert corrected([]) == []
    assert [e.cost_usd for e in corrected(rising + later)] == [1.0, 2.0, 3.0] * 2


def test_a_po_line_without_at_is_legacy() -> None:
    raw = [Entry(PO, "m", 1.0), Entry(PO, "m", 1.5)]
    assert [e.cost_usd for e in corrected(raw)] == pytest.approx([1.0, 0.5])


# ----- Ledger (K1, K4, K5, K6) -------------------------------------------------------


def test_ledger_reads_are_corrected_and_the_file_is_untouched(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "l.jsonl", worked_example())
    text = ledger.path.read_text()
    assert ledger.total() == pytest.approx(5.55)
    assert [e.cost_usd for e in ledger.entries()][2] == pytest.approx(0.5)
    assert ledger.by_role()[PO] == pytest.approx(5.15)
    assert ledger.totals("role")[PO].cost_usd == pytest.approx(5.15)
    assert ledger.path.read_text() == text


def test_last_cost_and_overcount(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "l.jsonl", worked_example())
    assert ledger.last_cost(PO) == 1.20
    assert ledger.last_cost("architect") == 0.40
    legacy = write_ledger(tmp_path / "m.jsonl", [entry(PO, 1.0), entry(PO, 2.0)])
    assert legacy.last_cost(PO) == 2.0
    assert ledger.overcount() == pytest.approx(2.80)


def test_a_missing_ledger_is_empty(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "none.jsonl")
    assert (ledger.entries(), ledger.total(), ledger.overcount()) == ([], 0.0, 0.0)
    assert (ledger.by_role(), ledger.last_cost(PO)) == ({}, 0.0)


def test_budget_status_uses_corrected_figures(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "l.jsonl", worked_example())
    status = budget_status(ledger, 10.0)
    assert status["spent_usd"] == 5.55
    assert status["remaining_usd"] == 4.45
    assert status["pct_used"] == 55.5
    assert status["by_role"] == {"architect": 0.4, PO: 5.15}
    assert status["po_overcount_usd"] == 2.8
    keys = list(status)
    assert keys.index("po_overcount_usd") == keys.index("pct_used") + 1


def test_budget_status_overcount_is_zero_without_legacy_lines(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "l.jsonl", [entry(PO, 1.0, LATER), entry("scribe", 0.5)])
    assert budget_status(ledger, 10.0)["po_overcount_usd"] == 0.0


# ----- AC2: one path everywhere ------------------------------------------------------


def test_every_reader_shows_the_same_corrected_total(make_runtime) -> None:
    rt = make_runtime()
    write_ledger(rt.ledger.path, worked_example())
    config = rt.config
    from agile_team.roles import RoleBook

    snap = snapshot.build(config, RoleBook.for_repo(config.repo, config.roles))
    context = rt._manager_context().split("Runner context:\n", 1)[1]
    figures = [
        cli.status_report(config)["budget"]["spent_usd"],
        round(sum(row["cost_usd"] for row in snap["ledger"]), 4),
        budget_status(rt.ledger, config.team.budget_usd)["spent_usd"],
        json.loads(context)["budget"]["spent_usd"],
    ]
    assert figures == [5.55] * 4


# ----- halt.budget_halt, HALTS, Cause (B1, B5, B8) -----------------------------------


def test_below_the_ceiling_does_not_halt() -> None:
    assert halt.budget_halt(3.99, 4.0) is None


@pytest.mark.parametrize(
    ("spent", "budget", "reason"),
    [
        (4.0, 4.0, REASON),
        (4.5, 4.0, "budget reached: spent $4.50 of $4.00"),
        (3.99995, 4.0, REASON),
    ],
)
def test_reaching_the_ceiling_halts(spent: float, budget: float, reason: str) -> None:
    assert halt.budget_halt(spent, budget) == halt.Halt(halt.HaltKind.BUDGET, reason)


def test_thousands_separator_in_the_reason() -> None:
    found = halt.budget_halt(1500.0, 1500.0)
    assert found.reason == "budget reached: spent $1,500.00 of $1,500.00"
    assert halt.budget_halt(1213.0, 1500.0) is None


def test_the_budget_halt_rule() -> None:
    rule = halt.HALTS[halt.HaltKind.BUDGET]
    assert (rule.status, rule.note_kind, rule.exit_code) == (RunStatus.BLOCKED, "blocked", 77)
    assert halt.budget_halt(4.0, 4.0).message() == f"{REASON}; {ADVICE}"
    assert salvage.Cause("budget") is salvage.Cause.BUDGET


# ----- Runtime.enforce_ceiling (B3) --------------------------------------------------


def test_enforce_ceiling_below_does_nothing(make_runtime) -> None:
    rt = make_runtime()
    rt.config.team.budget_usd = 4.0
    rt.ledger.record(entry("scribe", 1.0))
    assert rt.enforce_ceiling() is None
    assert rt.state.status is not RunStatus.BLOCKED
    assert Relay(rt.config.run_dir).messages() == []


def test_enforce_ceiling_at_the_ceiling_blocks_once(make_runtime) -> None:
    rt = make_runtime()
    rt.config.team.budget_usd = 4.0
    rt.ledger.record(entry("scribe", 4.0))
    found = rt.enforce_ceiling()
    assert found.kind is halt.HaltKind.BUDGET
    assert (rt.state.status, rt.state.status_reason) == (RunStatus.BLOCKED, REASON)
    rt.enforce_ceiling()
    kinds = [m.kind for m in Relay(rt.config.run_dir).messages()]
    assert kinds == ["blocked"]


# ----- role step reaches the ceiling (B2a, B7) ---------------------------------------


def test_a_role_step_lands_then_the_run_blocks(make_runtime, configured) -> None:
    def write() -> None:
        (configured / "src" / "app.py").write_text("x = 2\n")

    rt = make_runtime(FakeQuery(cost=1.2, action=write))
    rt.config.team.budget_usd = 1.0
    report = asyncio.run(rt.run_role(StepRequest("scribe", "go", None)))
    assert report["status"] != "halted"
    assert rt.state.interrupted == []
    assert rt.state.in_flight is None
    assert (rt.state.status, rt.state.status_reason) == (
        RunStatus.BLOCKED,
        "budget reached: spent $1.20 of $1.00",
    )
    again = asyncio.run(rt.run_role(StepRequest("scribe", "go", None)))
    assert again == {
        "status": "refused",
        "reason": "the run is blocked (budget reached: spent $1.20 of $1.00); end your turn",
    }


def test_a_role_step_below_the_ceiling_does_not_block(make_runtime) -> None:
    rt = make_runtime(FakeQuery(cost=0.5))
    rt.config.team.budget_usd = 1.0
    asyncio.run(rt.run_role(StepRequest("scribe", "go", None)))
    assert rt.state.status is not RunStatus.BLOCKED


# ----- PO query reaches the ceiling (B2b, B4) and AC4 through cli --------------------


def blocked_notes(rt) -> list:
    return [m for m in Relay(rt.config.run_dir).messages() if m.kind == "blocked"]


def test_below_the_ceiling_start_runs(make_runtime) -> None:
    q = Totals([1.0])
    rt = make_runtime(q)
    rt.config.team.budget_usd = 4.0
    assert cli._run(rt, Start("task")) == 0
    assert len(q.calls) == 1
    assert state_mod.load(rt.config.run_dir).status is not RunStatus.BLOCKED


def test_a_po_query_reaching_the_ceiling_exits_77(make_runtime, capsys) -> None:
    q = Totals([4.0, 9.0])
    rt = make_runtime(q)
    rt.config.team.budget_usd = 4.0
    assert cli._run(rt, Start("task")) == 77
    saved = state_mod.load(rt.config.run_dir)
    assert (saved.status, saved.status_reason) == (RunStatus.BLOCKED, REASON)
    assert [m.text for m in blocked_notes(rt)] == [f"{REASON}; {ADVICE}"]
    assert capsys.readouterr().err == f"agile-team start: {REASON}; {ADVICE}\n"
    assert len(q.calls) == 1


def test_a_renewal_turn_that_halts_gets_no_main_query(make_runtime) -> None:
    q = Totals([5.0, 6.0])
    rt = make_runtime(q)
    rt.config.team.budget_usd = 4.0
    run = PoRun(rt, Start("t"))
    asyncio.run(run._turn(PoTurn("renew", None)))
    assert rt.halted_by is not None
    result = asyncio.run(run._turn(PoTurn("main", None)))
    assert (result.text, result.cost) == ("", 0.0)
    assert len(q.calls) == 1


def over_at_start(make_runtime, budget: float = 4.0):
    q = Totals([0.1, 0.1])
    rt = make_runtime(q)
    rt.config.team.budget_usd = budget
    rt.ledger.record(entry("scribe", 5.0, LATER))
    return rt, q


def test_over_at_start_makes_no_query_and_keeps_interrupted(make_runtime, capsys) -> None:
    rt, q = over_at_start(make_runtime)
    found = salvage.Interruption("developer-cli", "s1", "brief", salvage.Cause.ERROR, None)
    rt.state.interrupted.append(found)
    assert cli._run(rt, Start("resume", StartMode.RESUME)) == 77
    assert q.calls == []
    assert state_mod.load(rt.config.run_dir).interrupted == [found]
    assert "budget reached: spent $5.00 of $4.00" in capsys.readouterr().err


def test_raise_then_resume_runs_and_no_raise_halts_again(make_runtime) -> None:
    rt, q = over_at_start(make_runtime)
    assert cli._run(rt, Start("r", StartMode.RESUME)) == 77
    assert cli._run(rt, Start("r", StartMode.RESUME)) == 77
    assert q.calls == []
    rt.config.team.budget_usd = 50.0
    assert cli._run(rt, Start("r", StartMode.RESUME)) == 0
    assert len(q.calls) == 1
    assert state_mod.load(rt.config.run_dir).status is not RunStatus.BLOCKED


# ----- AC4 through the real start entry point (checklist 12, B9) -----------------------


def start_resume(repo: Path, home: Path, q) -> int:
    args = cli.build_parser().parse_args(
        ["--repo", str(repo), "--home", str(home), "start", "--resume"]
    )
    return cli.cmd_start(args, q)


def set_budget(repo: Path, budget: float) -> None:
    import tomli_w
    from agile_team import config as config_mod

    from .conftest import PY_CONFIG

    team = {**PY_CONFIG["team"], "budget_usd": budget}
    text = tomli_w.dumps({**PY_CONFIG, "team": team})
    (repo / config_mod.CONFIG_NAME).write_text(text)


def blocked_at_four(configured: Path, key_home: Path, monkeypatch) -> Totals:
    from functools import partial

    from agile_team import preflight

    monkeypatch.setattr(cli, "Preflight", partial(preflight.Preflight, which=lambda e: e))
    set_budget(configured, 4.0)
    from .conftest import git

    git(configured, "commit", "-qam", "budget 4")
    q = Totals([4.0])
    args = cli.build_parser().parse_args(
        ["--repo", str(configured), "--home", str(key_home), "start", "--task", "t"]
    )
    assert cli.cmd_start(args, q) == 77
    return q


def test_resume_without_a_raise_halts_again_with_no_query(
    configured: Path, key_home: Path, monkeypatch
) -> None:
    blocked_at_four(configured, key_home, monkeypatch)
    q = Totals([1.0])
    assert start_resume(configured, key_home, q) == 77
    assert q.calls == []


def test_an_uncommitted_raise_is_refused_by_preflight(
    configured: Path, key_home: Path, monkeypatch
) -> None:
    blocked_at_four(configured, key_home, monkeypatch)
    set_budget(configured, 50.0)
    q = Totals([1.0])
    with pytest.raises(cli.CliError, match=r"dirty \(\.agile-team\.toml\)"):
        start_resume(configured, key_home, q)
    assert q.calls == []
    run_dir = configured / ".team/run"
    assert state_mod.load(run_dir).status is RunStatus.BLOCKED


def test_a_committed_raise_lets_resume_run(configured: Path, key_home: Path, monkeypatch) -> None:
    blocked_at_four(configured, key_home, monkeypatch)
    set_budget(configured, 50.0)
    from .conftest import git

    git(configured, "commit", "-qam", "raise budget")
    q = Totals([5.0])
    assert start_resume(configured, key_home, q) == 0
    assert len(q.calls) >= 1
    assert state_mod.load(configured / ".team/run").status is not RunStatus.BLOCKED
