"""s102: open stage runs are listed in the heartbeat (HB1-HB4) and the fixture carries them."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from agile_team import live, stage_log, stages
from agile_team.dashboard.step_times import Mark, Platform
from agile_team.events import EventKind, EventLog

from .clock import about
from .fake_system import FakeSystem
from .test_s98_live import WHO, pulse_of
from .test_snapshot import FIXTURE_TEXT

NAME = stages.Name
ROW_KEYS = [
    "stage",
    "when",
    "attach",
    "description",
    "story",
    "step",
    "attempt",
    "started_at",
    "started_mono",
    "started_slept",
    "tests",
]


class Clock:
    """A Marker handing out the same mark."""

    platform = Platform.POSIX

    def mark(self) -> Mark:
        return Mark(5.0, 7.0, 1.5)


class Board:
    """A recording StageBoard: what was listed, and what was listed at each moment."""

    def __init__(self, log: EventLog | None = None) -> None:
        self.rows: list[dict[str, Any]] = []
        self.seen: list[list[dict[str, Any]]] = []
        self.events_when_removed: list[int] = []
        self.log = log

    @contextmanager
    def showing(self, row: dict[str, Any]):  # type: ignore[no-untyped-def]
        self.rows.append(row)
        self.seen.append(list(self.rows))
        try:
            yield
        finally:
            self.rows.remove(row)
            if self.log is not None:
                self.events_when_removed.append(len(list(self.log.events())))


def make(repo: Path, board: Board | None = None) -> stage_log.StageLog:
    log = EventLog(repo / "ev.jsonl")
    if board is None:
        return stage_log.StageLog(log, Clock())
    return stage_log.StageLog(log, Clock(), board=board)


# ----- stage_log: open_row, board (HB1, HB2, HB4) -----


def test_open_row_has_hb2_keys_in_order() -> None:
    run = stages.Run(stages.STAGES[NAME.GATE_GREEN], stages.Place("s1", "implement"))
    row = stage_log.open_row(run, Mark(5.0, 7.0, 1.5))
    assert list(row) == ROW_KEYS
    assert row["stage"] == "gate.green"
    assert (row["story"], row["step"]) == ("s1", "implement")
    assert (row["started_at"], row["started_mono"], row["started_slept"]) == (5.0, 7.0, 1.5)
    assert row["when"] == str(run.stage.when) and row["attach"] == str(run.stage.attach)


def test_open_row_values_equal_the_closing_events_data(repo: Path) -> None:
    board = Board()
    log = make(repo, board)
    with log.within(stages.Place("s1", "implement")), log.open(NAME.GATE_GREEN):
        (row,) = board.rows
    (event,) = [e for e in log.log.events() if e.kind == EventKind.RUNNER_STAGE]
    for key in ("stage", "when", "attach", "step", "started_at", "started_mono", "started_slept"):
        assert row[key] == event.data[key]
    assert row["story"] == event.story


def test_the_row_is_listed_inside_the_block_and_gone_after(repo: Path) -> None:
    board = Board()
    log = make(repo, board)
    with log.open(NAME.GATE_GREEN):
        assert len(board.rows) == 1 and list(board.rows[0]) == ROW_KEYS
    assert board.rows == []


def test_the_row_is_gone_when_the_block_raises(repo: Path) -> None:
    board = Board()
    log = make(repo, board)
    with pytest.raises(ValueError), log.open(NAME.GATE_GREEN):
        raise ValueError("boom")
    assert board.rows == [] and len(board.seen) == 1


def test_the_row_is_removed_before_the_event_is_written(repo: Path) -> None:
    board = Board()
    log = make(repo, board)
    board.log = log.log
    with log.open(NAME.GATE_GREEN):
        pass
    assert board.events_when_removed == [0]
    assert len(list(log.log.events())) == 1


def test_nested_stages_list_outer_first(repo: Path) -> None:
    board = Board()
    log = make(repo, board)
    with log.open(NAME.GATE_GREEN), log.open(NAME.QUALITY_LINT):
        pass
    assert [r["stage"] for r in board.seen[-1]] == ["gate.green", "quality.lint"]


def test_a_log_without_a_board_uses_hidden(repo: Path) -> None:
    log = make(repo)
    assert log.board is stage_log.HIDDEN
    with log.open(NAME.GATE_GREEN) as run:
        assert run.stage.name == NAME.GATE_GREEN
    assert len(list(log.log.events())) == 1


def test_hidden_lists_nothing() -> None:
    with stage_log.HIDDEN.showing({"stage": "x"}) as shown:
        assert shown is None


# ----- live: Pulse.showing, heartbeat stages (HB3) -----


def written(fake: FakeSystem) -> dict[str, Any]:
    return json.loads(fake.read_text(Path("/fake/run") / live.HEARTBEAT))


def test_the_pulse_is_a_stage_board() -> None:
    assert callable(live.Pulse.showing)


def test_heartbeat_stages_follow_calls_and_start_empty(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    beat = pulse.heartbeat()
    keys = list(beat)
    assert beat["stages"] == []
    assert keys.index("stages") == keys.index("calls") + 1


def test_showing_lists_the_row_then_drops_it(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    row = {"stage": "gate.green"}
    with pulse.showing(row):
        assert pulse.heartbeat()["stages"] == [row]
    assert pulse.heartbeat()["stages"] == []


def test_nested_rows_are_outer_first_and_inner_goes_first(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    outer, inner = {"stage": "a"}, {"stage": "b"}
    with pulse.showing(outer), pulse.showing(inner):
        assert pulse.heartbeat()["stages"] == [outer, inner]
    assert pulse.heartbeat()["stages"] == []


def test_equal_rows_are_dropped_by_identity(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    first, second = {"stage": "a"}, {"stage": "a"}
    with pulse.showing(first):
        with pulse.showing(second):
            pass
        (left,) = pulse.heartbeat()["stages"]
        assert left is first


def test_a_row_is_dropped_when_the_block_raises(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    with pytest.raises(ValueError), pulse.showing({"stage": "a"}):
        raise ValueError("boom")
    assert pulse.heartbeat()["stages"] == []


def test_stages_are_empty_after_end(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    with pulse.showing({"stage": "a"}):
        pulse.end()
        assert pulse.heartbeat()["stages"] == []


def test_each_enter_and_exit_writes_the_heartbeat(fake: FakeSystem) -> None:
    fake.make_dirs(Path("/fake/run"))
    pulse = live.Pulse(Path("/fake/run"), 20.0)
    with pulse.showing({"stage": "a"}):
        assert written(fake)["stages"] == [{"stage": "a"}]
    assert written(fake)["stages"] == []


def test_a_stage_log_on_a_pulse_lists_its_open_row(fake: FakeSystem, repo: Path) -> None:
    pulse = pulse_of(fake)
    log = stage_log.StageLog(EventLog(repo / "ev.jsonl"), pulse, board=pulse)
    with log.open(NAME.GATE_GREEN):
        (row,) = pulse.heartbeat()["stages"]
        assert list(row) == ROW_KEYS and row["stage"] == "gate.green"
    assert pulse.heartbeat()["stages"] == []


def test_the_heartbeat_version_is_3() -> None:
    assert live.HEARTBEAT_VERSION == 3


def test_open_meters_do_not_show_in_stages(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    pulse.open(WHO)
    assert pulse.heartbeat()["stages"] == []


# ----- dispatch wiring (HB4) -----


def test_the_runtime_passes_its_pulse_as_the_board(make_runtime: Any) -> None:
    rt = make_runtime()
    assert rt.stage_log.board is rt.pulse


# ----- the fixture contract -----


def test_the_fixture_heartbeat_keys_equal_the_pulses(fake: FakeSystem) -> None:
    fixture = json.loads(FIXTURE_TEXT)
    assert list(fixture["heartbeat"]) == list(pulse_of(fake).heartbeat())
    assert [r["stage"] for r in fixture["heartbeat"]["stages"]] == ["gate.tests+coverage"]


def stage_events() -> list[dict[str, Any]]:
    return [e for e in json.loads(FIXTURE_TEXT)["events"] if e["kind"] == "runner-stage"]


def test_the_fixture_has_the_two_new_runner_stage_events() -> None:
    by_id = {e["id"]: e for e in stage_events()}
    rs4, rs5 = by_id["rs4"], by_id["rs5"]
    assert rs4["story"] == rs5["story"] == "s1"
    assert rs4["data"] == {
        "stage": "presentation.trial",
        "when": "after",
        "attach": "step",
        "step": "e2e",
        "attempt": None,
        "detail": None,
        "code": 0,
        "raised": None,
        "started_at": 1791457800.0,
        "started_mono": None,
        "started_slept": 0.0,
        "seconds": about(30.0),
    }
    assert rs5["data"]["stage"] == "env.prepare"
    assert (rs5["data"]["step"], rs5["data"]["when"]) == ("acceptance", "before")
    assert (rs5["data"]["started_at"], rs5["data"]["seconds"]) == (1791458000.0, about(45.0))


def test_the_new_events_sit_in_at_order() -> None:
    events = json.loads(FIXTURE_TEXT)["events"]
    ids = [e["id"] for e in events]
    order = ["e34", "rs4", "e35", "rs5", "e36"]
    positions = [ids.index(i) for i in order]
    assert positions == sorted(positions)
    ats = [e["at"] for e in events]
    assert ats == sorted(ats)


def test_the_fixture_has_eight_runner_stage_runs_in_total() -> None:
    assert len(stage_events()) == 8
