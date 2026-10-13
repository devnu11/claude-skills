"""Old-to-new commit pairing after a rebase, and rewriting the hashes in ``state.json``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import RunState

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"


@dataclass(frozen=True)
class Stamped:
    """A commit and what a rebase keeps of it (author, date, message)."""

    sha: str
    stamp: str


@dataclass(frozen=True)
class Listing:
    """The rebased commits, oldest first, and the commit they sit on."""

    onto: str
    commits: tuple[Stamped, ...]


def parse_listing(out: str) -> tuple[Stamped, ...]:
    """``git log --format=STAMP_FORMAT`` output as ``Stamped`` records (blank records skipped)."""
    records = (r.strip("\n") for r in out.split(RECORD_SEP))
    return tuple(_stamped(r) for r in records if r.strip())


def _stamped(record: str) -> Stamped:
    sha, _, stamp = record.partition(FIELD_SEP)
    return Stamped(sha, stamp)


def pair(old: Sequence[Stamped], new: Listing) -> dict[str, str]:
    """R5: every old sha to its rebased copy, or to the last kept copy before it."""
    moved: dict[str, str] = {}
    cursor, last = 0, new.onto
    for commit in old:
        if cursor < len(new.commits) and new.commits[cursor].stamp == commit.stamp:
            last = new.commits[cursor].sha
            cursor += 1
        moved[commit.sha] = last
    return moved


def _moved(sha: str | None, moved: Mapping[str, str]) -> str | None:
    return moved.get(sha, sha) if sha else sha


def _changed(before: str | None, after: str | None) -> int:
    return int(before != after)


def remap_state(state: RunState, moved: Mapping[str, str]) -> int:
    """R6: rewrite the ``REMAPPED`` fields in place; return how many values changed."""
    count = sum(_story(story, moved) for story in state.stories.values())
    count += _interruptions(state.interrupted, moved)
    return count + _upstream(state, moved)


def _story(story, moved: Mapping[str, str]) -> int:
    before = [story.commit, *story.code_commits]
    story.commit = _moved(story.commit, moved)
    story.code_commits = [_moved(c, moved) for c in story.code_commits]
    after = [story.commit, *story.code_commits]
    count = sum(_changed(b, a) for b, a in zip(before, after, strict=True))
    return count + _interruptions([story.interrupted] if story.interrupted else [], moved)


def _interruptions(items, moved: Mapping[str, str]) -> int:
    count = 0
    for item in items:
        count += _changed(item.sha, _moved(item.sha, moved))
        item.sha = _moved(item.sha, moved)
    return count


def _upstream(state: RunState, moved: Mapping[str, str]) -> int:
    up = state.upstream
    count = _changed(up.last_end, _moved(up.last_end, moved))
    up.last_end = _moved(up.last_end, moved) or ""
    for entry in up.stack:
        count += _changed(entry.start, _moved(entry.start, moved))
        count += _changed(entry.end, _moved(entry.end, moved))
        entry.start = _moved(entry.start, moved) or ""
        entry.end = _moved(entry.end, moved) or ""
    return count
