"""A folder of numbered files, each published whole (s134, ADR-0069).

A writer drafts the file, then hard-links the draft to the first free
``<prefix><N><suffix>``. A link never overwrites, so two writers never get the
same number and a reader never sees half a file. Used by ``relay`` (tell),
``reorders`` and ``sharing``.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from pathlib import Path

from . import system

DRAFT = ".draft-{token}"


@dataclass(frozen=True)
class Entry:
    """One numbered file: its id (``<prefix><N>``) and its path."""

    id: str
    path: Path


@dataclass(frozen=True)
class NumberedQueue:
    """Numbered files ``<prefix><N><suffix>`` in ``folder``."""

    folder: Path
    prefix: str
    suffix: str

    def publish(self, text: str) -> Entry:
        """Write ``text`` as the next numbered file: whole, never overwriting, no draft left."""
        system.make_dirs(self.folder)
        draft = self.folder / DRAFT.format(token=system.token())
        try:
            system.write_text(draft, text)
            return self._link(draft)
        finally:
            system.remove(draft)

    def entries(self) -> list[Entry]:
        """Every numbered file in number order; other names are ignored; none without a folder."""
        if not system.is_dir(self.folder):
            return []
        return [Entry(self._id(n), path) for n, path in sorted(self._numbered())]

    def _numbered(self) -> list[tuple[int, Path]]:
        pattern = re.compile(rf"^{re.escape(self.prefix)}(\d+){re.escape(self.suffix)}$")
        matched = ((pattern.match(p.name), p) for p in system.list_dir(self.folder))
        return [(int(m[1]), p) for m, p in matched if m]

    def _next_number(self) -> int:
        return max((n for n, _ in self._numbered()), default=0) + 1

    def _id(self, n: int) -> str:
        return f"{self.prefix}{n}"

    def _at(self, n: int) -> Entry:
        return Entry(self._id(n), self.folder / f"{self._id(n)}{self.suffix}")

    def _link(self, draft: Path) -> Entry:
        for n in itertools.count(self._next_number()):
            entry = self._at(n)
            try:
                system.hard_link(entry.path, draft)
            except FileExistsError:
                continue
            return entry
        raise AssertionError("unreachable")  # pragma: no cover
