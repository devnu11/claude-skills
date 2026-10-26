"""s184: a done at a sprint end waits for the boundary and survives a re-pin (D1 to D7)."""

from __future__ import annotations

import argparse
import json

import pytest
from agile_team import boundary as bd
from agile_team import cli, po_tools, repin, sprint_end
from agile_team import config as config_mod
from agile_team import state as state_mod
from agile_team.boundary_runner import BoundaryRunner
from agile_team.po_tools import Start, Tools
from agile_team.scheduler import Scheduler
from agile_team.state import RunState, RunStatus

from .fake_system import Done, FakeSystem
from .test_po_tools import call
from .test_s128_keep_going import ended_sprint, stuck_sprint

REASON = "Stop after 52"
NOTE = f"{REASON}\nmore detail"


@pytest.fixture(autouse=True)
def tracked(configured, fake: FakeSystem) -> None:
    fake.track()
    fake.reply(("git", "remote", "get-url"), Done(2))


def done_call(rt, text: str = NOTE) -> dict:
    return call(Tools(rt).notify_user({"kind": "done", "text": text}))


def pending_end(make_runtime):
    """Sprint 1 is complete under until-blocker with ready backlog; its end boundary is open."""
    rt = ended_sprint(make_runtime)
    rt.state.boundary = bd.Boundary(bd.Edge.END, 1)
    return rt


def held_message(rt) -> str:
    return po_tools.DONE_HELD.format(sprint=rt.state.sprint)


# ----- D1, D2: a done waits for a pending boundary --------------------------------------------


def test_done_during_an_end_boundary_is_held(make_runtime) -> None:
    rt = pending_end(make_runtime)
    before = rt.state.status
    out = done_call(rt)
    assert set(out) == {"id", "held"} and out["held"] == held_message(rt)
    assert rt.state.status is before and rt.state.held_done == REASON
    [note] = rt.relay.messages()
    assert (note.kind, note.text) == ("done", NOTE)


def test_done_after_a_complete_sprint_whose_end_has_not_opened_is_held(make_runtime) -> None:
    rt = ended_sprint(make_runtime)
    rt.state.upstream.closed = 0
    assert rt.state.boundary is None
    out = done_call(rt)
    assert out["held"] == held_message(rt)
    assert rt.state.held_done == REASON and rt.state.status is not RunStatus.DONE


def test_done_during_a_start_boundary_is_held(make_runtime) -> None:
    rt = ended_sprint(make_runtime)
    rt.state.boundary = bd.Boundary(bd.Edge.START, 1)
    assert "held" in done_call(rt)
    assert rt.state.held_done == REASON


def test_done_with_the_end_boundary_closed_marks_done_at_once(make_runtime) -> None:
    rt = ended_sprint(make_runtime)
    rt.state.upstream.closed = 1
    out = done_call(rt)
    assert set(out) == {"id"}
    assert rt.state.status is RunStatus.DONE and rt.state.status_reason == REASON
    assert rt.state.held_done is None


@pytest.mark.parametrize("cadence", ["sprint", "until-blocker"])
def test_done_on_an_open_incomplete_sprint_lands_at_once(make_runtime, cadence: str) -> None:
    rt = stuck_sprint(make_runtime, cadence)
    assert rt.state.sprint_open() and not rt.state.sprint_complete()
    assert rt.state.boundary is None
    out = done_call(rt)
    assert set(out) == {"id"}
    assert rt.state.status is RunStatus.DONE and rt.state.status_reason == REASON
    assert rt.state.held_done is None


def test_closing_a_start_boundary_on_an_incomplete_sprint_releases_the_held_done(
    make_runtime,
) -> None:
    rt = stuck_sprint(make_runtime)
    rt.state.boundary = bd.Boundary(bd.Edge.START, 1)
    assert "held" in done_call(rt)
    BoundaryRunner(rt)._close(rt.state.boundary, "")
    assert rt.state.status is RunStatus.DONE and rt.state.status_reason == REASON
    assert rt.state.held_done is None and rt.state.boundary is None


def test_a_refused_done_holds_nothing(make_runtime) -> None:
    rt = ended_sprint(make_runtime)
    rt.state.upstream.closed = 0
    rt.state.stories["s3"].sprint = 1  # a Sprint Backlog story that can move
    out = done_call(rt)
    assert out["status"] == "refused"
    assert rt.state.held_done is None and rt.relay.messages() == []


@pytest.mark.parametrize("kind", ["sprint-end", "blocked"])
def test_other_status_notes_hold_nothing(make_runtime, kind: str) -> None:
    rt = pending_end(make_runtime)
    rt.state.cadence = "sprint"
    out = call(Tools(rt).notify_user({"kind": kind, "text": "x"}))
    assert "held" not in out and rt.state.held_done is None


def test_an_empty_done_holds_an_empty_reason(make_runtime) -> None:
    rt = pending_end(make_runtime)
    done_call(rt, "")
    assert rt.state.held_done == ""


def test_a_held_done_is_saved(make_runtime) -> None:
    rt = pending_end(make_runtime)
    done_call(rt)
    saved = state_mod.load(rt.config.run_dir)
    assert saved.held_done == REASON


# ----- D3: the done lands when the boundary closes --------------------------------------------


def test_release_marks_done_with_the_reason_when_nothing_is_pending() -> None:
    state = RunState(sprint=1, held_done=REASON)
    state.upstream.closed = 1
    state.release_held_done()
    assert state.status is RunStatus.DONE and state.status_reason == REASON
    assert state.held_done is None


def test_release_with_a_boundary_pending_changes_nothing() -> None:
    state = RunState(sprint=1, held_done=REASON)
    state.boundary = bd.Boundary(bd.Edge.END, 1)
    state.release_held_done()
    assert state.status is RunStatus.IDLE and state.held_done == REASON


def test_release_with_nothing_held_changes_nothing() -> None:
    state = RunState(sprint=1)
    state.upstream.closed = 1
    state.release_held_done()
    assert state.status is RunStatus.IDLE and state.held_done is None


def test_release_of_an_empty_reason_has_no_reason() -> None:
    state = RunState(sprint=1, held_done="")
    state.upstream.closed = 1
    state.release_held_done()
    assert state.status is RunStatus.DONE and state.status_reason is None


def test_closing_the_end_boundary_releases_the_held_done(make_runtime) -> None:
    rt = pending_end(make_runtime)
    done_call(rt)
    BoundaryRunner(rt)._close(rt.state.boundary, "reports/r1.md")
    assert rt.state.status is RunStatus.DONE and rt.state.status_reason == REASON
    assert rt.state.held_done is None and rt.state.boundary is None


def test_closing_with_nothing_held_leaves_the_status(make_runtime) -> None:
    rt = pending_end(make_runtime)
    before = rt.state.status
    BoundaryRunner(rt)._close(rt.state.boundary, "")
    assert rt.state.status is before


def test_the_run_ends_done_with_no_next_sprint_hand_over(make_runtime) -> None:
    rt = pending_end(make_runtime)
    done_call(rt)
    assert rt.state.held_done == REASON
    BoundaryRunner(rt)._close(rt.state.boundary, "")
    sched = Scheduler(rt, Start("task"))
    sched.tick()
    assert sched.ended and sched.is_finished
    assert rt.state.keep_going_asks == 0 and rt.state.status is RunStatus.DONE
    sched.finish_run()
    assert rt.state.status is RunStatus.DONE and rt.state.status_reason == REASON


# ----- D4: a re-pin carries it ----------------------------------------------------------------


class FakePin:
    """Records the re-pin marker instead of exec'ing a new runner."""

    def __init__(self) -> None:
        self.markers: list[repin.Marker] = []

    def repin(self, marker: repin.Marker) -> None:
        self.markers.append(marker)


def test_a_repin_round_trip_keeps_the_held_done(make_runtime, monkeypatch) -> None:
    monkeypatch.setattr(repin, "pin_commit", lambda run_dir: "a" * 40)
    rt = pending_end(make_runtime)
    done_call(rt)
    rt.state.repin = "b" * 40
    pin = FakePin()
    cli._repin_or(0, rt, pin)
    assert len(pin.markers) == 1
    assert rt.state.status is RunStatus.IDLE and rt.state.held_done == REASON
    loaded = RunState.from_json(rt.state.to_json())
    assert loaded.held_done == REASON
    rt.state = loaded
    Scheduler(rt, Start("task")).begin()
    assert rt.state.status is RunStatus.RUNNING and rt.state.held_done == REASON
    BoundaryRunner(rt)._close(rt.state.boundary, "")
    assert rt.state.status is RunStatus.DONE and rt.state.status_reason == REASON


def test_an_old_state_loads_without_a_held_done() -> None:
    old = json.loads(RunState().to_json())
    old.pop("held_done", None)
    assert RunState.from_json(json.dumps(old)).held_done is None


# ----- D5: the human's new direction drops it -------------------------------------------------


def start_of(task: str, mode: cli.StartMode) -> Start:
    return Start(task, mode)


@pytest.mark.parametrize("mode", [cli.StartMode.RESUME, cli.StartMode.WORK])
def test_a_start_with_a_task_drops_the_held_done(mode: cli.StartMode) -> None:
    state = RunState(held_done=REASON)
    cli._drop_held_done(state, start_of("new work", mode))
    assert state.held_done is None


@pytest.mark.parametrize("mode", [cli.StartMode.RESUME, cli.StartMode.WORK])
def test_a_start_without_a_task_keeps_the_held_done(mode: cli.StartMode) -> None:
    state = RunState(held_done=REASON)
    cli._drop_held_done(state, start_of("", mode))
    assert state.held_done == REASON


def test_prepared_drops_the_held_done_for_a_task(configured, key_home, fake: FakeSystem) -> None:
    from .test_cli import any_tool, start_args

    any_tool(fake)
    held = RunState(held_done=REASON, sprint=1)
    run_dir = config_mod.load(configured).run_dir
    state_mod.save(run_dir, held)
    args = start_args(configured, key_home, "--resume", "--task", "new")
    assert isinstance(args, argparse.Namespace)
    place = cli.Place(configured, key_home)
    runtime = cli._prepared(args, place, cli.Start("new", cli.StartMode.RESUME), None)
    assert not isinstance(runtime, int) and runtime.state.held_done is None


# ----- D6: the liaison sees it ----------------------------------------------------------------


def test_status_report_shows_the_held_done(configured) -> None:
    config = config_mod.load(configured)
    assert cli.status_report(config)["held_done"] is None
    state_mod.save(config.run_dir, RunState(sprint=1, held_done=REASON))
    assert cli.status_report(config)["held_done"] == REASON


def test_status_shows_done_and_the_reason_after_the_run_ends(make_runtime) -> None:
    rt = pending_end(make_runtime)
    done_call(rt)
    BoundaryRunner(rt)._close(rt.state.boundary, "")
    rt.save()
    report = cli.status_report(rt.config)
    assert report["status"] is RunStatus.DONE
    assert report["status_reason"] == REASON and report["held_done"] is None


# ----- D7: the hand-over says how a run ends on purpose ---------------------------------------


def test_next_sprint_advice_says_how_a_run_ends() -> None:
    advice = sprint_end.NEXT_SPRINT_ADVICE
    assert "--cadence sprint" in advice and "notify done quoting them" in advice
    assert "start a sprint" in advice
    assert "don't notify done or blocked while" not in advice.lower()
