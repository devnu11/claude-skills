"""s123: a devops fix's handover holds ``fix_handover``; a bad stored hold is dropped at load."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from agile_team import boundary as bd
from agile_team import boundary_runner as br
from agile_team import cli, system, watch
from agile_team import config as config_mod
from agile_team import state as state_mod
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.events import EventKind
from agile_team.po_tools import Tools
from agile_team.state import BAD_HOLD, LoadFault, RunState

from .conftest import FakeQuery
from .fake_system import FakeSystem
from .test_boundary_runner import Env, fail_lint
from .test_boundary_wiring import call
from .test_cli import any_tool, start_args

BAD = "stopped, questions"
FAULT = LoadFault("boundary.hold", BAD, BAD_HOLD)
BLOCKED = {"role": "devops", "status": "blocked", "open_questions": ["q"]}


def state_text(hold, faults=None) -> str:
    """A saved state whose boundary holds ``hold`` (any JSON value)."""
    data = json.loads(RunState(boundary=bd.Boundary(Edge.END, 2, rounds=1)).to_json())
    data["boundary"]["hold"] = hold
    if faults is not None:
        data["load_faults"] = faults
    return json.dumps(data)


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


# ----- H1-H4: the fix's handover ---------------------------------------------


def test_fix_handover_is_the_last_hold() -> None:
    assert list(BoundaryHold)[-1] is BoundaryHold.FIX_HANDOVER == "fix_handover"


def test_fix_hold_follows_the_triggers() -> None:
    assert br.fix_hold(BLOCKED) is BoundaryHold.FIX_HANDOVER
    assert br.fix_hold({"role": "devops", "status": "done"}) is None


def test_a_fix_with_triggers_holds_fix_handover_and_the_state_loads(env: Env) -> None:
    fail_lint(env)
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    env.br.after_fix(BLOCKED)
    b = env.rt.state.boundary
    assert b.hold is BoundaryHold.FIX_HANDOVER and b.failure is None and b.rounds == 1
    env.rt.save()
    assert state_mod.load(env.rt.config.run_dir).boundary.hold is BoundaryHold.FIX_HANDOVER
    assert env.br.due() is None


def test_a_quiet_fix_holds_nothing(env: Env) -> None:
    fail_lint(env)
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    env.br.after_fix({"role": "devops", "status": "done"})
    b = env.rt.state.boundary
    assert (b.hold, b.failure, b.rounds) == (None, None, 1)


def test_a_halted_fix_still_changes_nothing(env: Env) -> None:
    fail_lint(env)
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    env.br.after_fix({"role": "devops", "status": "halted"})
    b = env.rt.state.boundary
    assert b.rounds == 0 and b.failure is not None and b.hold is None


def test_the_stall_hint_names_continue_boundary() -> None:
    assert "continue_boundary" in bd.stall_hint(BoundaryHold.FIX_HANDOVER)
    assert bd.STALL_HINTS[BoundaryHold.FIX_HANDOVER] == (
        "answer the devops fix's handover, then continue_boundary(note) to rerun the stage"
    )


def test_continue_boundary_releases_fix_handover_and_keeps_rounds(make_runtime) -> None:
    rt = make_runtime()
    rt.state.boundary = bd.Boundary(Edge.END, 2, hold=BoundaryHold.FIX_HANDOVER, rounds=2)
    call(Tools(rt).continue_boundary({"note": "answered"}))
    b = rt.state.boundary
    assert (b.hold, b.rounds, b.note) == (None, 2, "answered")


# ----- L1/L2/L5: loading ------------------------------------------------------


def test_a_bad_stored_hold_is_dropped_and_recorded() -> None:
    st = RunState.from_json(state_text(BAD))
    assert st.boundary.hold is None and st.boundary.rounds == 1
    assert st.boundary.edge is Edge.END and st.boundary.sprint == 2
    assert st.load_faults == [FAULT]


@pytest.mark.parametrize("hold", [["x"], 7, {"a": 1}])
def test_a_non_string_hold_is_dropped_and_recorded(hold) -> None:
    st = RunState.from_json(state_text(hold))
    assert st.boundary.hold is None
    assert st.load_faults == [LoadFault("boundary.hold", str(hold), BAD_HOLD)]


def test_a_valid_hold_loads_with_no_fault() -> None:
    st = RunState.from_json(state_text("ci_failed"))
    assert st.boundary.hold is BoundaryHold.CI_FAILED and st.load_faults == []


@pytest.mark.parametrize("hold", [None, ""])
def test_an_empty_hold_loads_as_none_with_no_fault(hold) -> None:
    st = RunState.from_json(state_text(hold))
    assert st.boundary.hold is None and st.load_faults == []


def test_a_state_with_no_boundary_has_no_fault() -> None:
    assert RunState.from_json(RunState().to_json()).load_faults == []


def test_load_faults_round_trip_through_json() -> None:
    st = RunState(load_faults=[FAULT])
    assert json.loads(st.to_json())["load_faults"] == [asdict(FAULT)]
    assert RunState.from_json(st.to_json()).load_faults == [FAULT]


def test_a_listed_fault_is_not_duplicated_on_load() -> None:
    st = RunState.from_json(state_text(BAD, [asdict(FAULT)]))
    assert st.load_faults == [FAULT]


def test_a_new_fault_is_appended_to_the_stored_ones() -> None:
    other = LoadFault("x", "y", "z")
    st = RunState.from_json(state_text(BAD, [asdict(other)]))
    assert st.load_faults == [other, FAULT]


def test_building_a_boundary_with_a_bad_hold_still_raises() -> None:
    with pytest.raises(ValueError):
        bd.Boundary(Edge.END, 1, hold="bogus")


# ----- L3: Runtime.report_load_faults -----------------------------------------


def fault_events(rt) -> list:
    return [e for e in rt.events.events() if e.kind == EventKind.FAULT]


def test_report_load_faults_emits_one_event_clears_and_saves(make_runtime) -> None:
    rt = make_runtime()
    rt.state.load_faults = [FAULT]
    rt.report_load_faults()
    [event] = fault_events(rt)
    assert event.role is None and event.story is None
    assert event.data == {
        "fault": "state",
        "field": "boundary.hold",
        "value": BAD,
        "reason": BAD_HOLD,
    }
    assert rt.state.load_faults == []
    assert state_mod.load(rt.config.run_dir).load_faults == []
    rt.report_load_faults()
    assert len(fault_events(rt)) == 1


def test_report_load_faults_with_none_emits_and_saves_nothing(make_runtime) -> None:
    rt = make_runtime()
    rt.report_load_faults()
    assert fault_events(rt) == []
    assert not system.exists(rt.config.run_dir / state_mod.STATE_FILE)


# ----- AC2: start, watch and status -------------------------------------------


def test_start_reports_the_bad_hold_once(configured: Path, key_home: Path, fake: FakeSystem):
    any_tool(fake)
    run_dir = configured / ".team/run"
    system.make_dirs(run_dir)
    system.write_text(run_dir / state_mod.STATE_FILE, state_text(BAD))
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 0
    log = system.read_text(run_dir / "events.jsonl").splitlines()
    faults = [e for e in map(json.loads, log) if e["kind"] == "fault"]
    [fault] = [f for f in faults if f["data"].get("fault") == "state"]
    assert fault["data"]["value"] == BAD and fault["story"] is None
    assert state_mod.load(run_dir).boundary is None or state_mod.load(run_dir).load_faults == []


def test_status_and_watch_read_a_bad_hold_without_events(configured: Path, fake: FakeSystem):
    run_dir = configured / ".team/run"
    system.make_dirs(run_dir)
    system.write_text(run_dir / state_mod.STATE_FILE, state_text(BAD))
    config = config_mod.load(configured)
    assert cli.status_report(config)
    assert isinstance(watch.Watcher(run_dir).until(0), dict)
    assert not system.exists(run_dir / "events.jsonl")
