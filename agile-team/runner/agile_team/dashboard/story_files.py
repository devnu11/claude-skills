"""Story files the dashboard may serve (s83, AC3): a fixed table of folders, by story id only."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from .. import state as state_mod
from .. import system
from ..backlog import STORY_ID
from ..config import Config

FOLDERS: dict[str, Callable[[Config], Path]] = {
    "story": lambda c: c.stories_dir,
    "design": lambda c: c.repo / c.team.docs_dir / "design",
    "review": lambda c: c.repo / ".team" / "reviews",
    "acceptance": lambda c: c.repo / ".team" / "acceptance",
}


class FileAsk(NamedTuple):
    """The kind of file and the story it belongs to."""

    kind: str
    story: str


def _file_of(config: Config, kind: str, story: str) -> Path | None:
    """The path for a kind in the table and a well-formed id (no state check)."""
    if kind not in FOLDERS or not STORY_ID.match(story):
        return None
    return FOLDERS[kind](config) / f"{story}.md"


def path_of(config: Config, ask: FileAsk) -> Path | None:
    """The file for ``ask``, or None unless kind, id and story all check out (B6)."""
    path = _file_of(config, ask.kind, ask.story)
    known = path is not None and ask.story in state_mod.load(config.run_dir).stories
    return path if known else None


def read(config: Config, ask: FileAsk) -> str | None:
    """The file's text when it is a regular file, else None."""
    path = path_of(config, ask)
    return system.read_text(path) if path and system.is_file(path) else None


def existing(config: Config, story: str) -> list[str]:
    """The kinds whose file for ``story`` is a regular file."""
    paths = {kind: _file_of(config, kind, story) for kind in FOLDERS}
    return [kind for kind, path in paths.items() if path and system.is_file(path)]
