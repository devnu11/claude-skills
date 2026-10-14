"""Opens named stages, times them and writes one ``runner-stage`` event each (s99)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
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


class StageBoard(Protocol):
    """Where open stage runs are listed while they run (HB1); ``live.Pulse`` is one."""

    def showing(self, row: dict[str, Any]) -> AbstractContextManager[None]:
        """List ``row`` for the duration of the ``with`` block."""
        ...


class Hidden:
    """A board that lists nothing (HB4)."""

    def showing(self, row: dict[str, Any]) -> AbstractContextManager[None]:
        """No listing; a ``nullcontext``."""
        return nullcontext()


HIDDEN = Hidden()


def open_row(run: stages.Run, start: Mark) -> dict[str, Any]:
    """The heartbeat's row for a stage run still open (HB2)."""
    return {
        "stage": str(run.stage.name),
        "when": str(run.stage.when),
        "attach": str(run.stage.attach),
        "description": run.stage.description,
        "story": run.place.story,
        "step": run.place.step,
        "started_at": start.at,
        "started_mono": start.mono,
        "started_slept": start.slept,
    }


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
    board: StageBoard = HIDDEN

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
            with stages.entered(run), self.board.showing(open_row(run, start)):
                yield run
        finally:
            self._emit(run, start)

    def _emit(self, run: stages.Run, start: Mark) -> None:
        seconds = awake_gap(self.clock.platform, (start, self.clock.mark()))
        event = Event(
            EventKind.RUNNER_STAGE,
            stages.RUNNER_ROLE,
            run.place.story,
            Timed(run, start, seconds).data(),
        )
        with suppress(OSError):
            self.log.emit(event)
