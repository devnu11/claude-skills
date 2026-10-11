"""Why a story is not moving (s40): the board's hold mark and what it waits on."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .gates import StoryState, StoryStatus

ROUND_CAP_DETAIL = "round {rounds}: the manager must rule"


class WaitReason(StrEnum):
    """The reasons a story waits."""

    QUESTIONS = "questions"
    MANAGER = "manager"
    ROUND_CAP = "round cap"
    HUMAN = "needs the human"
    HELD = "held"


@dataclass(frozen=True)
class Wait:
    """A reason and what it waits on."""

    reason: WaitReason
    on: list[str]


@dataclass(frozen=True)
class WaitRule:
    """One row of ``WAITS``."""

    reason: WaitReason
    applies: Callable[[StoryState, list[str]], bool]
    detail: Callable[[StoryState], str]


def _summary(story: StoryState) -> str:
    prev = story.previous
    return f"{prev.role}: {prev.summary}" if prev and prev.summary else ""


def _held_detail(story: StoryState) -> str:
    summary = _summary(story)
    return f"{story.hold} · {summary}" if summary else str(story.hold)


def _first_line(story: StoryState) -> str:
    return (story.repeated or "").split("\n", 1)[0]


def _needs_manager(story: StoryState) -> bool:
    return story.status is StoryStatus.NEEDS_MANAGER


WAITS: tuple[WaitRule, ...] = (
    WaitRule(WaitReason.HUMAN, lambda s, a: s.status is StoryStatus.BLOCKED, _summary),
    WaitRule(WaitReason.MANAGER, lambda s, a: _needs_manager(s) and bool(s.repeated), _first_line),
    WaitRule(
        WaitReason.ROUND_CAP,
        lambda s, a: _needs_manager(s),
        lambda s: ROUND_CAP_DETAIL.format(rounds=s.rounds),
    ),
    WaitRule(
        WaitReason.QUESTIONS,
        lambda s, a: "questions" in (s.hold or "").split(", "),
        _summary,
    ),
    WaitRule(WaitReason.HELD, lambda s, a: bool(s.hold), _held_detail),
    WaitRule(WaitReason.HUMAN, lambda s, a: bool(a), lambda s: ""),
)


def wait(story: StoryState, asking: list[str]) -> Wait | None:
    """Why the story is not moving, or None."""
    if story.status is StoryStatus.DONE:
        return None
    rule = next((r for r in WAITS if r.applies(story, asking)), None)
    if rule is None:
        return None
    detail = rule.detail(story)
    return Wait(rule.reason, asking + ([detail] if detail else []))
