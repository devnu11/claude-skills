"""Rebuild the dashboard's sample snapshot from its source sections.

`agile_team/dashboard/fixtures/snapshot.json` is generated: never edit it by
hand. To change it, edit the section file `scripts/dashboard_fixture/<key>.json`
(one JSON file per top-level key; a new or removed key also goes in
`SECTIONS`), then rebuild:

    uv run --directory agile-team/runner python scripts/make_dashboard_fixture.py

An optional argument writes somewhere else instead of the fixture. A test
fails when the committed fixture differs from a fresh rebuild.
"""

import json
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
SOURCE = SCRIPTS / "dashboard_fixture"
FIXTURE = SCRIPTS.parent / "agile_team" / "dashboard" / "fixtures" / "snapshot.json"
SECTIONS: tuple[str, ...] = (
    "generated_at", "run", "pipeline", "step_roles", "stage_descriptions",
    "stage_labels", "roles", "stories", "requirements", "reorders", "events",
    "ledger", "steps", "tools", "sleeps", "messages", "answers", "thread",
    "opinions", "upstream", "turns", "heartbeat", "health",
)  # fmt: skip


class FixtureSourceError(Exception):
    """The source directory's section files don't match SECTIONS."""


def source_problems(source: Path) -> list[str]:
    """`missing: ...` and `unknown: ...` lines (each only when non-empty)."""
    names = {p.stem for p in source.glob("*.json")}
    missing = sorted(set(SECTIONS) - names)
    unknown = sorted(names - set(SECTIONS))
    found = {"missing": missing, "unknown": unknown}
    return [f"{k}: " + ", ".join(f"{n}.json" for n in v) for k, v in found.items() if v]


def load_sections(source: Path) -> dict[str, Any]:
    """Every section, keyed and ordered as SECTIONS; raises on problems."""
    problems = source_problems(source)
    if problems:
        raise FixtureSourceError(f"{source}: " + "; ".join(problems))
    return {k: json.loads((source / f"{k}.json").read_text()) for k in SECTIONS}


def render(snapshot: dict[str, Any]) -> str:
    """The fixture text: indent 1, stdlib defaults, no trailing newline."""
    return json.dumps(snapshot, indent=1)


def build(source: Path) -> str:
    """The fixture text rebuilt from ``source``."""
    return render(load_sections(source))


def main(argv: list[str]) -> int:
    """Write the rebuilt fixture to argv[0] (default FIXTURE); 1 on a problem."""
    out = Path(argv[0]) if argv else FIXTURE
    try:
        text = build(SOURCE)
    except FixtureSourceError as err:
        print(err, file=sys.stderr)
        return 1
    out.write_text(text)
    print(f"{out}: {len(SECTIONS)} sections")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
