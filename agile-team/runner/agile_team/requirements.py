"""Requirement files <docs>/requirements/REQ-NNN.md: parse, check, coverage, design trace (s1)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from . import story_spec, system
from .config import REQUIREMENTS_DIR, Config
from .priority import natural
from .roles import RoleError, split_frontmatter

FILE_NAME = re.compile(r"REQ-\d{3,}\.md")
REF = re.compile(r"(s\d+)/([A-Za-z][\w.-]*)")
LINE = "{file}: {problem}"


class Status(StrEnum):
    """Whether a requirement counts toward coverage."""

    ACTIVE = "active"
    RETIRED = "retired"


class Problem(StrEnum):
    """Everything the checks can find wrong in a requirement file (T3, T4)."""

    UNREADABLE = "unreadable"
    BAD_NAME = "bad_name"
    NO_FRONTMATTER = "no_frontmatter"
    BAD_YAML = "bad_yaml"
    WRONG_ID = "wrong_id"
    NO_TITLE = "no_title"
    BAD_STATUS = "bad_status"
    BAD_COVERS = "bad_covers"
    BAD_REF = "bad_ref"
    REPEATED_REF = "repeated_ref"
    NO_TEXT = "no_text"
    DUPLICATE_ID = "duplicate_id"
    NO_STORY = "no_story"
    UNREAD_STORY = "unread_story"
    NO_AC = "no_ac"


PROBLEMS: dict[Problem, str] = {
    Problem.UNREADABLE: "cannot be read",
    Problem.BAD_NAME: "the file name must be REQ-NNN.md (REQ- and three or more digits)",
    Problem.NO_FRONTMATTER: (
        "no YAML frontmatter; start the file with --- and the keys id, title, status and covers"
    ),
    Problem.BAD_YAML: "frontmatter does not parse: {error}",
    Problem.WRONG_ID: "id is {found!r}, not {name!r} (the file name)",
    Problem.NO_TITLE: "title must be a non-empty string",
    Problem.BAD_STATUS: "status is {found!r}; use active or retired",
    Problem.BAD_COVERS: 'covers must be a list of "sN/ACk" strings',
    Problem.BAD_REF: 'covers item {n}: {found!r} is not "sN/ACk"',
    Problem.REPEATED_REF: "covers item {n}: {ref!r} is listed twice",
    Problem.NO_TEXT: "the body is empty; state the requirement in plain words",
    Problem.DUPLICATE_ID: "id {id!r} is also used by {others}",
    Problem.NO_STORY: "covers item {n}: {ref!r}: no story file for {story}",
    Problem.UNREAD_STORY: (
        "covers item {n}: {ref!r}: the story file of {story} has problems ({first})"
    ),
    Problem.NO_AC: "covers item {n}: {ref!r}: {story} has no AC {ac}; its ACs are {acs}",
}


def _line(file: str, problem: Problem, **fields: Any) -> str:
    return LINE.format(file=file, problem=PROBLEMS[problem].format(**fields))


@dataclass(frozen=True)
class Ref:
    """A reference to one AC of one story."""

    story: str
    ac: str

    def text(self) -> str:
        """The ref as written: ``s1/AC1``."""
        return f"{self.story}/{self.ac}"


def parse_ref(value: Any) -> Ref | None:
    """The ref ``value`` spells, or None unless it is a string fully matching ``sN/ACk``."""
    match = REF.fullmatch(value) if isinstance(value, str) else None
    return Ref(match.group(1), match.group(2)) if match else None


@dataclass(frozen=True)
class Source:
    """A requirement file's path and text (None: unreadable)."""

    file: str
    text: str | None


@dataclass(frozen=True)
class Requirement:
    """A clean requirement file."""

    id: str
    title: str
    status: Status
    covers: tuple[Ref, ...]
    text: str
    file: str


@dataclass(frozen=True)
class Parsed:
    """What reading one file gave: a requirement or its problem lines."""

    source: Source
    claimed: str | None = None
    requirement: Requirement | None = None
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Doc:
    """A file whose frontmatter parsed, for the per-field checks."""

    source: Source
    meta: dict[str, Any]
    body: str

    def line(self, problem: Problem, **fields: Any) -> str:
        return _line(self.source.file, problem, **fields)

    @property
    def stem(self) -> str:
        return _stem(self.source)


class _Stop(Exception):
    """The file cannot be read further; carries the one problem line."""


def _name_lines(doc: _Doc) -> list[str]:
    ok = FILE_NAME.fullmatch(PurePosixPath(doc.source.file).name)
    return [] if ok else [doc.line(Problem.BAD_NAME)]


def _id_lines(doc: _Doc) -> list[str]:
    found = doc.meta.get("id")
    return [] if found == doc.stem else [doc.line(Problem.WRONG_ID, found=found, name=doc.stem)]


def _title_lines(doc: _Doc) -> list[str]:
    title = doc.meta.get("title")
    ok = isinstance(title, str) and title.strip()
    return [] if ok else [doc.line(Problem.NO_TITLE)]


def _status_lines(doc: _Doc) -> list[str]:
    found = doc.meta.get("status")
    ok = found in [s.value for s in Status]  # a list, so unhashable YAML values compare
    return [] if ok else [doc.line(Problem.BAD_STATUS, found=found)]


def _item_lines(doc: _Doc, covers: list[Any]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for n, item in enumerate(covers, 1):
        ref = parse_ref(item)
        if ref is None:
            lines.append(doc.line(Problem.BAD_REF, n=n, found=item))
        elif ref.text() in seen:
            lines.append(doc.line(Problem.REPEATED_REF, n=n, ref=ref.text()))
        seen.add(ref.text() if ref else "")
    return lines


def _covers_lines(doc: _Doc) -> list[str]:
    covers = doc.meta.get("covers")
    if not isinstance(covers, list):
        return [doc.line(Problem.BAD_COVERS)]
    return _item_lines(doc, covers)


def _body_lines(doc: _Doc) -> list[str]:
    return [] if doc.body.strip() else [doc.line(Problem.NO_TEXT)]


_CHECKS: tuple[Callable[[_Doc], list[str]], ...] = (
    _name_lines,
    _id_lines,
    _title_lines,
    _status_lines,
    _covers_lines,
    _body_lines,
)


def _open(source: Source) -> _Doc:
    """The frontmatter and body of a readable file; raises ``_Stop`` (T3 rows 3 and 4)."""
    probe = _Doc(source, {}, "")
    try:
        meta, body = split_frontmatter(source.file, source.text or "")
    except (RoleError, yaml.YAMLError) as error:
        raise _Stop(probe.line(Problem.BAD_YAML, error=str(error).replace("\n", " "))) from error
    if meta is None:
        raise _Stop(probe.line(Problem.NO_FRONTMATTER))
    return _Doc(source, meta, body)


def _requirement(doc: _Doc) -> Requirement:
    meta = doc.meta
    covers = tuple(r for item in meta["covers"] if (r := parse_ref(item)))
    status = Status(meta["status"])
    return Requirement(meta["id"], meta["title"], status, covers, doc.body.strip(), doc.source.file)


def parse(source: Source) -> Parsed:
    """Check one file (T3): a requirement when clean, else every problem line."""
    if source.text is None:
        return Parsed(source, problems=(_line(source.file, Problem.UNREADABLE),))
    try:
        doc = _open(source)
    except _Stop as stop:
        named = _name_lines(_Doc(source, {}, ""))
        return Parsed(source, problems=(*named, str(stop)))
    problems = tuple(line for check in _CHECKS for line in check(doc))
    claimed = doc.meta.get("id")
    claimed = claimed if isinstance(claimed, str) else None
    return Parsed(source, claimed, None if problems else _requirement(doc), problems)


@dataclass(frozen=True)
class StoryAcs:
    """A story file as the requirement checks see it: its AC ids or its problems."""

    story: str
    acs: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    @classmethod
    def of(cls, story: str, read: story_spec.Read) -> StoryAcs:
        """The AC ids of a clean read, else the read's problem lines."""
        if read.spec is None:
            return cls(story, problems=read.problems)
        return cls(story, tuple(c.id for c in read.spec.criteria))


@dataclass(frozen=True)
class Found:
    """Everything the checks read: the files and the story files."""

    folder: str
    sources: tuple[Source, ...]
    stories: Mapping[str, StoryAcs]


@dataclass(frozen=True)
class Checked:
    """Parsed files with their cross-file problems added."""

    folder: str
    files: tuple[Parsed, ...]
    stories: Mapping[str, StoryAcs]

    def problems(self) -> list[str]:
        """Every problem line, files in order."""
        return [line for parsed in self.files for line in parsed.problems]

    def counting(self) -> list[Requirement]:
        """Active requirements whose file has no problem at all (T5)."""
        return [
            p.requirement
            for p in self.files
            if p.requirement and not p.problems and p.requirement.status is Status.ACTIVE
        ]

    def active(self) -> list[Requirement]:
        """Active requirements that parsed clean, whatever their cross-file problems."""
        found = (p.requirement for p in self.files)
        return [r for r in found if r and r.status is Status.ACTIVE]

    def covering(self, ref: Ref) -> list[str]:
        """Ids of the counting requirements that cover ``ref``, natural order."""
        ids = [r.id for r in self.counting() if ref in r.covers]
        return sorted(ids, key=natural)

    def touching(self, story: str) -> list[Parsed]:
        """The files whose raw text mentions ``story/``, broken or not."""
        pattern = re.compile(rf"\b{re.escape(story)}/")
        return [p for p in self.files if pattern.search(p.source.text or "")]


@dataclass(frozen=True)
class _Cross:
    """The cross-file checks (T4) over one set of parsed files."""

    parsed: tuple[Parsed, ...]
    stories: Mapping[str, StoryAcs]

    def add(self, one: Parsed) -> Parsed:
        lines = (*self._duplicates(one), *self._refs(one))
        return replace(one, problems=(*one.problems, *lines))

    def _duplicates(self, one: Parsed) -> list[str]:
        if one.claimed is None:
            return []
        others = [p.source.file for p in self.parsed if p is not one and p.claimed == one.claimed]
        if not others:
            return []
        fields = {"id": one.claimed, "others": ", ".join(others)}
        return [_line(one.source.file, Problem.DUPLICATE_ID, **fields)]

    def _refs(self, one: Parsed) -> list[str]:
        if one.requirement is None:
            return []
        found = (self._ref_line(one, n, r) for n, r in enumerate(one.requirement.covers, 1))
        return [line for line in found if line]

    def _ref_line(self, one: Parsed, n: int, ref: Ref) -> str | None:
        story = self.stories.get(ref.story)
        fields = {"n": n, "ref": ref.text(), "story": ref.story, "ac": ref.ac}
        if story is None:
            return _line(one.source.file, Problem.NO_STORY, **fields)
        if story.problems:
            fields["first"] = story.problems[0]
            return _line(one.source.file, Problem.UNREAD_STORY, **fields)
        if ref.ac not in story.acs:
            fields["acs"] = ", ".join(story.acs)
            return _line(one.source.file, Problem.NO_AC, **fields)
        return None


def check(found: Found) -> Checked:
    """Parse every file, then add the cross-file problems (T4)."""
    parsed = tuple(parse(s) for s in found.sources)
    cross = _Cross(parsed, found.stories)
    return Checked(found.folder, tuple(cross.add(p) for p in parsed), found.stories)


def _ordered(checked: Checked) -> list[StoryAcs]:
    return sorted(checked.stories.values(), key=lambda s: natural(s.story))


def _readable(checked: Checked) -> list[StoryAcs]:
    return [s for s in _ordered(checked) if not s.problems]


def coverage(checked: Checked) -> dict[str, dict[str, list[str]]]:
    """Each readable story's AC ids to the requirement ids covering them (T7)."""
    return {
        s.story: {ac: checked.covering(Ref(s.story, ac)) for ac in s.acs}
        for s in _readable(checked)
    }


def report(checked: Checked) -> dict[str, Any]:
    """The ``requirements check`` output (T7)."""
    unreadable = {s.story: list(s.problems) for s in _ordered(checked) if s.problems}
    return {
        "problems": checked.problems(),
        "coverage": coverage(checked),
        "unreadable": unreadable,
    }


TRACE_HEAD = (
    "{story}'s ACs must be traced to active requirements in {folder}/ before design passes:"
)
UNTRACED = (
    "{ref} is covered by no active requirement; "
    "add it to an active REQ's covers or write a new REQ-NNN.md"
)


def _story_reasons(checked: Checked, story: str) -> list[str]:
    found = checked.stories.get(story)
    if found is None:
        return [f"no story file for {story}"]
    return list(found.problems)


def _untraced_reasons(checked: Checked, story: str) -> list[str]:
    found = checked.stories.get(story)
    acs = found.acs if found else ()
    refs = [Ref(story, ac).text() for ac in acs if not checked.covering(Ref(story, ac))]
    return [UNTRACED.format(ref=ref) for ref in refs]


def design_reasons(checked: Checked, story: str) -> list[str]:
    """Why ``story`` cannot pass design (T12): a head line and one ``- `` line each, or ``[]``."""
    files = [line for p in checked.touching(story) for line in p.problems]
    reasons = [*files, *_story_reasons(checked, story), *_untraced_reasons(checked, story)]
    if not reasons:
        return []
    head = TRACE_HEAD.format(story=story, folder=checked.folder)
    return [head, *(f"- {r}" for r in reasons)]


def _stem(source: Source) -> str:
    return PurePosixPath(source.file).stem


NUMBER = re.compile(r"REQ-(\d+)")


def parse_numbers(paths: Iterable[str]) -> set[int]:
    """The REQ numbers among the paths' stems (``ls-tree`` lines or file names)."""
    matches = (NUMBER.match(PurePosixPath(p).stem) for p in paths)
    return {int(m.group(1)) for m in matches if m}


def format_id(number: int) -> str:
    """``REQ-007`` for 7."""
    return f"REQ-{number:03d}"


def list_numbers(folder: Path) -> set[int]:
    """The REQ numbers of the files in ``folder`` (none when it is missing)."""
    return parse_numbers(p.name for p in system.glob(folder, "REQ-*.md"))


def next_id(checked: Checked) -> str:
    """One above the highest REQ number among the files' names (``REQ-001`` with none)."""
    numbers = parse_numbers(p.source.file for p in checked.files)
    return format_id(max(numbers, default=0) + 1)


@dataclass(frozen=True)
class Offer:
    """The ids a story's architect brief offers (s178)."""

    story: str
    next_free: str
    first: str
    last: str


COVERAGE_HEAD = (
    "## Requirements\n\n"
    "The story's ACs and the active requirements that cover them (`{folder}/`). "
    "Cite these ids in your findings.\n\n"
)
INDEX_HEAD = (
    "Active requirements (add the story's ACs to one's `covers`, "
    "or write {next}.md, the next free id):\n\n"
)
OFFER_HEAD = (
    "Active requirements (add the story's ACs to one's `covers`, "
    "or write {next_free}.md, the next free id; this story's ids are {first} to {last}, "
    "and an id outside them is checked at the design gate):\n\n"
)
UNREAD_LINE = "- the story file has problems; see the design gate"


def _coverage_line(checked: Checked, ref: Ref) -> str:
    by_id = {r.id: r for r in checked.counting()}
    ids = checked.covering(ref)
    names = ", ".join(f"{i} ({by_id[i].title})" for i in ids)
    return f"- {ref.ac}: {names or 'untraced'}"


def coverage_section(checked: Checked, story: str) -> str:
    """The ``## Requirements`` brief section with each AC's coverage (T13)."""
    found = checked.stories.get(story)
    head = COVERAGE_HEAD.format(folder=checked.folder)
    if found is None or found.problems:
        return head + UNREAD_LINE
    return head + "\n".join(_coverage_line(checked, Ref(story, ac)) for ac in found.acs)


def _index_line(requirement: Requirement) -> str:
    covers = ", ".join(r.text() for r in requirement.covers) or "no ACs yet"
    return f"- {requirement.id} {requirement.title}: {covers}"


def _format_index(checked: Checked) -> str:
    return "\n".join(_index_line(r) for r in checked.active())


def design_section(checked: Checked, story: str) -> str:
    """The coverage section plus the active requirements and the next free id (T13)."""
    head = INDEX_HEAD.format(next=next_id(checked))
    return f"{coverage_section(checked, story)}\n\n{head}{_format_index(checked)}"


def format_offer_section(checked: Checked, offer: Offer) -> str:
    """The architect's section with the story's reserved ids (s178 R7)."""
    head = OFFER_HEAD.format(next_free=offer.next_free, first=offer.first, last=offer.last)
    return f"{coverage_section(checked, offer.story)}\n\n{head}{_format_index(checked)}"


BRIEFS: dict[str, Callable[[Checked, str], str]] = {
    "architect": design_section,
    "code-reviewer": coverage_section,
    "customer-proxy": coverage_section,
}


def folder_of(config: Config) -> str:
    """The requirements folder, repo-relative POSIX."""
    return (PurePosixPath(config.team.docs_dir) / REQUIREMENTS_DIR).as_posix()


def _read(config: Config, path: Any) -> Source:
    file = path.relative_to(config.repo).as_posix()
    try:
        return Source(file, system.read_text(path))
    except (OSError, UnicodeDecodeError):
        return Source(file, None)


def sources(config: Config) -> tuple[Source, ...]:
    """The requirement files in natural order of their names."""
    paths = system.glob(config.requirements_dir, "REQ-*.md")
    ordered = sorted(paths, key=lambda p: natural(p.stem))
    return tuple(_read(config, p) for p in ordered)


def stories(config: Config) -> dict[str, StoryAcs]:
    """Every story file under the stories folder, read."""
    names = [p.stem for p in system.glob(config.stories_dir, "*.md")]
    return {n: StoryAcs.of(n, story_spec.read(config, n)) for n in names}


def load(config: Config) -> Checked:
    """Read the repo's requirement and story files and check them."""
    return check(Found(folder_of(config), sources(config), stories(config)))


def trace_reasons(config: Config, story: str) -> list[str]:
    """The design-gate reasons for ``story`` on this repo (T12)."""
    return design_reasons(load(config), story)
