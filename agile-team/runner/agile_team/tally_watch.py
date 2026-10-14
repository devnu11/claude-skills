"""The runner side of the tally plugin: environment, watcher, retry (s118 R10)."""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from . import stages, system

PLUGIN = "agile_team_tally"
PLUGIN_DIR = Path(__file__).parent / "pytest_plugin"
TALLY_ENV = "AGILE_TEAM_TALLY"
TALLY_POLL_S = 0.5
PLUGIN_FAILED = re.compile(r'Error importing plugin "agile_team_tally"')


class Append(NamedTuple):
    """A value added at the end of a list-like environment variable."""

    key: str
    value: str
    sep: str

    def onto(self, base: Mapping[str, str]) -> str:
        """``base[key]``, ``sep`` and ``value``; just ``value`` when ``base`` has none."""
        old = base.get(self.key, "")
        return f"{old}{self.sep}{self.value}" if old else self.value


APPENDS = (
    Append("PYTHONPATH", str(PLUGIN_DIR), os.pathsep),
    Append("PYTEST_PLUGINS", PLUGIN, ","),
)


def plugin_env(base: Mapping[str, str], path: Path) -> dict[str, str]:
    """``base`` plus each APPENDS row and the tally file in TALLY_ENV."""
    return {**base, **{a.key: a.onto(base) for a in APPENDS}, TALLY_ENV: str(path)}


def plugin_failed(output: str) -> bool:
    """True when pytest could not import the plugin (the command then runs again without it)."""
    return PLUGIN_FAILED.search(output) is not None


@dataclass(eq=False)
class TallyWatch:
    """Reads the tally file every TALLY_POLL_S on a thread and tells the run each new record."""

    path: Path
    run: stages.Run
    last: str = ""
    stopping: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def start(self) -> None:
        """Begin watching on a daemon thread."""
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """End the thread, then look once more for the final record."""
        self.stopping.set()
        if self.thread:
            self.thread.join(TALLY_POLL_S * 4)
        self._look()

    def _watch(self) -> None:
        while not system.wait_event(self.stopping, TALLY_POLL_S):
            self._look()

    def _look(self) -> None:
        text = ""
        with suppress(OSError):
            text = system.read_text(self.path)
        if text and text != self.last:
            self.last = text
            with suppress(Exception):
                self.run.hear(text)


@contextmanager
def watching(run: stages.Run) -> Iterator[dict[str, str]]:
    """A scratch tally file watched for ``run``; yields the command's environment."""
    path = system.scratch_file("agile-team-tally-")
    watch = TallyWatch(path, run)
    watch.start()
    try:
        yield plugin_env(system.environ(), path)
    finally:
        watch.stop()
        system.remove(path)
        system.remove(path.with_name(path.name + ".tmp"))
