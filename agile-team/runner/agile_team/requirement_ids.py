"""Requirement ids across a sprint's open stories: reserve a block, find clashes (s178)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import requirements
from .gates import FINISHED, StoryState
from .workspaces import Workspaces

if TYPE_CHECKING:
    from .dispatch import Runtime

BLOCK_SIZE = 5
ON_HEAD = "{id} is already used on the sprint head"
USED_BY = "{id} is already used by {story}"
RESERVED_BY = "{id} is reserved by {story}"
CLASH_HEAD = (
    "{story} adds requirement ids that other work already holds; "
    "renumber them from the next free id your retry brief names:"
)


def list_block(first: int) -> range:
    """The numbers of a block starting at ``first`` (empty for 0)."""
    return range(first, first + BLOCK_SIZE) if first else range(0)


class RequirementIds:
    """Reserves requirement ids per story and finds clashes between open stories."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    @property
    def _folder(self) -> str:
        return requirements.folder_of(self.runtime.config)

    @property
    def _head_numbers(self) -> set[int]:
        return self._read_numbers("HEAD")

    def _read_numbers(self, ref: str) -> set[int]:
        """The REQ numbers on ``ref``; none when it is empty or gone."""
        if not ref:
            return set()
        code, out = self.runtime.main.attempt(
            "ls-tree", "--name-only", ref, "--", f"{self._folder}/"
        )
        return requirements.parse_numbers(out.split()) if code == 0 else set()

    def _find_others(self, story_id: str) -> list[StoryState]:
        state = self.runtime.state
        return [
            s
            for s in state.stories.values()
            if s.id != story_id and s.sprint == state.sprint and s.status not in FINISHED
        ]

    def _read_worktree(self, story_id: str) -> set[int]:
        path = Workspaces(self.runtime.main, self.runtime.config).get_path(story_id)
        return requirements.list_numbers(
            self.runtime.config.get_worktree_config(path).requirements_dir
        )

    def _find_written(self, other: StoryState) -> set[int]:
        return self._read_numbers(other.branch) | self._read_worktree(other.id)

    def _find_added(self, other: StoryState) -> set[int]:
        return self._find_written(other) - self._read_numbers(other.base_sha)

    def _find_taken(self, story: StoryState) -> set[int]:
        taken = self._head_numbers
        for other in self._find_others(story.id):
            taken |= self._find_written(other) | set(list_block(other.req_block))
        return taken

    @property
    def _story_numbers(self) -> set[int]:
        return requirements.list_numbers(self.runtime.config.requirements_dir)

    def reserve(self, story: StoryState) -> requirements.Offer:
        """Keep or start the story's block; the ids its architect brief offers (R6)."""
        taken = self._find_taken(story)
        if not story.req_block or taken & set(list_block(story.req_block)):
            story.req_block = max(taken, default=0) + 1
        block, own = list_block(story.req_block), self._story_numbers
        free = [n for n in block if n not in own]
        next_free = free[0] if free else max(taken | own | set(block)) + 1
        fmt = requirements.format_id
        return requirements.Offer(story.id, fmt(next_free), fmt(block[0]), fmt(block[-1]))

    def _find_holders(self, story: StoryState) -> dict[int, str]:
        mine = set(list_block(story.req_block))
        holders = {n: ON_HEAD.format(id=requirements.format_id(n)) for n in self._head_numbers}
        others = self._find_others(story.id)
        reasons = [(USED_BY, o, self._find_added(o)) for o in others]
        reasons += [(RESERVED_BY, o, set(list_block(o.req_block))) for o in others]
        fmt = requirements.format_id
        for template, other, numbers in reasons:
            found = {n: template.format(id=fmt(n), story=other.id) for n in numbers - mine}
            holders = found | holders
        return holders

    def list_clashes(self, story_id: str) -> list[str]:
        """The design gate's lines for ids the story added that other work holds (R8)."""
        story = self.runtime.state.stories.get(story_id)
        if story is None or not story.base_sha:
            return []
        added = self._story_numbers - self._read_numbers(story.base_sha)
        holders = self._find_holders(story)
        lines = [f"- {holders[n]}" for n in sorted(added) if n in holders]
        return [CLASH_HEAD.format(story=story_id), *lines] if lines else []
