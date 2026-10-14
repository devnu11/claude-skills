from __future__ import annotations

from group_chat.compaction import estimate_tokens, split, summary_prompt, turns_tokens
from group_chat.state import Turn


def turns(n: int, size: int = 40) -> list[Turn]:
    return [Turn("po", f"{i}" * size) for i in range(n)]


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("x" * 40) == 11


def test_split_under_budget_evicts_nothing() -> None:
    history = turns(3)
    assert split(history, 10_000, 1) == ([], history)


def test_split_evicts_oldest_until_fits() -> None:
    history = turns(6)
    budget = turns_tokens(history[-2:])
    evicted, kept = split(history, budget, 1)
    assert evicted == history[:4]
    assert kept == history[4:]


def test_split_always_keeps_last_turns() -> None:
    history = turns(5)
    evicted, kept = split(history, 0, 3)
    assert kept == history[2:]
    assert evicted == history[:2]


def test_summary_prompt() -> None:
    text = summary_prompt("", [Turn("po", "hi")])
    assert "(none)" in text
    assert "@po: hi" in text
