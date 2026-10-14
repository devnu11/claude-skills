"""A story file's frontmatter: its ACs and their acceptance environments (s94 SF1-SF9)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import yaml

from . import system
from .config import Config
from .roles import RoleError, split_frontmatter


class Problem(StrEnum):
    """What can be wrong with a story file."""

    NO_FILE = "no_file"
    NO_FRONTMATTER = "no_frontmatter"
    BAD_YAML = "bad_yaml"
    WRONG_ID = "wrong_id"
    NO_TITLE = "no_title"
    NO_CRITERIA = "no_criteria"
    NOT_A_MAPPING = "not_a_mapping"
    NO_ID = "no_id"
    DUPLICATE_ID = "duplicate_id"
    NO_TEXT = "no_text"
    NO_ENVIRONMENT = "no_environment"
    UNKNOWN_ENVIRONMENT = "unknown_environment"
    NONE_CONFIGURED = "none_configured"


PROBLEMS: dict[Problem, str] = {
    Problem.NO_FILE: "no story file; write it before open_story",
    Problem.NO_FRONTMATTER: (
        "no YAML frontmatter; start the file with --- and the keys id, title and acceptance"
    ),
    Problem.BAD_YAML: "frontmatter does not parse: {error}",
    Problem.WRONG_ID: "id is {found!r}, not {story!r}",
    Problem.NO_TITLE: "title must be a non-empty string",
    Problem.NO_CRITERIA: "acceptance must be a non-empty list of {{id, text, environment}}",
    Problem.NOT_A_MAPPING: "must be a mapping with id, text and environment",
    Problem.NO_ID: "id is missing or empty",
    Problem.DUPLICATE_ID: "id is used by an earlier AC",
    Problem.NO_TEXT: "text is missing or empty",
    Problem.NO_ENVIRONMENT: "environment is missing; use one of: {names}",
    Problem.UNKNOWN_ENVIRONMENT: (
        "environment {name!r} is not a configured [[environment]]; use one of: {names}"
    ),
    Problem.NONE_CONFIGURED: (
        "environment {name!r} cannot be checked: .agile-team.toml configures no "
        "[[environment]]; ask the human to add one"
    ),
}
LINE = "{file}: {where}{problem}"
STORY_FILE_HOLD = (
    "the story file must be fixed before acceptance:\n{refusal}\n"
    "Edit the file; no state change is needed"
)


@dataclass(frozen=True)
class Criterion:
    """One acceptance criterion."""

    id: str
    text: str
    environment: str


@dataclass(frozen=True)
class Source:
    """What ``parse`` reads; ``text`` None means the file is missing or unreadable."""

    story: str
    file: str
    text: str | None


@dataclass(frozen=True)
class Spec:
    """A clean story file."""

    story: str
    title: str
    criteria: tuple[Criterion, ...]

    def environments(self, order: Sequence[str]) -> list[str]:
        """The distinct environments of the ACs, in ``order`` (config order, SF6)."""
        used = {c.environment for c in self.criteria}
        return [name for name in order if name in used]


@dataclass(frozen=True)
class Read:
    """The outcome of reading a story file: a spec, or finished problem lines."""

    spec: Spec | None = None
    problems: tuple[str, ...] = ()

    def refusal(self) -> str | None:
        """The problems as one text, or None when the file is clean."""
        return "\n".join(self.problems) or None


@dataclass(frozen=True)
class _Ctx:
    """The parts every problem line needs."""

    source: Source
    names: Sequence[str]

    def line(self, problem: Problem, where: str = "", **fields: Any) -> str:
        # Texts without fields are used as written (NO_CRITERIA keeps its literal braces).
        text = PROBLEMS[problem].format(**fields) if fields else PROBLEMS[problem]
        return LINE.format(file=self.source.file, where=where, problem=text)


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _meta(ctx: _Ctx) -> tuple[dict[str, Any] | None, str | None]:
    """Checks 1-3: the frontmatter mapping, or the one line that stops the read."""
    if ctx.source.text is None:
        return None, ctx.line(Problem.NO_FILE)
    try:
        meta, _ = split_frontmatter(ctx.source.file, ctx.source.text)
    except (RoleError, yaml.YAMLError) as exc:
        return None, ctx.line(Problem.BAD_YAML, error=str(exc))
    if meta is None:
        return None, ctx.line(Problem.NO_FRONTMATTER)
    return meta, None


def _has_criteria(meta: dict[str, Any]) -> bool:
    criteria = meta.get("acceptance")
    return isinstance(criteria, list) and bool(criteria)


def _story_problems(ctx: _Ctx, meta: dict[str, Any]) -> list[str]:
    """Checks 4-6, all reported."""
    found = []
    if meta.get("id") != ctx.source.story:
        found.append(ctx.line(Problem.WRONG_ID, found=meta.get("id"), story=ctx.source.story))
    if not _non_empty(meta.get("title")):
        found.append(ctx.line(Problem.NO_TITLE))
    if not _has_criteria(meta):
        found.append(ctx.line(Problem.NO_CRITERIA))
    return found


def _text_problem(item: dict[str, Any], _ctx: _Ctx) -> tuple[Problem, dict[str, Any]] | None:
    return None if _non_empty(item.get("text")) else (Problem.NO_TEXT, {})


def _environment_problem(item: dict[str, Any], ctx: _Ctx) -> tuple[Problem, dict[str, Any]] | None:
    name, names = item.get("environment"), ", ".join(ctx.names)
    if not _non_empty(name):
        return Problem.NO_ENVIRONMENT, {"names": names}
    if name in ctx.names:
        return None
    unknown = Problem.UNKNOWN_ENVIRONMENT if ctx.names else Problem.NONE_CONFIGURED
    return unknown, {"name": name, "names": names}


ITEM_CHECKS: list[Callable[[dict[str, Any], _Ctx], tuple[Problem, dict[str, Any]] | None]] = [
    _text_problem,
    _environment_problem,
]


def _item_problems(ctx: _Ctx, item: dict[str, Any], where: str) -> list[str]:
    checks = (check(item, ctx) for check in ITEM_CHECKS)
    return [ctx.line(p, where, **fields) for p, fields in filter(None, checks)]


def _identified(ctx: _Ctx, n: int, item: Any, seen: set[str]) -> tuple[str, list[str]]:
    """The ``where`` prefix for an item, and the id problems that stop its other checks."""
    if not isinstance(item, dict):
        return "", [ctx.line(Problem.NOT_A_MAPPING, f"item {n}: ")]
    if not _non_empty(item.get("id")):
        return "", [ctx.line(Problem.NO_ID, f"item {n}: ")]
    where = f"AC {item['id']}: "
    if item["id"] in seen:
        return where, [ctx.line(Problem.DUPLICATE_ID, where)]
    return where, []


def _all_items(ctx: _Ctx, criteria: list[Any]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for n, item in enumerate(criteria, 1):
        where, own = _identified(ctx, n, item, seen)
        found += own
        if where:
            seen.add(item["id"])
            found += _item_problems(ctx, item, where)
    return found


def parse(source: Source, names: Sequence[str]) -> Read:
    """Read a story file's text against the configured environment names (SF2, SF3)."""
    ctx = _Ctx(source, names)
    meta, stop = _meta(ctx)
    if meta is None:
        return Read(problems=(stop,) if stop else ())
    found = _story_problems(ctx, meta)
    if _has_criteria(meta):
        found += _all_items(ctx, meta["acceptance"])
    if found:
        return Read(problems=tuple(found))
    return Read(spec=_spec(source, meta))


def _spec(source: Source, meta: dict[str, Any]) -> Spec:
    criteria = tuple(Criterion(c["id"], c["text"], c["environment"]) for c in meta["acceptance"])
    return Spec(source.story, meta["title"], criteria)


def file_of(config: Config, story: str) -> str:
    """The story file's path, relative to the repo."""
    return (config.stories_dir / f"{story}.md").relative_to(config.repo).as_posix()


def read(config: Config, story: str) -> Read:
    """Read and check ``story``'s file against the configured environments."""
    file = file_of(config, story)
    try:
        text: str | None = system.read_text(config.repo / file)
    except OSError:
        text = None
    return parse(Source(story, file, text), [e.name for e in config.environments])


def environment_names(config: Config, story: str) -> list[str]:
    """The story's environments in config order; empty when the file has problems."""
    spec = read(config, story).spec
    return spec.environments([e.name for e in config.environments]) if spec else []
