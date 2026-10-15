"""Test setup: put a story into a run's state as the old ``open_story`` tool did (s135 AC5)."""

from __future__ import annotations

from dataclasses import dataclass

from agile_team.events import Event, EventKind
from agile_team.gates import StoryState


@dataclass(frozen=True)
class Opening:
    """The story to put into state."""

    id: str
    title: str
    depends_on: tuple[str, ...] = ()


def opened(runtime, opening: Opening) -> StoryState:
    """Add the story at the pipeline's first step, save, and emit ``story-opened`` (role PO)."""
    first = runtime.pipeline.first()
    given = list(opening.depends_on)
    runtime.state.stories[opening.id] = StoryState(
        opening.id, opening.title, first, depends_on=given
    )
    runtime.save()
    data = {"title": opening.title, "step": first, "depends_on": given}
    runtime.events.emit(Event(EventKind.STORY_OPENED, "product-owner", opening.id, data))
    return runtime.state.stories[opening.id]
