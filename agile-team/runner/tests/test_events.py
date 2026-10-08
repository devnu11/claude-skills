"""Activity log."""

from pathlib import Path

from agile_team.events import Event, EventKind, EventLog


def kinds(log: EventLog) -> list[str]:
    return [e.kind for e in log.events()]


def test_emit_numbers_and_round_trips(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "run" / "events.jsonl")
    assert log.events() == []
    first = log.emit(Event(EventKind.GATE, None, "s1", {"verdict": "pass"}))
    assert first.id == "e1" and first.at > 0
    log.emit(Event(EventKind.STEP_START, "architect", at=5.0))
    reread = EventLog(log.path)
    assert reread.emit(Event(EventKind.RULING)).id == "e3"
    events = reread.events()
    assert [e.id for e in events] == ["e1", "e2", "e3"]
    assert events[0].kind is EventKind.GATE and events[0].data == {"verdict": "pass"}
    assert events[1].at == 5.0
