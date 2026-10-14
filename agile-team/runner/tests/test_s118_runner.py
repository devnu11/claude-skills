"""s118: the runner changes that feed the Flow chart (R1-R8) and the fixture.

The page's own behaviour is checked in ``test_s118_page.py`` (static) and the
node-harness tests (e2e).
"""

from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from agile_team import commands, live, rates, stage_log, stages, system, test_tally
from agile_team import config as cfg
from agile_team import state as state_mod
from agile_team.commands import TIMED_OUT, CommandShell, Pump
from agile_team.events import EventLog
from agile_team.gates import StoryState
from agile_team.providers import Billing
from agile_team.salvage import Cause
from agile_team.state import RunState
from claude_agent_sdk import AssistantMessage

from .fake_system import FAKE_REPO, Done, FakeSystem, Hang
from .test_s98_live import WHO, pulse_of
from .test_s102_stage_board import Board, Clock
from .test_snapshot import FIXTURE_TEXT, build, make_config

NAME = stages.Name
PLACE = stages.Place("s1", "implement")


# ----- R3: rates -----


def test_rate_buckets_tokens_by_ten_seconds_from_start() -> None:
    rate = rates.Rate(100.0)
    rate.add(100.0, 10)
    rate.add(130.0, 5)
    rate.add(165.0, 20)
    assert rate.series() == [60.0, 0.0, 0.0, 30.0, 0.0, 0.0, 120.0]


def test_rate_before_start_lands_in_window_zero() -> None:
    rate = rates.Rate(100.0)
    rate.add(90.0, 7)
    assert rate.series() == [42.0]


def test_rate_fills_quiet_windows_with_zero() -> None:
    rate = rates.Rate(0.0)
    rate.add(10.0, 4)
    rate.add(190.0, 9)
    assert rate.series() == [0.0, 24.0] + [0.0] * 17 + [54.0]


def test_rate_with_nothing_is_empty() -> None:
    assert rates.Rate(0.0).series() == []


def test_rate_series_is_rounded_to_one_decimal_through_squeeze() -> None:
    rate = rates.Rate(0.0)
    for at in (0.0, 10.0, 20.0):
        rate.add(at, 1)
    assert rate.series() == [6.0, 6.0, 6.0]
    assert rates.squeeze([0.0, 0.0, 1.0], 2) == [0.0, 0.5]
    assert rates.squeeze([1.0, 1.0, 2.0], 2) == [1.0, 1.5]


def test_rate_points_cap_is_24() -> None:
    assert rates.RATE_POINTS == 24


def test_squeeze_keeps_values_within_the_cap() -> None:
    assert rates.squeeze([1.0, 2.0], 24) == [1.0, 2.0]
    assert rates.squeeze([], 24) == []
    values = [float(i) for i in range(24)]
    assert rates.squeeze(values, 24) == values


def test_squeeze_averages_chunks_above_the_cap() -> None:
    squeezed = rates.squeeze([float(i) for i in range(30)], 24)
    assert len(squeezed) == 24
    assert squeezed[0] == 0.0 and squeezed[-1] == 28.5


def test_a_long_series_is_squeezed_to_the_cap() -> None:
    rate = rates.Rate(0.0)
    for minute in range(60):
        rate.add(minute * 60.0, minute)
    assert len(rate.series()) == rates.RATE_POINTS


# ----- R4: live.Reading carries the rate -----


def usage(tokens: int, uid: str) -> AssistantMessage:
    return AssistantMessage(content=[], model="m", usage={"input_tokens": tokens}, message_id=uid)


def test_a_reading_view_has_the_rate_after_cost() -> None:
    reading = live.Reading(WHO, 1000.0)
    reading.take(usage(60, "a"), 1010.0)
    reading.take(usage(120, "b"), 1075.0)
    view = reading.view()
    assert view["rate"] == [60.0, 120.0]
    keys = list(view)
    assert keys.index("rate") == keys.index("cost_usd") + 1


def test_the_time_split_carries_the_rate() -> None:
    reading = live.Reading(WHO, 1000.0)
    reading.take(usage(30, "a"), 1005.0)
    assert reading.time_split()["rate"] == [30.0]
    assert {"opened_at", "tool_s", "model_s", "waiting_s"} <= set(reading.time_split())


def test_an_interrupted_step_end_carries_the_rate(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(WHO)
    meter.take(usage(50, "a"))
    pulse.close(meter)
    event = meter.interrupted(live.Stop(Cause.ERROR))
    assert event.data["rate"] == [50.0]


def test_a_meter_split_carries_the_rate(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(live.Who("product-owner", None, None, "opus", Billing.REPORTED))
    meter.take(usage(10, "a"))
    pulse.close(meter)
    assert live.time_split(meter)["rate"] == [10.0]
    assert live.time_split(None) == {}


# ----- R5: test_tally (the plugin's records) -----


def rec(session: str = "a", passed: int = 0, warned: int = 0, skipped: int = 0,
        failed: int = 0, total: int | None = 10) -> str:  # fmt: skip
    """One plugin record as the tally file holds it."""
    return json.dumps({"session": session, "total": total, "passed": passed, "warned": warned,
                       "skipped": skipped, "failed": failed})  # fmt: skip


def raw(**over: Any) -> str:
    """A record with fields replaced by (possibly invalid) values; ``None`` drops the field."""
    fields: dict[str, Any] = {
        "session": "a",
        "passed": 1,
        "warned": 0,
        "skipped": 0,
        "failed": 0,
        "total": 5,
    }
    fields.update(over)
    return json.dumps({k: v for k, v in fields.items() if v is not None})


def fold(*texts: str) -> test_tally.Tally:
    tally = test_tally.EMPTY
    for text in texts:
        tally = test_tally.read(tally, text)
    return tally


def test_the_counts_are_the_four_categories() -> None:
    assert test_tally.COUNTS == ("passed", "warned", "skipped", "failed")


def test_a_record_sets_the_counts_the_total_and_one_point() -> None:
    tally = fold(rec(passed=3, warned=1, skipped=1, failed=0, total=10))
    assert (tally.passed, tally.warned, tally.skipped, tally.failed) == (3, 1, 1, 0)
    assert tally.total == 10 and tally.session == "a"
    assert tally.ran() == 5 and tally.counted() and tally.pct() == 50
    assert tally.points == (50,) and tally.fail_at is None


def test_the_same_record_again_adds_no_point() -> None:
    text = rec(passed=5)
    assert fold(text, text).points == (50,)


def test_a_later_record_adds_a_point_and_the_first_failure_is_kept() -> None:
    tally = fold(rec(passed=5), rec(passed=5, failed=1), rec(passed=5, failed=2, total=10))
    assert tally.points == (50, 60, 70)
    assert tally.fail_at == 1
    assert tally.failed == 2


def test_a_failure_in_the_first_record_marks_the_first_point() -> None:
    assert fold(rec(passed=1, failed=1)).fail_at == 0


def test_a_failure_before_any_point_leaves_fail_at_none() -> None:
    tally = fold(rec(failed=1, total=None))
    assert tally.failed == 1 and tally.points == () and tally.fail_at is None


def test_no_failure_leaves_fail_at_none() -> None:
    assert fold(rec(passed=2)).fail_at is None


def test_without_a_total_there_is_no_point_and_no_percentage() -> None:
    tally = fold(rec(passed=4, total=None))
    assert tally.total is None and tally.pct() is None and tally.points == ()


def test_the_percentage_caps_at_100() -> None:
    assert test_tally.Tally(passed=12, total=10).pct() == 100


def test_a_new_session_starts_afresh() -> None:
    old = fold(rec("a", passed=5, failed=1))
    assert old.fail_at == 0
    new = test_tally.read(old, rec("b", passed=1, total=4))
    assert new.session == "b" and new.passed == 1 and new.failed == 0 and new.total == 4
    assert new.points == (25,) and new.fail_at is None


def test_the_same_session_carries_on_after_a_new_one_never_came() -> None:
    assert fold(rec("a", passed=1), rec("a", passed=2)).points == (10, 20)


@pytest.mark.parametrize(
    "text",
    [
        "collected 506 items",
        "..F.s  [ 12%]",
        "",
        "not json {",
        "[1, 2]",
        '"text"',
        raw(failed=None),
        raw(session="a", passed=True, total=5),
        raw(session="a", passed=-1, total=5),
        raw(session="a", passed=1.5, total=5),
        rec(total=0),
        rec(session=""),
        raw(session=7, passed=1, total=5),
        raw(session="a", passed=1, total="5"),
        raw(session="a", passed=1, total=True),
    ],
)  # fmt: skip
def test_what_is_not_a_record_gives_none_and_changes_nothing(text: str) -> None:
    assert test_tally.record_of(text) is None
    before = fold(rec(passed=2))
    assert test_tally.read(before, text) is before


def test_a_record_with_no_total_is_a_record() -> None:
    record = test_tally.record_of(rec(passed=1, total=None))
    assert record is not None and record["total"] is None and record["session"] == "a"


def test_the_empty_tally_is_not_counted() -> None:
    assert test_tally.Tally() == test_tally.EMPTY
    assert not test_tally.EMPTY.counted() and test_tally.EMPTY.ran() == 0
    assert test_tally.EMPTY.pct() is None


def test_as_dict_has_the_heartbeat_keys_in_order() -> None:
    tally = fold(rec(passed=3, warned=1, skipped=2, failed=4, total=20))
    assert list(tally.as_dict()) == [
        "passed", "warned", "skipped", "failed", "total", "points", "fail_at",
    ]  # fmt: skip
    assert tally.as_dict() == {
        "passed": 3, "warned": 1, "skipped": 2, "failed": 4, "total": 20,
        "points": [50], "fail_at": 0,
    }  # fmt: skip


def test_the_old_progress_machinery_is_gone() -> None:
    for name in ("OUTCOMES", "TOTALS", "PROGRESS", "MAX_POINTS"):
        assert not hasattr(test_tally, name)
    assert "pct" not in test_tally.EMPTY.as_dict()


def test_points_have_no_cap() -> None:
    tally = test_tally.EMPTY
    for i in range(1, 101):
        tally = test_tally.read(tally, rec(passed=i, failed=1, total=100))
    # one point per whole percent, 2..100
    assert len(tally.points) == 99 and tally.points[-1] == 100
    assert tally.fail_at == 0


# ----- R6: stages.current, Run.hear -----


def test_current_is_the_innermost_open_run() -> None:
    assert stages.current() is None
    with stages.opened(NAME.GATE_GREEN, PLACE) as outer:
        assert stages.current() is outer
        with stages.opened(NAME.GATE_DISPUTE, PLACE) as inner:
            assert stages.current() is inner
        assert stages.current() is outer
    assert stages.current() is None


def test_hear_calls_every_listener_in_order() -> None:
    run = stages.Run(stages.STAGES[NAME.GATE_GREEN], PLACE)
    heard: list[str] = []
    run.listeners.append(lambda line: heard.append("a:" + line))
    run.listeners.append(lambda line: heard.append("b:" + line))
    run.hear("x")
    assert heard == ["a:x", "b:x"]


def test_a_run_starts_with_no_listeners() -> None:
    first = stages.Run(stages.STAGES[NAME.GATE_GREEN], PLACE)
    second = stages.Run(stages.STAGES[NAME.GATE_GREEN], PLACE)
    first.hear("nobody listens")
    assert first.listeners == [] and first.listeners is not second.listeners


# ----- R7: stage_log -----


class RefreshBoard(Board):
    """A Board that counts refreshes."""

    def __init__(self, log: EventLog | None = None) -> None:
        super().__init__(log)
        self.refreshed = 0

    def refresh(self) -> None:
        self.refreshed += 1


def make_row() -> dict[str, Any]:
    run = stages.Run(stages.STAGES[NAME.GATE_TESTS_COVERAGE], PLACE)
    return stage_log.open_row(run, Clock().mark())


def test_open_row_ends_with_tests_none() -> None:
    row = make_row()
    assert list(row)[-1] == "tests" and row["tests"] is None
    assert list(row)[:-1] == [
        "stage", "when", "attach", "description", "story", "step",
        "started_at", "started_mono", "started_slept",
    ]  # fmt: skip


def test_a_record_fills_the_row_and_refreshes_the_board(fake: FakeSystem) -> None:
    row, board = make_row(), RefreshBoard()
    hear = stage_log.Tallier(row, board)
    hear("not a record")
    assert row["tests"] is None and board.refreshed == 0
    hear(rec(passed=3, failed=1, total=10))
    assert row["tests"]["passed"] == 3 and row["tests"]["failed"] == 1
    assert row["tests"]["total"] == 10 and row["tests"]["skipped"] == 0
    assert board.refreshed == 1


def test_a_record_of_nothing_leaves_none(fake: FakeSystem) -> None:
    row, board = make_row(), RefreshBoard()
    stage_log.Tallier(row, board)(rec(total=10))
    assert row["tests"] is None and board.refreshed == 0


def test_a_new_dict_is_set_each_time(fake: FakeSystem) -> None:
    row = make_row()
    hear = stage_log.Tallier(row, RefreshBoard())
    hear(rec(passed=2))
    first = row["tests"]
    hear(rec(passed=5))
    assert row["tests"] is not first and first["passed"] == 2 and row["tests"]["passed"] == 5


def test_refreshes_are_spaced_by_two_seconds(fake: FakeSystem) -> None:
    assert stage_log.TALLY_REFRESH_S == 2.0
    row, board = make_row(), RefreshBoard()
    hear = stage_log.Tallier(row, board)
    hear(rec(passed=1))
    fake.clock += 1.0
    hear(rec(passed=2))
    assert board.refreshed == 1 and row["tests"]["passed"] == 2
    fake.clock += 1.0
    hear(rec(passed=3))
    assert board.refreshed == 2


def test_a_second_session_replaces_the_first_in_the_row(fake: FakeSystem) -> None:
    row = make_row()
    hear = stage_log.Tallier(row, RefreshBoard())
    hear(rec("a", passed=9, failed=1))
    hear(rec("b", passed=1, total=4))
    assert (
        row["tests"]["passed"] == 1 and row["tests"]["failed"] == 0 and row["tests"]["total"] == 4
    )


def test_a_lint_line_leaves_tests_none(fake: FakeSystem) -> None:
    row, board = make_row(), RefreshBoard()
    stage_log.Tallier(row, board)("All checks passed!")
    assert row["tests"] is None and board.refreshed == 0


def test_hidden_refresh_does_nothing() -> None:
    assert stage_log.HIDDEN.refresh() is None


def test_pulse_refresh_writes_the_heartbeat(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    writes: list[int] = []
    pulse.write = lambda: writes.append(1)  # type: ignore[method-assign]
    pulse.refresh()
    assert writes == [1]


def test_an_open_stage_listens_and_the_event_is_unchanged(scratch: Path, fake: FakeSystem) -> None:
    board = RefreshBoard()
    log = stage_log.StageLog(EventLog(scratch / "ev.jsonl"), Clock(), board=board)
    with log.open(NAME.GATE_TESTS_COVERAGE) as run:
        run.hear(rec(passed=2, total=4))
        (row,) = board.rows
        assert row["tests"]["passed"] == 2 and row["tests"]["total"] == 4
    (event,) = [e for e in log.log.events() if e.kind == "runner-stage"]
    assert list(event.data) == [
        "stage", "when", "attach", "step", "detail", "code", "raised",
        "started_at", "started_mono", "started_slept", "seconds",
    ]  # fmt: skip


# ----- R8: Pump and CommandShell -----


def test_a_pump_keeps_every_line_in_order() -> None:
    pump = Pump(iter(["one\n", "two\n"]))
    pump.start()
    assert pump.join(2.0) is True
    assert pump.text() == "one\ntwo\n"


def test_a_pump_has_no_run_and_never_tells_the_stage() -> None:
    assert [f.name for f in dataclasses.fields(Pump)][:2] == ["lines", "seen"]
    assert not hasattr(Pump, "_tell")
    with stages.opened(NAME.GATE_TESTS_COVERAGE, PLACE) as run:
        heard: list[str] = []
        run.listeners.append(heard.append)
        pump = Pump(iter(["a\n"]))
        pump.start()
        assert pump.join(2.0)
    assert heard == []


@pytest.mark.parametrize("error", [ValueError("closed"), OSError("pipe")])
def test_a_pipe_closed_under_the_thread_ends_the_output(error: Exception) -> None:
    def lines() -> Iterator[str]:
        yield "kept\n"
        raise error

    pump = Pump(lines())
    pump.start()
    assert pump.join(2.0) and pump.text() == "kept\n"


def test_a_pump_that_never_ends_reports_false() -> None:
    release = threading.Event()

    def lines() -> Iterator[str]:
        yield "a\n"
        release.wait(5)  # a hard bound so a mistake cannot hang the suite

    pump = Pump(lines())
    pump.start()
    try:
        assert pump.join(0.05) is False
        assert pump.text() == "a\n"
    finally:
        release.set()


def test_the_result_is_what_communicate_gave(fake: FakeSystem) -> None:
    fake.reply(("echo",), Done(3, "a\nb\nc\n"))
    assert CommandShell(FAKE_REPO).run("echo a; echo b; echo c") == (3, "a\nb\nc\n")


def test_a_command_outside_a_stage_still_runs(fake: FakeSystem) -> None:
    fake.reply(("ls",), Done(0, "x\n"))
    assert CommandShell(FAKE_REPO).run("ls") == (0, "x\n")


def test_a_timeout_still_kills_and_names_the_hung_test(fake: FakeSystem) -> None:
    line = '  File "/x/tests/test_a.py", line 12 in test_hangs\n'
    fake.reply(("sleep",), Hang(line))
    code, out = CommandShell(FAKE_REPO, 0.3).run("sleep 30")
    assert code == TIMED_OUT
    assert out.splitlines()[-1].endswith("/x/tests/test_a.py::test_hangs (line 12)")
    assert any(kind == "killpg" for kind, _, _ in fake.signals)


def test_output_that_never_closes_counts_as_a_timeout(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()

    class Open:
        pid = 4242
        returncode = 0

        @property
        def stdout(self) -> Iterator[str]:
            yield "tail\n"
            release.wait(5)  # a hard bound so a mistake cannot hang the suite

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def __enter__(self) -> Open:
            return self

        def __exit__(self, *exc: object) -> None:
            release.set()

    monkeypatch.setattr(system, "spawn_piped", lambda _command: Open())
    monkeypatch.setattr(commands, "kill_group", lambda _proc: None)
    monkeypatch.setattr(commands, "DRAIN_S", 0.05)
    code, out = CommandShell(FAKE_REPO, 0.05).run("cmd")
    assert code == TIMED_OUT and out.splitlines()[0] == "tail"


def test_drain_is_gone() -> None:
    assert not hasattr(commands, "drain")


# ----- R2: snapshot step_roles; R1: step-start step; fixture -----


@pytest.fixture
def config(scratch: Path) -> cfg.Config:
    return make_config(scratch / "repo", ["design", "tests", "implement", "nonsense"])


def test_step_roles_follows_the_pipeline(config: cfg.Config, scratch: Path) -> None:
    snap = build(config, scratch)
    assert list(snap["step_roles"]) == snap["pipeline"]
    assert snap["step_roles"]["design"] == ["architect"]
    assert snap["step_roles"]["tests"] == ["unit-tester"]
    assert snap["step_roles"]["implement"] == ["developer"]
    assert snap["step_roles"]["nonsense"] == []


def test_step_roles_lists_assigned_developers_sorted(config: cfg.Config, scratch: Path) -> None:
    one = StoryState("s1", "t", "implement")
    one.developer = "developer-db"
    two = StoryState("s2", "t", "implement")
    two.po_developer = "developer-cli"
    state_mod.save(config.run_dir, RunState(stories={"s1": one, "s2": two}))
    roles = build(config, scratch)["step_roles"]["implement"]
    assert roles == ["developer-cli", "developer-db"]


def test_step_roles_comes_right_after_pipeline(config: cfg.Config, scratch: Path) -> None:
    keys = list(build(config, scratch))
    assert keys.index("step_roles") == keys.index("pipeline") + 1


FIXTURE = json.loads(FIXTURE_TEXT)


def test_the_fixture_carries_step_roles_after_pipeline() -> None:
    keys = list(FIXTURE)
    assert keys.index("step_roles") == keys.index("pipeline") + 1
    assert list(FIXTURE["step_roles"]) == FIXTURE["pipeline"]
    assert all(isinstance(v, list) for v in FIXTURE["step_roles"].values())


def test_the_fixture_has_a_step_start_with_a_step_and_rates() -> None:
    starts = [e for e in FIXTURE["events"] if e["kind"] == "step-start"]
    assert any(e["data"].get("step") for e in starts)
    ends = [e for e in FIXTURE["events"] if e["kind"] in ("step-end", "po-turn")]
    assert any(len(e["data"].get("rate", [])) >= 2 for e in ends)
    assert any(e["kind"] == "step-end" and "rate" not in e["data"] for e in ends)


def test_the_fixture_has_a_bounce_gate_and_a_running_test_stage() -> None:
    assert any(
        e["kind"] == "gate" and e["data"].get("verdict") == "bounce" for e in FIXTURE["events"]
    )
    beat = FIXTURE["heartbeat"]
    assert len(beat["step"]["rate"]) >= 2
    rows = beat["stages"]
    (row,) = [r for r in rows if r["stage"] == "gate.tests+coverage"]
    assert list(row)[-1] == "tests"
    assert row["tests"]["total"] == 506 and row["tests"]["fail_at"] == 4
    assert len(row["tests"]["points"]) >= 2 and row["description"]
