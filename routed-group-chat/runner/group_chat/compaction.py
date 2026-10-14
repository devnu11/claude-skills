"""Keep the verbatim transcript under a token budget by folding the oldest
turns into a rolling summary. The decision log is separate and never folded.
"""

from __future__ import annotations

from collections.abc import Sequence

from .state import Turn

CHARS_PER_TOKEN = 4

SUMMARY_SYSTEM = """\
You keep the running summary of a group chat. Merge the earlier summary and the
turns below into one updated summary: who said what that still matters, open
threads and positions taken. Be concise. Output only the summary."""


def estimate_tokens(text: str) -> int:
    """A rough token count; enough to decide when to compact."""
    return len(text) // CHARS_PER_TOKEN + 1


def turns_tokens(turns: Sequence[Turn]) -> int:
    return sum(estimate_tokens(turn.render()) for turn in turns)


def split(turns: Sequence[Turn], budget: int, keep: int) -> tuple[list[Turn], list[Turn]]:
    """``(evicted, kept)``: evict oldest turns until the rest fit ``budget``,
    always keeping the last ``keep`` turns."""
    cut = 0
    while len(turns) - cut > keep and turns_tokens(turns[cut:]) > budget:
        cut += 1
    return list(turns[:cut]), list(turns[cut:])


def summary_prompt(summary: str, evicted: Sequence[Turn]) -> str:
    turns = "\n\n".join(turn.render() for turn in evicted)
    return f"--- EARLIER SUMMARY ---\n{summary or '(none)'}\n\n--- TURNS TO FOLD IN ---\n{turns}"
