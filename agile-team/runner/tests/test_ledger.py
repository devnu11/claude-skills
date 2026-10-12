"""Cost ledger and budget checkpoints."""

import json

from agile_team import system
from agile_team.ledger import Budget, Entry, Ledger, Tokens, budget_status

from .fake_system import FAKE_REPO


def test_record_and_totals() -> None:
    led = Ledger(FAKE_REPO / "run" / "ledger.jsonl")
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


def test_budget_status_zero_budget() -> None:
    assert budget_status(Ledger(FAKE_REPO / "l"), 0)["pct_used"] == 0.0


def test_checkpoint_crossed() -> None:
    budget = Budget(10, 25)
    assert budget.checkpoint_crossed(2.4, 2.6)
    assert not budget.checkpoint_crossed(2.6, 4.9)
    assert budget.checkpoint_crossed(4.9, 10.1)
    assert not Budget(0, 25).checkpoint_crossed(0, 5)


def test_tokens_from_usage_and_sum() -> None:
    usage = {"input_tokens": 3, "output_tokens": 2, "cache_read_input_tokens": None}
    tokens = Tokens.from_usage(usage) + Tokens(1, 1, 1, 1)
    assert tokens == Tokens(4, 3, 1, 1)
    assert tokens.total() == 9
    assert Tokens.from_usage(None) == Tokens()


def test_old_lines_without_tokens_still_load() -> None:
    path = FAKE_REPO / "ledger.jsonl"
    system.write_text(
        path, json.dumps({"role": "scribe", "model": "haiku", "cost_usd": 0.1}) + "\n"
    )
    assert Ledger(path).entries()[0].tokens == Tokens()


def test_totals_group_cost_tokens_and_steps() -> None:
    led = Ledger(FAKE_REPO / "ledger.jsonl")
    led.record(Entry("developer", "sonnet", 1.0, "s1", tokens=Tokens(10, 5)))
    led.record(Entry("developer", "sonnet", 0.5, "s2", tokens=Tokens(1, 1)))
    by_role = led.totals("role")["developer"]
    assert (by_role.cost_usd, by_role.tokens, by_role.steps) == (1.5, Tokens(11, 6), 2)
    assert set(led.totals("story")) == {"s1", "s2"}
    assert budget_status(led, 10)["tokens"] == {
        "input": 11,
        "output": 6,
        "cache_read": 0,
        "cache_creation": 0,
    }
