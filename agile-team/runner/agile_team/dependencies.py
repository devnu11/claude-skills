"""Story dependencies (s86).

`depends_on` is read from the story files, validated as a graph, and used to find
what waits or ranks above its dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from . import system
from .config import Config
from .gates import FINISHED, StoryState, StoryStatus
from .priority import first_refusal, natural
from .roles import RoleError, split_frontmatter

NOT_A_LIST = "depends_on must be a list of story ids: {ids}"
SELF = "a story cannot depend on itself: {ids}"
UNKNOWN = "depends_on names unknown stories: {pairs}; open them with open_story first"
CYCLE = "depends_on has a cycle: {cycle}"
MISMATCH = (
    "{story}'s file has depends_on [{file}], not [{given}]; pass the same list, or fix the file"
)
UNMET = (
    "depends_on not done and not in the sprint: {pairs}; add those stories in the same "
    "call, or add this one once they are done"
)
WAITING ="waiting on {ids}"
WARNING = "{story} is above {dependency}, which it depends on"

Graph = dict[str, list[str]]


@dataclass(frozen=True)
class Declared:
    """What the story files say: the lists, and the ids whose file is unreadable."""

    lists: Graph
    bad: list[str]


@dataclass(frozen=True)
class Proposal:
    """`open_story`'s argument for a new story."""

    story: str
    deps: list[str]


@dataclass(frozen=True)
class Moved:
    """A queue before and after a reorder."""

    before: list[str]
    after: list[str]


def listed(value: Any) -> list[str] | None:
    """The value deduped (DP1), or None when it isn't a list of strings."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return list(dict.fromkeys(value))


def open_ids(stories: dict[str, StoryState]) -> list[str]:
    """The ids of stories that are not done."""
    return [i for i, s in stories.items() if s.status not in FINISHED]


def _file_list(config: Config, sid: str) -> list[str] | None:
    """One file's list; None when the frontmatter or the key is bad."""
    try:
        meta, _ = split_frontmatter(sid, system.read_text(config.stories_dir / f"{sid}.md"))
    except (RoleError, yaml.YAMLError):
        return None
    return listed((meta or {}).get("depends_on", []))


def declared(config: Config, ids: list[str]) -> Declared:
    """Read `depends_on` from each id's story file; missing files are skipped."""
    present = [i for i in ids if system.is_file(config.stories_dir / f"{i}.md")]
    found = {i: _file_list(config, i) for i in present}
    return Declared(
        {i: v for i, v in found.items() if v is not None},
        [i for i, v in found.items() if v is None],
    )


def graph_of(stories: dict[str, StoryState]) -> Graph:
    """Each story's state list."""
    return {i: s.depends_on for i, s in stories.items()}


def merged(stories: dict[str, StoryState], found: Declared) -> Graph:
    """The state graph with the loaded lists replacing theirs."""
    return {**graph_of(stories), **found.lists}


def _ids(ids: list[str]) -> str:
    return ", ".join(sorted(ids, key=natural))


def shape_refusal(bad: list[str]) -> str | None:
    """DP4 (a): files whose depends_on is not a list of ids."""
    return NOT_A_LIST.format(ids=_ids(bad)) if bad else None


def mismatch_refusal(proposal: Proposal, found: Declared) -> str | None:
    """DP6: the story's file lists something other than the argument."""
    file = found.lists.get(proposal.story)
    if file is None or file == proposal.deps:
        return None
    return MISMATCH.format(
        story=proposal.story, file=", ".join(file), given=", ".join(proposal.deps)
    )


def find_cycle(graph: Graph) -> list[str]:
    """DP7: the first cycle found walking depth-first in natural order, or []."""
    done: set[str] = set()

    def walk(sid: str, path: list[str]) -> list[str]:
        if sid in path:
            return [*path[path.index(sid) :], sid]
        if sid in done or sid not in graph:
            return []
        for dep in graph[sid]:
            if cycle := walk(dep, [*path, sid]):
                return cycle
        done.add(sid)
        return []

    return next((c for sid in sorted(graph, key=natural) if (c := walk(sid, []))), [])


def _self_refusal(graph: Graph) -> str | None:
    selfish = [i for i, deps in graph.items() if i in deps]
    return SELF.format(ids=_ids(selfish)) if selfish else None


def _unknown_refusal(graph: Graph, known: set[str]) -> str | None:
    pairs = [f"{i} on {d}" for i in sorted(graph, key=natural) for d in graph[i] if d not in known]
    return UNKNOWN.format(pairs=", ".join(pairs)) if pairs else None


def _cycle_refusal(graph: Graph) -> str | None:
    cycle = find_cycle(graph)
    return CYCLE.format(cycle=" -> ".join(cycle)) if cycle else None


def graph_refusal(graph: Graph, known: set[str]) -> str | None:
    """DP4 (b)-(d): self, unknown, then cycle."""
    return first_refusal(
        [
            lambda: _self_refusal(graph),
            lambda: _unknown_refusal(graph, known),
            lambda: _cycle_refusal(graph),
        ]
    )


def load_refusal(found: Declared, stories: dict[str, StoryState]) -> str | None:
    """Why this load is refused, or None."""
    return shape_refusal(found.bad) or graph_refusal(merged(stories, found), set(stories))


def apply(found: Declared, stories: dict[str, StoryState]) -> None:
    """Set each loaded story's list."""
    for sid, deps in found.lists.items():
        stories[sid].depends_on = list(deps)


def waiting_on(story: StoryState, stories: dict[str, StoryState]) -> list[str]:
    """DP8: the listed dependencies that are missing or not done."""
    return [
        d for d in story.depends_on if d not in stories or stories[d].status is not StoryStatus.DONE
    ]


@dataclass(frozen=True)
class Scope:
    """The stories, and the ids that count as being in the sprint (SA5)."""

    stories: dict[str, StoryState]
    members: frozenset[str]


def unmet_refusal(ids: list[str], scope: Scope) -> str | None:
    """SA5: ``UNMET`` naming each dependency of ``ids`` that is not done and not a member."""
    pairs = [
        f"{i} on {d}"
        for i in ids
        for d in waiting_on(scope.stories[i], scope.stories)
        if d not in scope.members
    ]
    return UNMET.format(pairs=", ".join(pairs)) if pairs else None


def above(story: StoryState, queue: list[str]) -> list[str]:
    """DP11: dependencies that rank after the story in the queue."""
    if story.id not in queue:
        return []
    at = queue.index(story.id)
    return [d for d in story.depends_on if d in queue and queue.index(d) > at]


def inversions(queue: list[str], stories: dict[str, StoryState]) -> list[tuple[str, str]]:
    """Every (story, dependency) pair where the story is queued above it."""
    return [(i, d) for i in queue if i in stories for d in above(stories[i], queue)]


def _text(pair: tuple[str, str]) -> str:
    return WARNING.format(story=pair[0], dependency=pair[1])


def warnings(moved: Moved, stories: dict[str, StoryState]) -> list[str]:
    """DP12: warnings for inversions the move created."""
    old = set(inversions(moved.before, stories))
    return [_text(p) for p in inversions(moved.after, stories) if p not in old]


def warning_texts(story: StoryState, queue: list[str]) -> list[str]:
    """DP13: one warning per dependency the story is above."""
    return [_text((story.id, d)) for d in above(story, queue)]
