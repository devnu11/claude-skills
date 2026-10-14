"""What a revert records (s124): the story-file entry, the brief note and the PR lines.

Pure text; imports no other ``agile_team`` module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING = "## Reverted"
FILE_LINE = (
    "- {date}, sprint {sprint}: {reason} Reverted commits: {commits}. Revert commit: {revert}."
)
BRIEF = (
    "## Reverted\n\nThis story was reverted {count}× and starts again. Latest: {date}, "  # noqa: RUF001
    "sprint {sprint}: {reason}\nReverted commits: {commits}; revert commit: {revert}."
)
REDESIGN_LINE = (
    'Your design must say what changes this time, under a "## After revert {count}" heading; '
    "the design gate checks for it."
)
PR_HEAD = "Reverted:\n{lines}\n\n"
PR_LINE = "- {label}: {reason} (reverted {commits}; revert {revert})"
DESIGN_FILE = "{docs}/design/{id}.md"
SHORT = 12
DESIGN_STEP = "design"


@dataclass
class RevertEntry:
    """One revert of a story: when, in which sprint, why, what it undid (R5)."""

    date: str
    sprint: int
    reason: str
    commits: list[str]
    revert: str
    record: str = ""


def short(sha: str) -> str:
    """The first SHORT characters."""
    return sha[:SHORT]


def _shorts(shas: list[str]) -> str:
    return ", ".join(map(short, shas))


def file_line(entry: RevertEntry) -> str:
    """FILE_LINE for the story file."""
    return FILE_LINE.format(
        date=entry.date,
        sprint=entry.sprint,
        reason=entry.reason,
        commits=_shorts(entry.commits),
        revert=short(entry.revert),
    )


def with_entry(text: str, entry: RevertEntry) -> str:
    """The story file text with the entry appended, and HEADING added before the first one."""
    text = text if text.endswith("\n") else text + "\n"
    if HEADING not in text.splitlines():
        text += f"\n{HEADING}\n\n"
    return f"{text}{file_line(entry)}\n"


def brief_section(entries: list[RevertEntry], step: str) -> str:
    """BRIEF for the latest entry, plus REDESIGN_LINE at step ``design``; "" with no entries."""
    if not entries:
        return ""
    last = entries[-1]
    text = BRIEF.format(
        count=len(entries),
        date=last.date,
        sprint=last.sprint,
        reason=last.reason,
        commits=_shorts(last.commits),
        revert=short(last.revert),
    )
    if step != DESIGN_STEP:
        return text
    return f"{text}\n\n{REDESIGN_LINE.format(count=len(entries))}"


def after_heading(text: str, count: int) -> bool:
    """R9: the design has its After revert heading."""
    pattern = rf"^##\s+After revert {count}\b"
    return re.search(pattern, text, re.IGNORECASE | re.MULTILINE) is not None


def pr_line(label: str, entry: RevertEntry) -> str:
    """PR_LINE; ``label`` is ``sN: <title>``."""
    return PR_LINE.format(
        label=label,
        reason=entry.reason,
        commits=_shorts(entry.commits),
        revert=short(entry.revert),
    )


def pr_section(lines: list[str]) -> str:
    """PR_HEAD around the lines; "" when there are none."""
    return PR_HEAD.format(lines="\n".join(lines)) if lines else ""


def design_file(docs_dir: str, story_id: str) -> str:
    """DESIGN_FILE with the docs dir stripped of a trailing slash."""
    return DESIGN_FILE.format(docs=docs_dir.rstrip("/"), id=story_id)
