"""When and how the PO session is renewed: boundaries, `/compact`, handoff-file fallback."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from . import system
from .relay import Relay

HANDOFF_FILE = ".team/po/handoff.md"
KEEP = (
    "open decisions; pending questions with their ids and the stories they block; "
    "what is next and why; paths to artifacts (stories, designs, reviews) rather "
    "than their content"
)
COMPACT_PROMPT = (
    f"/compact Keep only what your next turns need: {KEEP}. Drop the step-by-step history."
)
HANDOFF_PROMPT = (
    "The runner is renewing your session to keep it small. Write "
    f"{HANDOFF_FILE} with: {KEEP}. Write nothing else, then end your turn."
)
FRESH_LEAD = (
    "You are continuing this run in a fresh session. Your previous session's "
    "handoff ({file}):\n\n{handoff}\n\nstory_status:\n{status}"
)
CARRY_HEAD = "Open questions (from the inbox; they stay open until the human answers):"


class RenewPath(StrEnum):
    """How a renewal went (or is configured to go)."""

    COMPACT = "compact"
    HANDOFF = "handoff"
    KEPT = "kept"


def carry_over(relay: Relay) -> str:
    """The open questions as prompt text; empty when none are open."""
    questions = relay.open_questions()
    if not questions:
        return ""
    lines = [f"- {q.id} (blocks {', '.join(q.stories) or 'nothing'}): {q.text}" for q in questions]
    return "\n".join([CARRY_HEAD, *lines])


def with_carry_over(relay: Relay, prompt: str) -> str:
    """``prompt`` preceded by the open questions, if any."""
    return "\n\n".join(p for p in (carry_over(relay), prompt) if p)


def read_handoff(repo: Path) -> str:
    """The PO's handoff file, stripped; empty when missing."""
    path = repo / HANDOFF_FILE
    return system.read_text(path).strip() if system.is_file(path) else ""


def clear_handoff(repo: Path) -> None:
    """Delete a stale handoff file."""
    system.remove(repo / HANDOFF_FILE)


def fresh_lead(handoff: str, status: str) -> str:
    """The opening of a fresh session's prompt."""
    return FRESH_LEAD.format(file=HANDOFF_FILE, handoff=handoff, status=status)
