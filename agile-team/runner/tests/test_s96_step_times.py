"""Step wall time paired from the event log (s96, ST1-ST8)."""

from __future__ import annotations

from typing import Any

from agile_team.dashboard import step_times


def ev(
    kind: str, at: float, role: str | None = None, story: str | None = None, **data: Any
) -> dict:
    """One event row as events.jsonl holds it."""
    return {"id": f"e{at}", "at": at, "kind": kind, "role": role, "story": story, "data": data}


def start(at: float, role: str = "architect", story: str | None = "s1") -> dict:
    return ev("step-start", at, role, story)


def end(at: float, role: str = "architect", story: str | None = "s1", **data: Any) -> dict:
    return ev("step-end", at, role, story, **{"status": "done", **data})


def test_a_pair_gives_rounded_seconds_status_model_and_start_time() -> None:
    [span] = step_times.spans([start(100.0), end(303.76, model="opus")])
    assert span.as_dict() == {
        "role": "architect",
        "story": "s1",
        "model": "opus",
        "sprint": None,
        "at": 100.0,
        "ended_at": 303.76,
        "seconds": 203.8,
        "status": "done",
    }


def test_pairs_match_by_role_and_story() -> None:
    events = [
        start(10.0, "architect"),
        start(11.0, "unit-tester"),
        end(20.0, "architect"),
        end(41.0, "unit-tester"),
    ]
    got = {s.role: s.seconds for s in step_times.spans(events)}
    assert got == {"architect": 10.0, "unit-tester": 30.0}


def test_pairs_match_by_story_too() -> None:
    events = [start(10.0, story="s1"), start(12.0, story="s2"), end(20.0, story="s2")]
    first, second = step_times.spans(events)
    assert (first.story, first.seconds, first.ended_at) == ("s1", None, None)
    assert (second.story, second.seconds) == ("s2", 8.0)


def test_a_storyless_step_pairs() -> None:
    [span] = step_times.spans([start(1.0, "manager", None), end(5.0, "manager", None)])
    assert (span.story, span.seconds) == (None, 4.0)


def test_an_open_start_is_running() -> None:
    [span] = step_times.spans([start(7.0)])
    assert span.at == 7.0
    assert span.ended_at is None and span.seconds is None and span.status is None


def test_a_killed_end_has_no_time_but_is_finished() -> None:
    [span] = step_times.spans([start(10.0), end(5000.0, status="interrupted", cause="killed")])
    assert span.seconds is None
    assert span.ended_at == 5000.0
    assert span.status == "interrupted"


def test_a_halt_interrupted_end_keeps_its_time() -> None:
    [span] = step_times.spans([start(10.0), end(40.0, status="interrupted", cause="halt")])
    assert span.seconds == 30.0 and span.status == "interrupted"


def test_a_second_start_drops_the_first() -> None:
    events = [start(10.0), start(20.0), end(25.0)]
    [span] = step_times.spans(events)
    assert (span.at, span.seconds) == (20.0, 5.0)


def test_an_end_with_no_open_start_is_ignored() -> None:
    assert step_times.spans([end(5.0)]) == []


def test_a_second_end_is_ignored() -> None:
    [span] = step_times.spans([start(1.0), end(3.0), end(9.0)])
    assert span.seconds == 2.0


def test_sprint_is_the_last_sprint_start_before_the_step() -> None:
    events = [
        start(1.0),
        end(2.0),
        ev("sprint-start", 3.0, sprint=1),
        start(4.0),
        end(5.0),
        ev("sprint-start", 6.0, sprint=2),
        start(7.0),
    ]
    assert [s.sprint for s in step_times.spans(events)] == [None, 1, 2]


def test_an_end_before_its_start_gives_zero() -> None:
    [span] = step_times.spans([start(50.0), end(40.0)])
    assert span.seconds == 0


def test_other_kinds_are_skipped_and_result_is_in_start_order() -> None:
    events = [
        ev("gate", 1.0),
        start(2.0, "a"),
        ev("message", 3.0),
        start(4.0, "b"),
        end(5.0, "b"),
        end(6.0, "a"),
    ]
    assert [s.role for s in step_times.spans(events)] == ["a", "b"]


def test_a_missing_data_key_is_tolerated() -> None:
    bare_end = {"id": "x", "at": 9.0, "kind": "step-end", "role": "architect", "story": "s1"}
    bare_start = {"id": "y", "at": 4.0, "kind": "step-start", "role": "architect", "story": "s1"}
    [span] = step_times.spans([bare_start, bare_end])
    assert span.seconds == 5.0 and span.model is None


def test_no_events_no_steps() -> None:
    assert step_times.spans([]) == []
