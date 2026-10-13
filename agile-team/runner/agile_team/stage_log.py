"""Opens named stages, times them and writes one ``runner-stage`` event each (s99)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from . import stages
from .dashboard.step_times import Mark, Platform
from .events import Event, EventKind, EventLog
from .tool_calls import awake_gap, shown

if TYPE_CHECKING:
    from .gates import StoryState


class Marker(Protocol):
    """What a StageLog reads its clocks from; ``live.Pulse`` is one."""

    platform: Platform

    def mark(self) -> Mark:
        """The current clock reading."""
        ...


def place_of(story: StoryState | None) -> stages.Place:
    """The place a story's step runs at, or nowhere."""
    return stages.Place(story.id, story.step) if story else stages.NOWHERE


@dataclass(frozen=True)
class Timed:
    """A closed stage run with its start and awake seconds."""

    run: stages.Run
    start: Mark
    seconds: float

    def data(self) -> dict[str, Any]:
        """The event's data, keys in the documented order."""
        run = self.run
        done = run.code is None and run.raised is None
        return {
            "stage": str(run.stage.name),
            "when": str(run.stage.when),
            "attach": str(run.stage.attach),
            "step": run.place.step,
            "detail": shown(run.detail),
            "code": 0 if done else run.code,
            "raised": run.raised,
            "started_at": self.start.at,
            "started_mono": self.start.mono,
            "started_slept": self.start.slept,
            "seconds": self.seconds,
        }


@dataclass(eq=False)
class StageLog:
    """Opens named stages, times them and writes one runner-stage event each."""

    log: EventLog
    clock: Marker
    place: stages.Place = stages.NOWHERE

    @contextmanager
    def within(self, place: stages.Place) -> Iterator[None]:
        """Attach the stages opened inside to ``place``."""
        before, self.place = self.place, place
        try:
            yield
        finally:
            self.place = before

    @contextmanager
    def open(self, name: stages.Name) -> Iterator[stages.Run]:
        """Run a stage by name; one event is written when it closes."""
        start = self.clock.mark()
        run = stages.Run(stages.STAGES[name], self.place)
        try:
            with stages.entered(run):
                yield run
        finally:
            self._emit(run, start)

    def _emit(self, run: stages.Run, start: Mark) -> None:
        seconds = awake_gap(self.clock.platform, (start, self.clock.mark()))
        event = Event(EventKind.RUNNER_STAGE, stages.RUNNER_ROLE, run.place.story, Timed(run, start, seconds).data())
        with suppress(OSError):
            self.log.emit(event)
