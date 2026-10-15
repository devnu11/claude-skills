"""Unit tests for ``compaction``: token estimates and the eviction split."""

from __future__ import annotations

import pytest
from group_chat.compaction import build_summary_prompt, measure_tokens, measure_turns, split
from group_chat.state import Turn

pytestmark = pytest.mark.unit


def turns(n: int, size: int = 40) -> list[Turn]:
    return [Turn("po", f"{i}" * size) for i in range(n)]


def test_estimate_tokens() -> None:
    assert measure_tokens("") == 1
    assert measure_tokens("x" * 40) == 11


def test_split_under_budget_evicts_nothing() -> None:
    history = turns(3)
    assert split(history, 10_000, 1) == ([], history)


def test_split_evicts_oldest_until_fits() -> None:
    history = turns(6)
    budget = measure_turns(history[-2:])
    evicted, kept = split(history, budget, 1)
    assert evicted == history[:4]
    assert kept == history[4:]


def test_split_always_keeps_last_turns() -> None:
    history = turns(5)
    evicted, kept = split(history, 0, 3)
    assert kept == history[2:]
    assert evicted == history[:2]


def test_summary_prompt() -> None:
    text = build_summary_prompt("", [Turn("po", "hi")])
    assert "(none)" in text
    assert '<turn speaker="po">\nhi\n</turn>' in text


def test_keep_at_least_len_turns_evicts_nothing() -> None:
    history = turns(3)
    assert split(history, 0, 3) == ([], history)
    assert split(history, 0, 10) == ([], history)


def test_budget_exactly_met_evicts_nothing() -> None:
    history = turns(4)
    assert split(history, measure_turns(history), 0) == ([], history)


def test_budget_one_short_evicts_one() -> None:
    history = turns(4)
    evicted, kept = split(history, measure_turns(history) - 1, 0)
    assert evicted == history[:1]
    assert kept == history[1:]


def test_keep_zero_can_evict_everything() -> None:
    history = turns(3)
    assert split(history, 0, 0) == (history, [])


def test_split_empty() -> None:
    assert split([], 0, 4) == ([], [])


def test_turns_tokens_counts_blocks() -> None:
    turn = Turn("po", "")
    assert measure_turns([turn]) == measure_tokens(turn.tagged)


def test_summary_prompt_carries_earlier_summary_and_order() -> None:
    text = build_summary_prompt("old", [Turn("po", "a"), Turn("manager", "b")])
    assert text.index("old") < text.index('speaker="po"') < text.index('speaker="manager"')
