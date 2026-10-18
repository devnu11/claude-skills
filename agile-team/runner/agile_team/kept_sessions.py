"""Kept SDK sessions per role on a story (s159 K1 to K3). Pure."""

from __future__ import annotations

import re
from typing import Any

from .gates import StoryState

CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"prompt is too long", re.I),
    re.compile(r"context (window|length)", re.I),
)


def resume_of(story: StoryState, role: Any) -> str | None:
    """The session to resume for ``role``, when model, effort and provider all match."""
    kept = story.sessions.get(role.name)
    same = kept and (kept.model, kept.effort, kept.provider) == (
        role.model,
        role.effort,
        role.provider,
    )
    return kept.session if same else None


def drop_all(story: StoryState) -> None:
    """End every kept session of the story."""
    story.sessions.clear()


def drop_role(story: StoryState, role: str) -> None:
    """End one role's kept session."""
    story.sessions.pop(role, None)


def context_exceeded(  # house-rules: allow verb-name -- name fixed by the s159 tests
    text: str,
) -> bool:
    """True when ``text`` is a context-limit error."""
    return any(p.search(text) for p in CONTEXT_PATTERNS)
