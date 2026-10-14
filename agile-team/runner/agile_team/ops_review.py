"""The ops-review step: DevOps's tooling verdict per AC (s115).

Pure: it imports no ``agile_team`` module at run time, so ``roles`` can use it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import Config
    from .story_spec import Read

STEP = "ops-review"


class ToolingVerdict(StrEnum):
    """How one AC is checked automatically."""

    AUTOMATIC = "automatic"
    ADDED = "added"
    MISSING = "missing"


@dataclass(frozen=True)
class ToolingRow:
    """One AC's verdict from the ops-review handoff."""

    ac: str
    verdict: ToolingVerdict
    how: str = ""
    needs: str = ""
    story: str = ""


REQUIRED: dict[ToolingVerdict, str] = {
    ToolingVerdict.AUTOMATIC: "how",
    ToolingVerdict.ADDED: "how",
    ToolingVerdict.MISSING: "needs",
}
FIELDS = ("ac", "verdict", "how", "needs", "story")
LINES: dict[ToolingVerdict, str] = {
    ToolingVerdict.AUTOMATIC: "- {ac}: automatic today: {how}",
    ToolingVerdict.ADDED: "- {ac}: added now: {how}",
    ToolingVerdict.MISSING: "- {ac}: missing: {needs} (story {story})",
}
HEADING = "## Tooling"
INTRO = "How each AC is checked automatically (DevOps, ops-review step):"
STORY_FILE = ".team/stories/{id}.md"
RECORD_SUBJECT = "chore({story}): record the tooling review in the story file"
PROBLEMS = {
    "no_row": "no row for {ac}",
    "unknown": "{ac} is not an AC of the story file",
    "repeated": "{ac} has {count} rows",
    "self": "{ac} names this story as its tooling story",
    "no_story": "{ac}'s story {story} has no file {file}",
}
BAD_LIST = "the tooling list is incomplete: {problems}. Hand off again with one row per AC"
UNFILED = (
    "devops found tooling outside its files with no story yet: {needs}. Open a story "
    "for each (open_story), then continue_story with a note naming each AC's story; "
    "devops runs ops-review again and records them"
)
PASSED = "tooling recorded: {automatic} automatic today, {added} added now, {missing} missing"
REDESIGN = "devops: the design assumes tooling that cannot exist"
NONE_LINE = "- (none)"
STORY_PROBLEM = "The story file has problems, and the gate will hold the story: {problem}"
BRIEF_INTRO = (
    "## Ops review\n\n"
    "For each AC below: can it be checked automatically with what this repo has\n"
    "today? If not, what is missing? Hand off one `tooling` row per AC (your role\n"
    'file\'s "Ops review" section says how).'
)
TABLE_HEAD = "| AC | Environment | Criterion |\n|---|---|---|"


def row_form(value: Any) -> bool:
    """Whether one raw row is well formed (H1)."""
    if not isinstance(value, dict):
        return False
    if not all(isinstance(value.get(f, ""), str) for f in FIELDS):
        return False
    verdicts = {v.value: v for v in ToolingVerdict}
    verdict = verdicts.get(value.get("verdict"))
    return bool(value.get("ac")) and verdict is not None and bool(value.get(REQUIRED[verdict]))


def rows_form(value: Any) -> bool:
    """Whether ``value`` is a list of well-formed rows (absent = [])."""
    return isinstance(value, list) and all(row_form(r) for r in value)


def adds(value: Any) -> bool:
    """Whether any raw row has verdict ``added``."""
    return any(r.get("verdict") == ToolingVerdict.ADDED for r in value)


def rows_of(value: Any) -> list[ToolingRow]:
    """The parsed rows of an already-checked raw list."""
    return [
        ToolingRow(
            r["ac"],
            ToolingVerdict(r["verdict"]),
            r.get("how", ""),
            r.get("needs", ""),
            r.get("story", ""),
        )
        for r in value
    ]


def problems(ac_ids: tuple[str, ...], rows: list[ToolingRow]) -> list[str]:
    """O2's coverage problems: no row, unknown AC, repeated AC (in that order)."""
    counts = Counter(r.ac for r in rows)
    fmt = PROBLEMS
    return (
        [fmt["no_row"].format(ac=a) for a in ac_ids if a not in counts]
        + [fmt["unknown"].format(ac=a) for a in counts if a not in ac_ids]
        + [fmt["repeated"].format(ac=a, count=n) for a, n in counts.items() if n > 1]
    )


def unfiled(rows: list[ToolingRow]) -> list[ToolingRow]:
    """The ``missing`` rows with no story."""
    return [r for r in rows if r.verdict is ToolingVerdict.MISSING and not r.story]


def passed_text(rows: list[ToolingRow]) -> str:
    """PASSED with the counts."""
    count = Counter(r.verdict for r in rows)
    return PASSED.format(
        automatic=count[ToolingVerdict.AUTOMATIC],
        added=count[ToolingVerdict.ADDED],
        missing=count[ToolingVerdict.MISSING],
    )


def unfiled_text(rows: list[ToolingRow]) -> str:
    """UNFILED with ``AC2: <needs>`` items joined by ``; ``."""
    return UNFILED.format(needs="; ".join(f"{r.ac}: {r.needs}" for r in unfiled(rows)))


def section(rows: list[ToolingRow]) -> str:
    """The ``## Tooling`` section (O5), ending with a newline."""
    lines = [LINES[r.verdict].format(**vars(r)) for r in rows]
    return "\n".join([HEADING, "", INTRO, "", *lines]) + "\n"


def with_section(text: str, rows: list[ToolingRow]) -> str:
    """``text`` with its Tooling section replaced, or the section appended (O5)."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == HEADING), None)
    if start is None:
        return text.rstrip("\n") + "\n\n" + section(rows)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), None)
    tail = "" if end is None else "\n" + "".join(lines[end:])
    return "".join(lines[:start]) + section(rows) + tail


def story_file(story: str) -> str:
    """The repo-relative story file of ``story``."""
    return STORY_FILE.format(id=story)


@dataclass(frozen=True)
class Facts:
    """What the ops-review brief section shows (B1); primitives only."""

    criteria: tuple[tuple[str, str, str], ...]
    commands: tuple[tuple[str, str], ...]
    environments: tuple[tuple[str, str], ...]
    tools: tuple[str, ...]
    ci: tuple[str, ...]
    problem: str = ""


def facts(config: Config, read: Read) -> Facts:
    """Facts from the config and the story file's read."""
    criteria = read.spec.criteria if read.spec else ()
    return Facts(
        criteria=tuple((c.id, c.environment, c.text) for c in criteria),
        commands=tuple(config.toolchain.commands.items()),
        environments=tuple((e.name, e.kind) for e in config.environments),
        tools=tuple(t.name for t in config.tools),
        ci=tuple(config.toolchain.globs.get("ci", ())),
        problem=read.refusal() or "",
    )


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def _table(facts: Facts) -> str:
    if facts.problem:
        return STORY_PROBLEM.format(problem=facts.problem)
    rows = [f"| {a} | {e} | {_cell(t)} |" for a, e, t in facts.criteria]
    return "\n".join([TABLE_HEAD, *rows])


def _bullets(items: list[str]) -> str:
    return "\n".join(items) if items else NONE_LINE


def brief_section(facts: Facts) -> str:
    """The ``## Ops review`` prompt section."""
    parts = [
        ("Acceptance criteria", _table(facts)),
        ("Toolchain commands", _bullets([f"- {n}: `{c}`" for n, c in facts.commands])),
        ("Acceptance environments", _bullets([f"- {n} (kind {k})" for n, k in facts.environments])),
        ("Repo tools ([[tool]])", _bullets([f"- {t}" for t in facts.tools])),
        ("CI files", _bullets([f"- {g}" for g in facts.ci])),
    ]
    return BRIEF_INTRO + "".join(f"\n\n### {title}\n\n{body}" for title, body in parts) + "\n"
