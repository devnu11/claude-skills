"""Pure branch names and the per-story records of story branches (s159, section 3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

MERGE_SUBJECT = "merge({id}): {title}"
MERGE_ID = re.compile(r"^merge\((?P<id>[^)]+)\): ")
LAND_SUFFIX = "-land"
REPLAY_SUFFIX = "-r{k}"
ASIDE_SUFFIX = "-kept-{tip}"
SHORT = 12
BRANCH_TAKEN = (
    "story {story}'s branch {branch} already exists at {tip}, but its fork starts at the "
    "sprint head {base}; the runner changed nothing. Way out: the human or the liaison sets "
    "the old branch aside in the main checkout, which keeps its commits: "
    "git branch -m {branch} {aside}. Then continue_story({story}); its next step forks "
    "{branch} from the sprint head."
)


class BranchAction(StrEnum):
    """s190: how a story's first step came by its branch (the story-branch event's action)."""

    CREATED = "created"
    REBUILT = "rebuilt"
    ADOPTED = "adopted"
    TAKEN = "taken"


@dataclass(frozen=True)
class TakenBranch:
    """s190: a local branch that already has the name a story's fork wants."""

    story_id: str
    branch: str
    tip: str
    base: str  # the sprint head the fork would start from

    @property
    def is_at_base(self) -> bool:
        """T2: the branch sits where a fork would put it."""
        return self.tip == self.base

    @property
    def aside_branch(self) -> str:
        """T5: ``<branch>-kept-<tip[:12]>``, the name the way out renames it to."""
        return self.branch + ASIDE_SUFFIX.format(tip=self.tip[:SHORT])

    @property
    def reason(self) -> str:
        """T4: ``BRANCH_TAKEN`` filled in (tip and base cut to ``SHORT``)."""
        return BRANCH_TAKEN.format(
            story=self.story_id,
            branch=self.branch,
            tip=self.tip[:SHORT],
            base=self.base[:SHORT],
            aside=self.aside_branch,
        )

    @property
    def event_data(self) -> dict[str, str]:
        """T3: the ``taken`` story-branch event's data."""
        return {
            "action": BranchAction.TAKEN.value,
            "branch": self.branch,
            "tip": self.tip,
            "base_sha": self.base,
            "aside": self.aside_branch,
        }


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
    heads: dict[str, str] = field(default_factory=dict)  # s176: free branch -> sha at the start
    made: list[str] = field(default_factory=list)  # s182: tips the runner made by folding


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
