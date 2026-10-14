"""Why a story is not moving (s40): the board's hold mark and what it waits on."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .gates import FINISHED, StoryState, StoryStatus
from .holds import HoldKind

ROUND_CAP_DETAIL = "round {rounds}: the manager must rule"


class WaitReason(StrEnum):
    """The reasons a story waits."""

    QUESTIONS = "questions"
    MANAGER = "manager"
    ROUND_CAP = "round cap"
    HUMAN = "needs the human"
    HELD = "held"
    PO_HOLD = "PO hold"
    CANCEL_REQUESTED = "cancel requested"
    REVERT_REQUESTED = "revert requested"


TITLED = frozenset({WaitReason.PO_HOLD, WaitReason.CANCEL_REQUESTED, WaitReason.REVERT_REQUESTED})


@dataclass(frozen=True)
class Wait:
    """A reason and what it waits on."""

    reason: WaitReason
    on: list[str]
    title: str


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


def _po_kind(story: StoryState) -> HoldKind | None:
    return story.po_hold.kind if story.po_hold else None


def _po_reason(story: StoryState) -> str:
    return story.po_hold.reason if story.po_hold else ""


def _needs_manager(story: StoryState) -> bool:
    return story.status is StoryStatus.NEEDS_MANAGER


WAITS: tuple[WaitRule, ...] = (
    WaitRule(WaitReason.CANCEL_REQUESTED, lambda s, a: _po_kind(s) is HoldKind.CANCEL, _po_reason),
    WaitRule(WaitReason.REVERT_REQUESTED, lambda s, a: _po_kind(s) is HoldKind.REVERT, _po_reason),
    WaitRule(WaitReason.PO_HOLD, lambda s, a: _po_kind(s) is HoldKind.HOLD, _po_reason),
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
    if story.status in FINISHED:
        return None
    rule = next((r for r in WAITS if r.applies(story, asking)), None)
    if rule is None:
        return None
    detail = rule.detail(story)
    return Wait(rule.reason, asking + ([detail] if detail else []), _title(rule.reason, detail))


def _title(reason: WaitReason, detail: str) -> str:
    return f"{reason}: {detail}" if reason in TITLED else str(reason)
