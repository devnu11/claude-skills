"""s86 end to end: story files hold dependencies as data (AC4); the page shows them (AC3)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from agile_team import dependencies
from agile_team.roles import split_frontmatter

from .. import dashboard_node

STORIES = Path(__file__).resolve().parents[4] / ".team" / "stories"
PROSE = re.compile(r"(?i)\bdepends\s+on\s+s\d+")
HISTORY = {"s4", "s5", "s9", "s29", "s70", "s76", "s77", "s79", "s83", "s84", "s85"}
TABLE_M = {
    "s2": ["s1"],
    "s6": ["s1", "s2"],
    "s10": [],
    "s16": ["s1"],
    "s32": ["s31"],
    "s33": ["s31"],
    "s34": [],
    "s35": [],  # the PO dropped its met dependencies (7fb8ab6)
    "s36": ["s31"],
    "s39": [],
    "s54": [],
    "s55": [],
    "s94": ["s93"],
    "s95": ["s94"],
    "s102": ["s96", "s97", "s98", "s99"],
}


def body_of(path: Path) -> str:
    """The text after the frontmatter (some old files have frontmatter YAML cannot parse)."""
    return path.read_text().split("\n---\n", 1)[-1]


def test_only_history_stories_keep_a_prose_dependency() -> None:
    holding = {p.stem for p in STORIES.glob("s*.md") if PROSE.search(body_of(p))}
    assert holding <= HISTORY, sorted(holding - HISTORY)


def test_open_stories_declare_the_migrated_dependencies() -> None:
    for sid, expected in TABLE_M.items():
        path = STORIES / f"{sid}.md"
        if path.is_file():
            got = dependencies.listed(
                split_frontmatter(sid, path.read_text())[0].get("depends_on", [])
            )
            assert got == expected, sid


# ----- the page under node (DP14) -------------------------------------------------------------


def _page(driver: str) -> object:
    """Run `driver` after the page's script and return its JSON output."""
    source = "\n".join([dashboard_node.PRELUDE, dashboard_node.page_script(), driver])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.js"
        path.write_text(source, encoding="utf-8")
        done = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

SETUP = f"""
const snap = {json.dumps(dashboard_node.fixture())};
data.snap = normalize(snap);
const view = asOf(data.snap, Infinity);
data.view = view;
const story = (id) => view.stories.find((s) => s.id === id);
"""


@needs_node
def test_rows_show_dependencies_and_warnings() -> None:
    """AC3: waiting and done ids, the warning pill, and nothing for a story without any."""
    out = _page(
        SETUP
        + """
    const bare = { id: "s9", depends_on: [] };
    console.log(JSON.stringify({
      s2: depsLine(story("s2")) + depWarnings(story("s2")),
      s6: depsLine(story("s6")) + depWarnings(story("s6")),
      bare: depsLine(bare) + depWarnings(bare),
      row: backlogRow(story("s2"), 1, 2, view),
    }));
    """
    )
    assert "depends on s5" in out["s2"] and "(done)" not in out["s2"]
    assert "⚠ s2 is above s5, which it depends on" in out["s2"]
    assert "depends on s1 (done)" in out["s6"] and "⚠" not in out["s6"]
    assert out["bare"] == ""
    assert "depends on s5" in out["row"] and "⚠ s2 is above s5" in out["row"]


@needs_node
def test_priority_timeline_entry_carries_the_warnings() -> None:
    """AC3: a priority event with warnings appends them to its meta and takes tone warning."""
    out = _page(
        SETUP
        + """
    const prio = view.events.filter((e) => e.kind === "priority");
    console.log(JSON.stringify(prio.map((e) => TIMELINE.priority(e))));
    """
    )
    warned = [x for x in out if "⚠ s2 is above s5, which it depends on" in x["meta"]]
    clean = [x for x in out if "⚠" not in x["meta"]]
    assert len(warned) == 1 and warned[0]["tone"] == "warning"
    assert clean and all(x.get("tone") is None for x in clean)
