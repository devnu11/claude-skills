"""Awake time of steps from the two clocks (s97, AW3-AW9)."""

from __future__ import annotations

from typing import Any

import pytest
from agile_team.dashboard import step_times
from agile_team.dashboard.step_times import Mark, Platform, Stopwatch

POSIX = Stopwatch(Platform.POSIX)
WINDOWS = Stopwatch(Platform.WINDOWS)


def ev(kind: str, at: float, **data: Any) -> dict:
    return {
        "id": f"e{at}",
        "at": at,
        "kind": kind,
        "role": "architect",
        "story": "s1",
        "data": data,
    }


def pair(start_data: dict, end_data: dict, at: tuple[float, float] = (100.0, 400.0)) -> list[dict]:
    return [
        ev("step-start", at[0], **start_data),
        ev("step-end", at[1], status="done", **end_data),
    ]


def one(events: list[dict], watch: Stopwatch = POSIX) -> step_times.Span:
    [span] = step_times.spans(events, watch)
    return span


def test_posix_counts_only_the_monotonic_span() -> None:
    span = one(pair({"mono": 1000.0, "slept": 0.0}, {"mono": 1100.0, "slept": 200.0}))
    assert (span.seconds, span.clock, span.slept) == (100.0, "awake", 200.0)


def test_windows_takes_the_counted_sleep_off_the_wall_span() -> None:
    events = pair({"mono": 0.0, "slept": 30.0}, {"mono": 300.0, "slept": 230.0})
    span = one(events, WINDOWS)
    assert (span.seconds, span.clock, span.slept) == (100.0, "awake", 200.0)


def test_windows_with_mono_only_falls_back_to_wall() -> None:
    span = one(pair({"mono": 1000.0}, {"mono": 1100.0}), WINDOWS)
    assert (span.seconds, span.clock, span.slept) == (300.0, "wall", 0.0)


@pytest.mark.parametrize("watch", [POSIX, WINDOWS])
def test_events_without_clocks_time_by_wall(watch: Stopwatch) -> None:
    span = one(pair({}, {}), watch)
    assert (span.seconds, span.clock, span.slept) == (300.0, "wall", 0.0)


def test_the_default_watch_times_by_wall() -> None:
    [span] = step_times.spans(pair({}, {}))
    assert (span.seconds, span.clock) == (300.0, "wall")


def test_a_monotonic_clock_that_went_back_falls_back_to_wall() -> None:
    span = one(pair({"mono": 5000.0}, {"mono": 10.0}))
    assert (span.seconds, span.clock, span.slept) == (300.0, "wall", 0.0)


def test_a_sleep_counter_that_went_back_falls_back_to_wall_on_windows() -> None:
    span = one(pair({"slept": 90.0}, {"slept": 5.0}), WINDOWS)
    assert (span.seconds, span.clock, span.slept) == (300.0, "wall", 0.0)


@pytest.mark.parametrize("bad", [True, "1000", None, [1]])
def test_a_bool_or_other_non_number_mono_counts_as_missing(bad: Any) -> None:
    span = one(pair({"mono": bad}, {"mono": 1100.0}))
    assert (span.clock, span.seconds) == ("wall", 300.0)


def test_number_accepts_int_and_float_only() -> None:
    assert step_times.number(3) == 3 and step_times.number(2.5) == 2.5
    assert step_times.number(True) is None
    assert step_times.number("3") is None and step_times.number(None) is None


def test_mark_reads_at_mono_and_slept() -> None:
    event = ev("step-start", 7.0, mono=1.5, slept="x")
    assert Mark.of(event) == Mark(7.0, 1.5, None)


def test_a_killed_step_is_untimed() -> None:
    events = pair({"mono": 1.0}, {"cause": "killed", "status": "interrupted"})
    span = one(events)
    assert (span.seconds, span.clock, span.slept) == (None, None, None)
    assert span.ended_at == 400.0


def test_a_running_step_gets_clock_and_slept_so_far() -> None:
    watch = Stopwatch(Platform.POSIX, Mark(700.0, 1300.0, None))
    span = one([ev("step-start", 100.0, mono=1000.0)], watch)
    assert (span.seconds, span.clock, span.slept) == (None, "awake", 300.0)


def test_a_running_step_on_windows_uses_the_heartbeat_counter() -> None:
    watch = Stopwatch(Platform.WINDOWS, Mark(700.0, None, 250.0))
    span = one([ev("step-start", 100.0, slept=50.0)], watch)
    assert (span.seconds, span.clock, span.slept) == (None, "awake", 200.0)


def test_a_running_step_without_clocks_is_wall() -> None:
    watch = Stopwatch(Platform.POSIX, Mark(700.0, 1300.0, None))
    span = one([ev("step-start", 100.0)], watch)
    assert (span.clock, span.slept) == ("wall", 0.0)


def test_platform_of_names() -> None:
    assert step_times.platform_of("win32") is Platform.WINDOWS
    for name in ("darwin", "linux", "cygwin"):
        assert step_times.platform_of(name) is Platform.POSIX


def test_awake_has_exactly_the_two_platforms() -> None:
    assert set(step_times.AWAKE) == {Platform.POSIX, Platform.WINDOWS}


def test_as_dict_carries_clock_and_slept_after_seconds() -> None:
    keys = list(one(pair({}, {})).as_dict())
    assert keys[keys.index("seconds") + 1 :][:2] == ["clock", "slept"]
