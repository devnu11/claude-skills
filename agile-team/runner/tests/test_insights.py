"""The Manager's spend and friction views."""

from pathlib import Path

from agile_team.events import Event, EventKind
from agile_team.insights import friction_since_review, spend_by_role
from agile_team.ledger import Entry, Ledger, Tokens


def test_spend_by_role_sorted_with_per_step_figures(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "ledger.jsonl")
    led.record(Entry("quality-czar", "haiku", 0.2, tokens=Tokens(1, 1, 98), turns=20))
    led.record(Entry("architect", "opus", 1.5, tokens=Tokens(10, 10), turns=12))
    led.record(Entry("architect", "opus", 0.5, turns=8))
    view = spend_by_role(led)
    assert list(view) == ["architect", "quality-czar"]
    assert view["architect"] == {
        "steps": 2,
        "cost_usd": 2.0,
        "cost_per_step": 1.0,
        "tokens": 20,
        "turns_per_step": 10.0,
    }
    assert view["quality-czar"]["tokens"] == 100


def step_end(role: str, friction: str = "") -> Event:
    return Event(EventKind.STEP_END, role, "s1", {"friction": friction})


def test_friction_only_since_the_last_manager_step() -> None:
    events = [
        step_end("developer", "old note"),
        step_end("manager"),
        step_end("developer", "tests take 3 minutes"),
        step_end("architect"),
        Event(EventKind.GATE, None, "s1", {}),
    ]
    assert friction_since_review(events) == [
        {"role": "developer", "story": "s1", "friction": "tests take 3 minutes"}
    ]
    assert friction_since_review(events[:1])[0]["friction"] == "old note"
