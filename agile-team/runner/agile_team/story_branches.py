"""Pure branch names and the per-story records of story branches (s159, section 3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MERGE_SUBJECT = "merge({id}): {title}"
MERGE_ID = re.compile(r"^merge\((?P<id>[^)]+)\): ")
LAND_SUFFIX = "-land"
REPLAY_SUFFIX = "-r{k}"


@dataclass
class Landed:
    """A story's landing merge, set at the landing push."""

    merge: str
    pushed: str = ""
    pr: int | None = None


@dataclass
class KeptSession:
    """A role's SDK session on one story, kept for the next step of that role."""

    session: str
    model: str
    effort: str
    provider: str
    reported: float = 0.0


@dataclass
class StoryCi:
    """The latest CI verdict seen for a story's pushed head."""

    sha: str
    verdict: str
    source: str  # "pr" | "landing"
    checks: list[str] = field(default_factory=list)


@dataclass
class StoryRebase:
    """A queued rebase of a story branch onto a newer base."""

    onto: str
    base: str
    old: str
    branch: str
    files: list[str]
    role: str


def format_story_branch(
    prefix: str,
    story_id: str,
    replays: int,
) -> str:
    """The story's branch name; replays add ``-r<k>``."""
    name = f"{prefix}{story_id}"
    return name + REPLAY_SUFFIX.format(k=replays) if replays else name


def format_landing_branch(
    prefix: str,
    story_id: str,
) -> str:
    """The short-lived branch a landing is pushed to for CI."""
    return f"{prefix}{story_id}{LAND_SUFFIX}"


def merge_subject(story_id: str, title: str) -> str:
    """The subject of a story's landing merge."""
    return MERGE_SUBJECT.format(id=story_id, title=title)


def merge_id(subject: str) -> str | None:
    """The story id a merge subject names, or None for any other subject."""
    found = MERGE_ID.match(subject)
    return found.group("id") if found else None
