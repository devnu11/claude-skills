"""Old-to-new commit pairing after a rebase, and rewriting the hashes in ``state.json``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .story_branches import merge_id

if TYPE_CHECKING:
    from .gates import StoryState
    from .salvage import Interruption
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


ReplayLine = tuple[str, str, tuple[str, ...]]  # (sha, subject, parents)


def _story_commits(lines: Sequence[ReplayLine]) -> dict[str, list[ReplayLine]]:
    """Each merge's story commits (``M^1..M^2`` inside ``lines``), by merge sha, oldest first."""
    index = {line[0]: line for line in lines}
    claimed: set[str] = set()
    found: dict[str, list[ReplayLine]] = {}
    for sha, _subject, parents in lines:
        if len(parents) == 2:
            found[sha] = _walk(parents[1], (index, claimed))
    return found


def _walk(sha: str, seen: tuple[Mapping[str, ReplayLine], set[str]]) -> list[ReplayLine]:
    """The unclaimed non-merge commits reachable from ``sha`` inside the listing, oldest first."""
    index, claimed = seen
    if sha not in index or sha in claimed or len(index[sha][2]) > 1:
        return []
    claimed.add(sha)
    below = [c for parent in index[sha][2] for c in _walk(parent, seen)]
    return [*below, index[sha]]


def _pair_by_subject(old: Sequence[ReplayLine], new: Sequence[ReplayLine]) -> dict[str, str]:
    """Old sha to new sha, matching subjects in order."""
    moved: dict[str, str] = {}
    cursor = 0
    for sha, subject, _parents in old:
        ahead = next((i for i in range(cursor, len(new)) if new[i][1] == subject), None)
        if ahead is not None:
            moved[sha] = new[ahead][0]
            cursor = ahead + 1
    return moved


def pair_replay(old: Sequence[ReplayLine], new: Sequence[ReplayLine]) -> dict[str, str]:
    """R4: pair a replay's commits story by story, merges by ``merge(<id>)``, plain by subject."""
    old_stories, new_stories = _story_commits(old), _story_commits(new)
    new_merges = _merges_by_id(new)
    moved = _pair_by_subject(_plain(old, old_stories), _plain(new, new_stories))
    for story_id, merge in _merges_by_id(old).items():
        if story_id in new_merges:
            twin = new_merges[story_id]
            moved[merge[0]] = twin[0]
            moved |= _pair_by_subject(old_stories[merge[0]], new_stories[twin[0]])
    return moved


def _merges_by_id(lines: Sequence[ReplayLine]) -> dict[str, ReplayLine]:
    found = {}
    for line in lines:
        story_id = merge_id(line[1])
        if story_id and len(line[2]) == 2:
            found[story_id] = line
    return found


def _plain(
    lines: Sequence[ReplayLine], stories: Mapping[str, list[ReplayLine]]
) -> list[ReplayLine]:
    inside = {c[0] for commits in stories.values() for c in commits}
    return [line for line in lines if line[0] not in inside and line[0] not in stories]


def _moved(sha: str | None, moved: Mapping[str, str]) -> str | None:
    return moved.get(sha, sha) if sha else sha


def _changed(before: str | None, after: str | None) -> int:
    return int(before != after)


def remap_state(state: RunState, moved: Mapping[str, str]) -> int:
    """R6: rewrite the ``REMAPPED`` fields in place; return how many values changed."""
    count = sum(_story(story, moved) for story in state.stories.values())
    count += _interruptions(state.interrupted, moved)
    return count + _upstream(state, moved)


def _swap(obj: object, attr: str, moved: Mapping[str, str]) -> int:
    before = getattr(obj, attr)
    after = _moved(before, moved)
    setattr(obj, attr, after)
    return _changed(before, after)


def _story(story: StoryState, moved: Mapping[str, str]) -> int:
    count = _swap(story, "commit", moved)
    count += _remap_all(story.code_commits, moved) + _remap_all(story.file_commits, moved)
    return count + _interruptions([story.interrupted] if story.interrupted else [], moved)


def _remap_all(shas: list[str], moved: Mapping[str, str]) -> int:
    count = 0
    for i, sha in enumerate(shas):
        shas[i] = _moved(sha, moved)
        count += _changed(sha, shas[i])
    return count


def _interruptions(items: Sequence[Interruption], moved: Mapping[str, str]) -> int:
    return sum(_swap(item, "sha", moved) for item in items)


def _upstream(state: RunState, moved: Mapping[str, str]) -> int:
    up = state.upstream
    count = _swap(up, "last_end", moved)
    for entry in up.stack:
        count += _swap(entry, "start", moved) + _swap(entry, "end", moved)
    return count
