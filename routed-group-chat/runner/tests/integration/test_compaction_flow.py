"""Integration tests: compaction over many messages with the decision log and Store.

Only the model is faked; every message is saved to and reloaded from state.json.
"""

from __future__ import annotations

import pytest
from group_chat.compaction import turns_tokens

from ..conftest import FakeBackend
from .conftest import MakeChat

pytestmark = pytest.mark.integration


class CountingSummary(FakeBackend):
    """Returns ``summary-<n>`` for the n-th summary call."""

    def complete(self, system: str, prompt: str, model: str | None) -> str:
        text = super().complete(system, prompt, model)
        if text == self.summary:
            return f"summary-{sum('EARLIER SUMMARY' in c.prompt for c in self.calls)}"
        return text


def chatter(make_chat: MakeChat, backend: FakeBackend, count: int, budget: int) -> None:
    for i in range(count):
        marker = f"DECISION: decision {i}" if i % 3 == 0 else f"note {i} " + "x" * 80
        make_chat(backend, recent_tokens=budget).say(f"@po {marker}")


def test_log_is_intact_after_many_compactions(make_chat: MakeChat) -> None:
    backend = CountingSummary()
    chatter(make_chat, backend, 15, budget=60)
    state = make_chat(backend).store.load()
    assert [e.text for e in state.log.decisions] == [f"decision {i}" for i in range(0, 15, 3)]
    assert len(state.turns) == 4
    assert state.summary.startswith("summary-")


def test_each_summary_feeds_the_next(make_chat: MakeChat) -> None:
    backend = CountingSummary()
    chatter(make_chat, backend, 6, budget=60)
    summary_calls = [c for c in backend.calls if "EARLIER SUMMARY" in c.prompt]
    assert len(summary_calls) >= 2
    assert summary_calls[0].prompt.startswith("--- EARLIER SUMMARY ---\n(none)")
    assert "--- EARLIER SUMMARY ---\nsummary-1" in summary_calls[1].prompt


def test_role_sees_summary_and_full_log_after_compaction(make_chat: MakeChat) -> None:
    backend = CountingSummary()
    chatter(make_chat, backend, 9, budget=60)
    make_chat(backend, recent_tokens=60).say("@manager recap?")
    prompt = next(c.prompt for c in reversed(backend.calls) if "Reply as @manager." in c.prompt)
    assert "- [D1] decision 0 (by human)" in prompt
    assert "--- SUMMARY OF EARLIER DISCUSSION ---\nsummary-" in prompt


def test_folded_turns_are_not_repeated_in_summary_prompt(make_chat: MakeChat) -> None:
    backend = CountingSummary()
    chatter(make_chat, backend, 6, budget=60)
    folded = [c.prompt for c in backend.calls if "EARLIER SUMMARY" in c.prompt]
    assert sum(p.count("@human: @po DECISION: decision 0") for p in folded) == 1


def test_kept_turns_respect_budget_or_keep(make_chat: MakeChat) -> None:
    backend = FakeBackend()
    chatter(make_chat, backend, 8, budget=200)
    turns = make_chat(backend).store.load().turns
    assert len(turns) >= 4
    assert len(turns) == 4 or turns_tokens(turns) <= 200
