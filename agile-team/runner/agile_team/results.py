"""The runner's own toolchain runs, kept per story and shown in briefs (s69 B1-B6)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import system

RESULTS_DIR = "results"
RESULT_LINES = 60
SHA_CHARS = 7
RESULTS_HEAD = (
    "## Runner results\n\nThe runner ran these commands on this story; do not run them again."
)
RESULT_HEAD = "### {name}: exit {code} ({where}, at {at})"
FENCE = "```"
FAILURES_SHOWN = 10
FAILURES_HEAD = "Failing tests ({count}), first error lines:"
FAILURE_ITEM = "- {id}\n{lines}"
FAILURES_MORE = "- … and {count} more in .team/run/results/"
INDENT = "    "


@dataclass(frozen=True)
class Ran:
    """A toolchain command the runner ran on a story, as briefs show it (s69 B1)."""

    name: str
    code: int
    tail: str
    at: str = ""
    where: str = ""
    failures: dict[str, str] = field(default_factory=dict)


BRIEF_RESULTS: dict[str, tuple[str, ...]] = {
    "implement": ("test", "coverage", "suite-runs"),
    "e2e": ("suite-runs",),
    "acceptance": ("suite-runs",),
    "quality": ("coverage", "lint", "static"),
    "review": ("coverage",),
}


def result_tail(text: str) -> str:
    """The last RESULT_LINES lines (B6)."""
    return "\n".join(text.splitlines()[-RESULT_LINES:])


def _item(id: str, lines: str) -> str:
    indented = "\n".join(INDENT + x for x in lines.splitlines())
    return FAILURE_ITEM.format(id=id, lines=indented)


def failures_text(failures: dict[str, str]) -> str:
    """The head, the first FAILURES_SHOWN items and the 'more' line; "" for none (G6)."""
    if not failures:
        return ""
    shown = list(failures.items())[:FAILURES_SHOWN]
    parts = [FAILURES_HEAD.format(count=len(failures)), *(_item(i, t) for i, t in shown)]
    if len(failures) > FAILURES_SHOWN:
        parts.append(FAILURES_MORE.format(count=len(failures) - FAILURES_SHOWN))
    return "\n".join(parts)


def event_failures(found: Iterable[Ran | None]) -> dict[str, Any]:
    """A gate event's ``failures`` (merged, later runs winning) and ``failures_more`` (G7)."""
    merged: dict[str, str] = {}
    for ran in found:
        merged |= ran.failures if ran else {}
    if not merged:
        return {}
    out: dict[str, Any] = {"failures": dict(list(merged.items())[:FAILURES_SHOWN])}
    if len(merged) > FAILURES_SHOWN:
        out["failures_more"] = len(merged) - FAILURES_SHOWN
    return out


def _block(ran: Ran) -> str:
    head = RESULT_HEAD.format(name=ran.name, code=ran.code, where=ran.where, at=ran.at[:SHA_CHARS])
    block = f"{head}\n{FENCE}text\n{ran.tail}\n{FENCE}"
    return block + (f"\n{failures_text(ran.failures)}" if ran.failures else "")


def section(found: list[Ran]) -> str:
    """The brief's ``## Runner results`` section, or "" for none (B5)."""
    if not found:
        return ""
    return "\n\n".join([RESULTS_HEAD, *map(_block, found)])


class Results:
    """The latest result of each command per story, in ``<run_dir>/results/`` (B3)."""

    def __init__(self, run_dir: Path) -> None:
        self.root = run_dir / RESULTS_DIR

    def _file(self, story: str, name: str) -> Path:
        return self.root / story / f"{name}.json"

    def keep(self, story: str, ran: Ran) -> None:
        """Write ``ran`` (``asdict`` JSON), replacing the story's last run of that command."""
        path = self._file(story, ran.name)
        system.make_dirs(path.parent)
        system.write_text(path, json.dumps(asdict(ran)))

    def latest(self, story: str, name: str) -> Ran | None:
        """The kept run, or None when there is none or the file is unreadable."""
        try:
            return Ran(**json.loads(system.read_text(self._file(story, name))))
        except (OSError, ValueError, TypeError):
            return None

    def shown(self, story: str, step: str) -> list[Ran]:
        """The kept runs BRIEF_RESULTS names for ``step``, in table order."""
        found = (self.latest(story, name) for name in BRIEF_RESULTS.get(step, ()))
        return [ran for ran in found if ran]
