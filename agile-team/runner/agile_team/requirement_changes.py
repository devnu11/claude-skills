"""A step's requirement changes: classify, explain, trailers, accept, log (s2, ADR-0083)."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from . import frontmatter, system
from .gates import FINISHED, StoryState, StoryStatus
from .git_ops import Git
from .priority import natural
from .requirements import parse_ref
from .roles import Handoff, HandoffError

GLOB = "REQ-*.md"
TRAILER_KEY = "Requirement-Changed"
TRAILER = "Requirement-Changed: {id}: {reason}"
NEW_REASON = "new requirement"
EXPLAIN = "explain change to {id}"
UNEXPLAINED = (
    "{explain} (your edits are held back in {sha}; make them again and give each reason in "
    "the handoff's requirement_changes)"
)
STOP_EXPLAIN = (
    '{explain}: add "requirement_changes": {{"<id>": "<why>"}} to your handoff for each '
    "changed or retired requirement"
)
HELD_SUBJECT = "chore(team): {role}'s unexplained requirement edits, held back"
REDESIGN_NOTE = (
    "Back to design: {by}'s step changed requirements this story traces ({sha}): {changes}. "
    "Check the design and its trace against them."
)
DIFF_ARGV = ("diff", "--name-status", "--no-renames", "-z", "HEAD", "--")
LOG_FORMAT = "%H%x1f%aI%x1f%(trailers:key=Requirement-Changed,valueonly,unfold,separator=%x1e)%x1d"
LOG_ID = re.compile(r"REQ-\d+")


class Change(StrEnum):
    """What a step did to a requirement file."""

    ADDED = "added"
    CHANGED = "changed"
    RETIRED = "retired"


NEEDS_REASON = frozenset({Change.CHANGED, Change.RETIRED})


@dataclass(frozen=True)
class Versions:
    """One candidate's text at HEAD and on disk; None when absent."""

    file: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class Changed:
    """A classified candidate and the stories its covers name (either version)."""

    id: str
    change: Change
    file: str
    stories: tuple[str, ...]


@dataclass(frozen=True)
class Explained:
    """A change with its one-line reason ("" when unexplained)."""

    changed: Changed
    reason: str

    def trailer(self, template: str = TRAILER) -> str:
        """The ``Requirement-Changed`` trailer line (``template`` is the line's format)."""
        return template.format(id=self.changed.id, reason=self.reason)

    def report(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """The change as the step report lists it, plus any ``extra`` keys."""
        base = {"id": self.changed.id, "change": self.changed.change.value, "reason": self.reason}
        return base | dict(extra or {})


@dataclass(frozen=True)
class Sorting:
    """A step's candidates split into landed and held back."""

    landed: tuple[Explained, ...]
    held: tuple[Changed, ...]

    @property
    def held_files(self) -> list[str]:
        """Repo-relative paths of the held-back files."""
        return [c.file for c in self.held]

    @property
    def trailers(self) -> tuple[str, ...]:
        """The landed changes as trailer lines."""
        return tuple(e.trailer() for e in self.landed)


@dataclass(frozen=True)
class Affected:
    """Stories a landed change touches: sent back to design, and done ones."""

    redesign: tuple[str, ...] = ()
    done: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcceptScope:
    """What ``find_affected`` needs besides the stories."""

    traced: tuple[str, ...]
    past_design: Callable[[StoryState], bool]


@dataclass(frozen=True)
class NoteTarget:
    """Whose note, written by which step's commit."""

    story: str
    by: str
    sha: str


@dataclass(frozen=True)
class HeldBack:
    """The role and files of a hold-back commit."""

    role: str
    files: tuple[str, ...]


# ----- pure -----


def candidates(paths: Sequence[str], folder: str) -> list[str]:
    """The ``REQ-*.md`` files directly in ``folder``."""
    return [p for p in paths if _is_candidate(PurePosixPath(p), folder)]


def _is_candidate(path: PurePosixPath, folder: str) -> bool:
    return path.parent.as_posix() == folder and fnmatch.fnmatchcase(path.name, GLOB)


def classify(versions: Versions) -> Changed:
    """Sort one candidate into added, changed or retired (never refuses)."""
    stem = PurePosixPath(versions.file).stem
    return Changed(stem, _find_kind(versions), versions.file, _find_stories(versions))


def _read_meta(text: str | None) -> dict[str, Any]:
    parsed = frontmatter.parse(text) if text is not None else None
    return parsed[0] if parsed else {}


def _find_kind(versions: Versions) -> Change:
    if versions.before is None:
        return Change.ADDED
    if versions.after is None:
        return Change.RETIRED
    was, now = (_read_meta(t).get("status") == "retired" for t in (versions.before, versions.after))
    return Change.RETIRED if now and not was else Change.CHANGED


def _find_stories(versions: Versions) -> tuple[str, ...]:
    found: set[str] = set()
    for text in (versions.before, versions.after):
        covers = _read_meta(text).get("covers")
        refs = (parse_ref(v) for v in covers) if isinstance(covers, list) else ()
        found |= {r.story for r in refs if r}
    return tuple(sorted(found, key=natural))


def reason_for(changed: Changed, reasons: Mapping[str, str]) -> str:
    """The one-line reason for ``changed`` ("" when a changed or retired one has none)."""
    reason = " ".join(reasons.get(changed.id, "").split())
    return reason or (NEW_REASON if changed.change is Change.ADDED else "")


def sort_changes(changes: Sequence[Changed], reasons: Mapping[str, str]) -> Sorting:
    """Split ``changes`` into landed (added or explained) and held (unexplained)."""
    ordered = sorted(changes, key=lambda c: natural(c.id))
    explained = [Explained(c, reason_for(c, reasons)) for c in ordered]
    return Sorting(
        landed=tuple(e for e in explained if e.reason),
        held=tuple(e.changed for e in explained if not e.reason),
    )


def explain_text(held: Sequence[Changed]) -> str:
    """One ``explain change to ID`` per held change, joined by ``; ``."""
    return "; ".join(EXPLAIN.format(id=c.id) for c in held)


def describe_unexplained(held: Sequence[Changed], sha: str) -> str:
    """The bad-handoff text for held-back edits."""
    return UNEXPLAINED.format(explain=explain_text(held), sha=sha)


def unexplained_error(parsed: Handoff | HandoffError, text: str) -> HandoffError:
    """The bad handoff for ``text``, after the parse error when there already was one."""
    if isinstance(parsed, HandoffError):
        return HandoffError(f"{parsed}; {text}")
    return HandoffError(text)


def traced(landed: Sequence[Explained], own: str | None) -> list[str]:
    """Stories traced by changed or retired requirements, without the step's own."""
    found = {s for e in landed if e.changed.change in NEEDS_REASON for s in e.changed.stories}
    return sorted(found - {own}, key=natural)


def find_affected(stories: Mapping[str, StoryState], scope: AcceptScope) -> Affected:
    """Which traced stories go back to design and which are done."""
    known = [stories[s] for s in scope.traced if s in stories]
    done = tuple(s.id for s in known if s.status is StoryStatus.DONE)
    back = tuple(s.id for s in known if s.status not in FINISHED and scope.past_design(s))
    return Affected(redesign=back, done=done)


def redesign_note(landed: Sequence[Explained], target: NoteTarget) -> str:
    """The note a story sent back to design carries."""
    named = [
        e for e in landed if e.changed.change in NEEDS_REASON and target.story in e.changed.stories
    ]
    changes = "; ".join(f"{e.changed.id} {e.changed.change}: {e.reason}" for e in named)
    return REDESIGN_NOTE.format(by=target.by, sha=target.sha[:12], changes=changes)


def parse_log(out: str) -> list[dict[str, str]]:
    """Rows (id, reason, sha, date) from ``LOG_FORMAT`` output, in order."""
    return [row for record in out.split("\x1d") for row in _record_rows(record.strip())]


def _record_rows(record: str) -> list[dict[str, str]]:
    parts = record.split("\x1f", 2)
    if len(parts) < 3:
        return []
    sha, date, values = parts
    pairs = (_split_trailer(v.strip()) for v in values.split("\x1e"))
    return [{"id": i, "reason": r, "sha": sha, "date": date} for i, r in (p for p in pairs if p)]


def _split_trailer(value: str) -> tuple[str, str] | None:
    req_id, sep, reason = value.partition(": ")
    return (req_id, reason) if sep and reason and LOG_ID.fullmatch(req_id) else None


# ----- git and disk -----


def read_name_status(git: Git, paths: Sequence[str]) -> dict[str, str]:
    """Path to diff letter; a path the diff doesn't list is untracked, so ``A``."""
    parts = [p for p in git.run(*DIFF_ARGV, *paths).split("\0") if p]
    listed = {
        path: ("M" if letter == "T" else letter)
        for letter, path in zip(parts[::2], parts[1::2], strict=False)
    }
    return {p: "A" for p in paths} | listed


def read_versions(git: Git, entry: tuple[str, str]) -> Versions:
    """The candidate's text at HEAD and on disk."""
    path, letter = entry
    before = None if letter == "A" else git.run("show", f"HEAD:{path}")
    after = None if letter == "D" else system.read_text(git.repo / path)
    return Versions(path, before, after)


def find_changes(git: Git, paths: Sequence[str]) -> list[Changed]:
    """Classify the candidate ``paths`` (no git command when there are none)."""
    if not paths:
        return []
    letters = read_name_status(git, paths)
    return [classify(read_versions(git, (p, letters[p]))) for p in paths]


def hold_back(git: Git, held: HeldBack) -> str:
    """Commit the held files alone, revert that commit, and return its sha."""
    sha = git.commit(list(held.files), HELD_SUBJECT.format(role=held.role))
    git.revert(sha)
    return sha


def log(git: Git, folder: str) -> list[dict[str, str]]:
    """The requirement change history from the ``Requirement-Changed`` trailers."""
    out = git.run("log", "--reverse", f"--format={LOG_FORMAT}", "--", folder)
    return parse_log(out)
