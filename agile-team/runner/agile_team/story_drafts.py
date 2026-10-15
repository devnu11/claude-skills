"""The liaison's story drafts: requests, checks and the file text (s135, pure).

``agile-team story`` checks a draft and queues a ``StoryRequest``; the runner checks it
again, writes ``.team/stories/<id>.md`` and commits it (``story_intake``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from . import frontmatter, roles, story_spec
from .config import STORIES_DIR
from .gates import FINISHED, StoryState
from .git_ops import Authored
from .priority import natural
from .request_files import NUMBER, STRING, BadRequest, FieldKind, Fields, bad_request


class Action(StrEnum):
    """What a request asks for."""

    NEW = "new"
    AMEND = "amend"


class Approval(StrEnum):
    """Who approved the draft."""

    HUMAN = "human"
    NONE = "none"


class Placing(StrEnum):
    """Where a new story goes."""

    CURRENT = "current"
    NEXT = "next"
    BACKLOG = "backlog"


LIAISON_AUTHOR = "Claude (agile-team liaison) <noreply@anthropic.com>"
AUTHORS: dict[Approval, str] = {Approval.HUMAN: "", Approval.NONE: LIAISON_AUTHOR}
SUBJECTS: dict[Action, str] = {
    Action.NEW: "docs({story}): created story to {title}",
    Action.AMEND: "docs({story}): amended story to {title}",
}
APPROVED: dict[Approval, str] = {
    Approval.HUMAN: "approved by the human",
    Approval.NONE: "written by the liaison alone",
}
INVOLVEMENT: dict[Approval, str] = {
    Approval.HUMAN: "approved by the human",
    Approval.NONE: "none: written and submitted by the liaison",
}
PLAN_INVOLVEMENT = "approved plan `{plan}`"
BODY = "{subject}\n\nHuman-involvement: {involvement}\nLiaison-request: {id}"
REQUEST_FIELDS: dict[str, FieldKind] = {
    "action": STRING,
    "story": STRING,
    "approved_by": STRING,
    "plan": STRING,
    "sprint": STRING,
    "after": STRING,
    "file": STRING,
    "text": STRING,
    "at": NUMBER,
}
BAD_ENUM = "field '{field}' must be one of {values}"
ALLOWED: dict[str, tuple[str, ...]] = {
    "action": tuple(a.value for a in Action),
    "approved_by": tuple(a.value for a in Approval),
    "sprint": ("", *(p.value for p in Placing)),
}

USAGE = "story new takes <file.md>; story amend takes <id> <file.md>"
QUEUED: dict[Action, str] = {
    Action.NEW: (
        'queued {id}: new story "{title}" ({approved}); the runner gives it an id and commits '
        "it between steps"
    ),
    Action.AMEND: (
        "queued {id}: new ACs for {story} ({approved}); the runner commits them between steps "
        "and sends {story} back to design; the draft's body is not used"
    ),
}
TOLD_NEW = (
    'Runner note: the liaison\'s story {id} is now {story} "{title}" ({approved}; commit '
    "{commit}), placed {placed}. Read {file}, then schedule it."
)
TOLD_AMENDED = (
    "Runner note: the liaison amended {story}'s ACs ({id}; {approved}; commit {commit}). "
    "It is back at {step} from {from_step}. Old: {old}. New: {new}. Read {file}."
)
POSTED_NEW = "Runner: story {id} is {story}, commit {commit}, placed {placed}."
POSTED_AMENDED = "Runner: story {id} amended {story}'s ACs, commit {commit}; it is back at {step}."
POSTED_REFUSED = "Runner: story {id} was refused: {reason}"
PLACE_REASON = "placed for the liaison's request {id}"
PLACED: dict[Placing, str] = {
    Placing.CURRENT: "in sprint {sprint}",
    Placing.NEXT: "in the backlog, first for the next sprint",
    Placing.BACKLOG: "in the backlog",
}
AFTER = " after {anchor}"
NOT_ADDED = "in the backlog; not added to sprint {sprint}: {refusal}"
AFTER_DROPPED = "; --after {anchor} dropped: it is {status}"
AMENDED_NOTE = (
    "The liaison amended the ACs ({id}); design against the new ACs and trace each to a "
    "requirement."
)
CANNOT_WRITE = "cannot write {file}: {problems}"
CANNOT_REWRITE = "cannot rewrite {file}'s acceptance block; fix its frontmatter"
COMMIT_FAILED = "commit failed: {error}"
CANNOT_READ = "cannot read {file}: {error}"
DEPENDS_SHAPE = "{file}: depends_on must be a list of story ids"
DEPENDS_UNKNOWN = "{file}: depends_on names unknown stories: {ids}"
EMPTY_BODY = "{file}: the body must hold the user story"
AFTER_UNKNOWN = "--after: no story '{story}'"
AFTER_FINISHED = "--after: {story} is {status}; name an open story"
PLAN_NEEDS_HUMAN = "--plan needs --approved-by human"
PLAN_MISSING = "--plan: no file {plan}"
NO_STORY = "no story '{story}'"
FINISHED_TARGET = "{story} is {status}; story amend changes open stories only"
NEW_ONLY = "--sprint and --after apply to story new only"
NO_TARGET_FRONTMATTER = "cannot amend {story}: {file} has no readable frontmatter"
TITLE_DIFFERS = "{file}: title is '{new}', not {story}'s '{old}'; story amend replaces only the ACs"
DEPENDS_DIFFERS = (
    "{file}: depends_on is [{new}], not {story}'s [{old}]; story amend replaces only the ACs"
)
SAME_ACS = "{file}: the ACs are the same as {story}'s; nothing to amend"
STORY_ID = re.compile(r"^s(\d+)$")
ACCEPTANCE = "acceptance"


@dataclass(frozen=True)
class StoryRequest:
    """A queued request; ``id`` is empty until queued."""

    id: str
    action: Action
    story: str
    approved_by: Approval
    plan: str
    sprint: str
    after: str
    file: str
    text: str
    at: float = 0.0

    def to_json(self) -> str:
        """The queued request file's text."""
        raw = {name: getattr(self, name) for name in REQUEST_FIELDS}
        enums = {"action": self.action.value, "approved_by": self.approved_by.value}
        return json.dumps(raw | enums)

    @classmethod
    def from_json(cls, rid: str, text: str) -> StoryRequest | BadRequest:
        """Read a request file, or a ``BadRequest`` naming the first problem."""
        raw = Fields(REQUEST_FIELDS).loaded(text)
        if isinstance(raw, str):
            return bad_request(rid, raw)
        if problem := _enum_problem(raw):
            return bad_request(rid, problem)
        enums = {"action": Action(raw["action"]), "approved_by": Approval(raw["approved_by"])}
        return cls(id=rid, **(raw | enums))


def _enum_problem(raw: dict[str, Any]) -> str | None:
    wrong = [f for f, allowed in ALLOWED.items() if raw[f] not in allowed]
    if not wrong:
        return None
    return BAD_ENUM.format(field=wrong[0], values=", ".join(ALLOWED[wrong[0]]))


@dataclass(frozen=True)
class Known:
    """What the checks compare a draft with."""

    environments: tuple[str, ...]
    stories: Mapping[str, StoryState]
    target_text: str | None = None


@dataclass(frozen=True)
class Draft:
    """A clean draft: its spec (story ``""``), its dependencies and its frontmatter."""

    spec: story_spec.Spec
    depends_on: tuple[str, ...]
    meta: dict[str, Any]


@dataclass(frozen=True)
class Checked:
    """The result of checking a draft: the draft, or every problem."""

    draft: Draft | None
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class Target:
    """The story a commit is about."""

    story: str
    title: str


@dataclass(frozen=True)
class _Read:
    """A draft as the checks see it."""

    request: StoryRequest
    known: Known
    read: story_spec.Read
    parsed: tuple[dict[str, Any], str] | None

    @property
    def meta(self) -> dict[str, Any]:
        """The draft's frontmatter (empty when it did not parse)."""
        return self.parsed[0] if self.parsed else {}


def _ids_of(value: Any) -> list[str] | None:
    ok = isinstance(value, list) and all(isinstance(i, str) for i in value)
    return value if ok else None


def _spec_problems(read: _Read) -> list[str]:
    return list(read.read.problems)


def _depends_problems(read: _Read) -> list[str]:
    if read.parsed is None or "depends_on" not in read.meta:
        return []
    file, ids = read.request.file, _ids_of(read.meta["depends_on"])
    if ids is None:
        return [DEPENDS_SHAPE.format(file=file)]
    unknown = sorted((i for i in ids if i not in read.known.stories), key=natural)
    return [DEPENDS_UNKNOWN.format(file=file, ids=", ".join(unknown))] if unknown else []


def _body_problems(read: _Read) -> list[str]:
    if read.parsed is None or read.parsed[1].strip():
        return []
    return [EMPTY_BODY.format(file=read.request.file)]


def _target_problems(read: _Read) -> list[str]:
    request = read.request
    story = read.known.stories.get(request.story)
    if story is None:
        return [NO_STORY.format(story=request.story)]
    if story.status in FINISHED:
        return [FINISHED_TARGET.format(story=request.story, status=story.status.value)]
    return _against_target(read)


def _against_target(read: _Read) -> list[str]:
    request, text = read.request, read.known.target_text
    old = frontmatter.parse(text) if text is not None else None
    if old is None:
        file = f"{STORIES_DIR}/{request.story}.md"
        return [NO_TARGET_FRONTMATTER.format(story=request.story, file=file)]
    if read.parsed is None:
        return []
    return [line for check in TARGET_CHECKS if (line := check(read, old[0]))]


def _title_differs(read: _Read, old: dict[str, Any]) -> str | None:
    new, was = read.meta.get("title"), old.get("title")
    if new == was:
        return None
    fields = {"file": read.request.file, "new": new, "old": was, "story": read.request.story}
    return TITLE_DIFFERS.format(**fields)


def _depends_differs(read: _Read, old: dict[str, Any]) -> str | None:
    new, was = _ids_of(read.meta.get("depends_on", [])), _ids_of(old.get("depends_on", [])) or []
    if new is None or new == was:
        return None
    fields = {"file": read.request.file, "new": ", ".join(new), "old": ", ".join(was)}
    return DEPENDS_DIFFERS.format(story=read.request.story, **fields)


def _same_acs(read: _Read, _old: dict[str, Any]) -> str | None:
    request, text = read.request, read.known.target_text or ""
    source = story_spec.Source(request.story, request.file, text)
    filed = story_spec.parse(source, read.known.environments).spec
    if filed is None or read.read.spec is None or filed.criteria != read.read.spec.criteria:
        return None
    return SAME_ACS.format(file=request.file, story=request.story)


TARGET_CHECKS: list[Callable[[_Read, dict[str, Any]], str | None]] = [
    _title_differs,
    _depends_differs,
    _same_acs,
]


def _amend_problems(read: _Read) -> list[str]:
    return _target_problems(read) if read.request.action is Action.AMEND else []


DRAFT_CHECKS: list[Callable[[_Read], list[str]]] = [
    _spec_problems,
    _depends_problems,
    _body_problems,
    _amend_problems,
]


def draft_problems(request: StoryRequest, known: Known) -> Checked:
    """Q3 items 2 to 4, plus item 6's target and frontmatter checks for an amend."""
    source = story_spec.Source("", request.file, request.text, story_spec.Kind.DRAFT)
    parsed = frontmatter.parse(request.text)
    read = _Read(request, known, story_spec.parse(source, known.environments), parsed)
    problems = tuple(line for check in DRAFT_CHECKS for line in check(read))
    if problems or read.read.spec is None or read.parsed is None:
        return Checked(None, problems)
    ids = tuple(_ids_of(read.meta.get("depends_on", [])) or [])
    return Checked(Draft(read.read.spec, ids, read.meta))


def _option_checks(request: StoryRequest, known: Known) -> list[str | None]:
    return [
        _after_problem(request, known),
        PLAN_NEEDS_HUMAN if request.plan and request.approved_by is Approval.NONE else None,
        NEW_ONLY if request.action is Action.AMEND and (request.sprint or request.after) else None,
    ]


def _after_problem(request: StoryRequest, known: Known) -> str | None:
    story = known.stories.get(request.after)
    if not request.after:
        return None
    if story is None:
        return AFTER_UNKNOWN.format(story=request.after)
    if story.status in FINISHED:
        return AFTER_FINISHED.format(story=request.after, status=story.status.value)
    return None


def option_problems(request: StoryRequest, known: Known) -> list[str]:
    """Q3 item 5 and item 6's ``--sprint``/``--after`` line; the ``--plan`` file is the CLI's."""
    return [line for line in _option_checks(request, known) if line]


def next_id(names: Iterable[str]) -> str:
    """``s<max N + 1>`` over the names like ``sN``, or ``s1``."""
    numbers = [int(m[1]) for name in names if (m := STORY_ID.match(name))]
    return f"s{max(numbers, default=0) + 1}"


def with_id(text: str, story: str) -> str:
    """``text`` with ``id: <story>`` straight after the opening ``---``."""
    return f"---\nid: {story}\n" + text.removeprefix("---\n")


def render_criteria(criteria: Sequence[story_spec.Criterion]) -> str:
    """The ``acceptance:`` block, ending with a newline."""
    rows = "".join(
        f"  - id: {json.dumps(c.id)}\n    text: {json.dumps(c.text)}\n"
        f"    environment: {json.dumps(c.environment)}\n"
        for c in criteria
    )
    return f"{ACCEPTANCE}:\n{rows}"


def criteria_data(criteria: Sequence[story_spec.Criterion]) -> list[dict[str, str]]:
    """The criteria as ``{id, text, environment}`` dicts."""
    return [{"id": c.id, "text": c.text, "environment": c.environment} for c in criteria]


def with_criteria(text: str, criteria: Sequence[story_spec.Criterion]) -> str | None:
    """``text`` with its ``acceptance`` block replaced, or None when that is unsafe."""
    parsed, match = frontmatter.parse(text), roles.FRONTMATTER.match(text)
    if parsed is None or match is None:
        return None
    head = frontmatter.without_key(match.group(1), ACCEPTANCE).rstrip("\n")
    made = f"---\n{head}\n{render_criteria(criteria)}".removesuffix("\n") + text[match.end(1) :]
    return made if _safe(made, parsed, criteria) else None


def _safe(made: str, parsed: tuple[dict[str, Any], str], criteria: Sequence[Any]) -> bool:
    again = frontmatter.parse(made)
    if again is None or again[1] != parsed[1]:
        return False
    rest = {k: v for k, v in again[0].items() if k != ACCEPTANCE}
    before = {k: v for k, v in parsed[0].items() if k != ACCEPTANCE}
    return rest == before and again[0].get(ACCEPTANCE) == criteria_data(criteria)


def involvement(request: StoryRequest) -> str:
    """The ``Human-involvement`` line's text."""
    if request.approved_by is Approval.HUMAN and request.plan:
        return PLAN_INVOLVEMENT.format(plan=request.plan)
    return INVOLVEMENT[request.approved_by]


def commit_message(request: StoryRequest, target: Target) -> Authored:
    """The commit's text and author for ``request`` about ``target``."""
    title = " ".join(target.title.split())
    subject = SUBJECTS[request.action].format(story=target.story, title=title)
    body = BODY.format(subject=subject, involvement=involvement(request), id=request.id)
    return Authored(body, AUTHORS[request.approved_by])
