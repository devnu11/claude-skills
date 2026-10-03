"""Cost ledger and budget checkpoints."""

from pathlib import Path

from agile_team.ledger import Entry, Ledger, budget_status, checkpoint_crossed


def test_record_and_totals(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "run" / "ledger.jsonl")
    assert led.total() == 0
    led.record(Entry("developer", "sonnet", 1.5, "s1"))
    led.record(Entry("developer", "sonnet", 0.5))
    led.record(Entry("architect", "opus", 2.0, at=5.0))
    assert led.total() == 4.0
    assert led.by_role() == {"developer": 2.0, "architect": 2.0}
    assert led.entries()[2].at == 5.0
    status = budget_status(led, 8.0)
    assert status["pct_used"] == 50.0
    assert status["remaining_usd"] == 4.0
    assert list(status["by_role"]) == ["architect", "developer"]


def test_budget_status_zero_budget(tmp_path: Path) -> None:
    assert budget_status(Ledger(tmp_path / "l"), 0)["pct_used"] == 0.0


def test_checkpoint_crossed() -> None:
    assert checkpoint_crossed(2.4, 2.6, 10, 25)
    assert not checkpoint_crossed(2.6, 4.9, 10, 25)
    assert checkpoint_crossed(4.9, 10.1, 10, 25)
    assert not checkpoint_crossed(0, 5, 0, 25)
