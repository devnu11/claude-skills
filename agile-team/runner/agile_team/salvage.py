"""A step cut short: what ran, why it stopped, and the reverted commit holding its edits."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .git_ops import Git

SUBJECT = "chore(team): interrupted step by {label}"
NOTE_SUFFIX = "; {label}'s edits are saved in {sha} (git cherry-pick -n {sha})"
OFFER = (
    "Interrupted work: an earlier {label} step was cut off ({cause}). "
    "Its edits are saved in commit {sha} and reverted. "
    "Reuse them with `git cherry-pick -n {sha}` and check them before you build on them; "
    "files outside your write scope are quarantined again."
)
RESUME_HEAD = (
    "## Interrupted steps\n\n"
    "The runner saved each cut-off step's edits in a commit and reverted it."
)
RESUME_ITEM = "- {label} ({cause}): {saved}\n  Brief: {brief}"
RESUME_TAIL = (
    "Re-run each step. On a story, the runner offers the saved commit in the next brief "
    "on that story; for any other step, put the cherry-pick line in your brief."
)
SAVED = "edits saved in {sha}; reuse with `git cherry-pick -n {sha}`"
NO_EDITS = "no edits"


class Cause(StrEnum):
    """Why a step was cut off; LIMIT, CRASH, SIGTERM and BUDGET equal ``halt.HaltKind`` values."""

    ERROR = "error"
    LIMIT = "limit"
    CRASH = "crash"
    SIGTERM = "sigterm"
    BUDGET = "budget"
    CHECKOUT = "checkout"
    KILLED = "killed"


RUN_ENDING = frozenset(c for c in Cause if c is not Cause.ERROR)


def label(role: str, story: str | None) -> str:
    """``role on story``, or just ``role`` with no story."""
    return f"{role} on {story}" if story else role


@dataclass(frozen=True)
class InFlight:
    """The step that was running."""

    role: str
    story: str | None
    brief: str


PO_TURN = InFlight("product-owner", None, "the PO's own turn")


@dataclass(frozen=True)
class Cut:
    """A stop: its cause and the step that was in flight, if any."""

    cause: Cause
    step: InFlight | None


@dataclass
class Interruption:
    """A cut-off step and the reverted commit holding its edits (``None`` if none)."""

    role: str
    story: str | None
    brief: str
    cause: Cause
    sha: str | None

    def __post_init__(self) -> None:
        self.cause = Cause(self.cause)

    @property
    def label(self) -> str:
        return label(self.role, self.story)


def save_tree(git: Git, cut: Cut) -> str | None:
    """Commit every changed path, revert that commit, and return its sha."""
    paths = git.changed_paths()
    if not paths:
        return None
    step = cut.step or PO_TURN
    subject = SUBJECT.format(label=label(step.role, step.story))
    sha = git.commit(paths, f"{subject}\n\ncause: {cut.cause}")
    git.revert(sha)
    return sha


def capture(git: Git, cut: Cut) -> Interruption | None:
    """Save the tree for ``cut``; ``None`` when nothing was in flight and the tree is clean."""
    if cut.step is None and not git.changed_paths():
        return None
    step = cut.step or PO_TURN
    sha = save_tree(git, cut)
    return Interruption(step.role, step.story, step.brief, cut.cause, sha)


def note_suffix(found: Interruption | None) -> str:
    """What to append to the halt note, or nothing without saved edits."""
    if found is None or found.sha is None:
        return ""
    return NOTE_SUFFIX.format(label=found.label, sha=found.sha)


def offer(found: Interruption) -> str:
    """The brief line that offers a story's saved edits."""
    return OFFER.format(label=found.label, cause=found.cause, sha=found.sha)


def _item(found: Interruption) -> str:
    saved = SAVED.format(sha=found.sha) if found.sha else NO_EDITS
    brief = found.brief.replace("\n", "\n    ")
    return RESUME_ITEM.format(label=found.label, cause=found.cause, saved=saved, brief=brief)


def resume_section(found: list[Interruption]) -> str:
    """The PO's resume prompt section; empty with nothing interrupted."""
    if not found:
        return ""
    return "\n\n".join([RESUME_HEAD, "\n".join(_item(f) for f in found), RESUME_TAIL])
