"""The repo's own Claude instructions (``.claude/CLAUDE.md``) as prompt text (s142, ADR-0073)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import system

INSTRUCTIONS = Path(".claude/CLAUDE.md")
OUTSIDE = "(left out: @{path} points outside the repo)"
UNREADABLE = "(left out: @{path} is not UTF-8 text)"
REPEATED = "(left out: @{path} is already included above)"
# The code alternative must come first, so an "@" inside backticks is consumed as code.
_IMPORT = re.compile(r"(?P<code>(`+).*?\2)|(?<!\S)@(?P<path>\S+)", re.DOTALL)


def repo_instructions(repo: Path) -> str:
    """``<repo>/.claude/CLAUDE.md`` with in-repo imports inlined once; "" if missing."""
    root = system.resolve(repo)
    path = system.resolve(repo / INSTRUCTIONS)
    if not (system.is_file(path) and path.is_relative_to(root)):
        return ""
    return Inliner(root).file(path)


@dataclass
class Inliner:
    """Inlines one repo's ``@path`` imports, each file at most once."""

    root: Path
    seen: set[Path] = field(default_factory=set)

    def file(self, path: Path) -> str:
        """``path``'s text (resolved, inside ``root``) with its imports replaced; marks it seen.

        Raises ``UnicodeDecodeError`` (before marking) when the file is not UTF-8.
        """
        text = _read_utf8(path)
        self.seen.add(path)
        return _IMPORT.sub(lambda m: self._replace(m, path.parent), text)

    def _replace(self, match: re.Match[str], base: Path) -> str:
        """A code match unchanged; an import through ``_import``."""
        if match.group("code"):
            return match.group(0)
        return self._import(match.group("path"), base)

    def _import(self, path: str, base: Path) -> str:
        """What replaces ``@path`` imported from directory ``base``."""
        target = _target(path, base)
        if target is None or not target.is_relative_to(self.root):
            return OUTSIDE.format(path=path)
        if not system.is_file(target):
            return f"@{path}"
        if target in self.seen:
            return REPEATED.format(path=path)
        return self._read_inline(path, target)

    def _read_inline(self, path: str, target: Path) -> str:
        """``target``'s inlined text, or the ``UNREADABLE`` note when it is not UTF-8."""
        try:
            return self.file(target).strip()
        except UnicodeDecodeError:
            return UNREADABLE.format(path=path)


def _target(path: str, base: Path) -> Path | None:
    """The resolved import target, or None for a ``~`` path (never expanded)."""
    return None if path.startswith("~") else system.resolve(base / path)


def _read_utf8(path: Path) -> str:
    """The file's text decoded as UTF-8 on every platform (never the locale's encoding)."""
    return system.read_bytes(path).decode("utf-8")
