"""s121 end to end: the Board shows the current sprint only; the empty Requirements tab says why."""
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

EL = """const els = {};
const el = () => ({textContent: "", innerHTML: "", title: "", hidden: false, className: "", dataset: {}, attrs: {},
  setAttribute(k, v) { this.attrs[k] = v; }, classList: {toggle() {}}});
globalThis.document.querySelector = (q) => (els[q] ??= el());
"""
REQ_DIR = "agile-team/docs/requirements"


def _run(body: str, edits: str = "") -> dict:
    """Run `body` in the page with the fixture bound as `view`; it fills `out`."""
    snap = json.dumps(dashboard_node.fixture())
    driver = f"const view = {snap};\nconst out = {{}};\n(async () => {{\n{EL}{edits}\n{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


BOARD_EDITS = """
view.run.sprint = 2;
const base = view.stories[0];
const mk = (id, sprint, status, step) => ({ ...base, id, sprint, status, step, title: "t" + id, held: null, hold: null });
view.stories = [mk("a", 2, "active", "design"), mk("b", 2, "active", "implement"), mk("c", 2, "done", "acceptance"),
  mk("d", null, "active", "design"), mk("e", 1, "done", "acceptance"), mk("f", 2, "cancelled", "design"), mk("g", 2, "active", "nope")];
view.requirements = [];
"""
BOARD_BODY = """
renderTabs(view); renderBoard(view);
out.html = els["#board"].innerHTML; out.tabs = els["#tabs"].innerHTML; out.pipeline = view.pipeline;
"""


def _board(edits: str = BOARD_EDITS) -> dict:
    return _run(BOARD_BODY, edits)


def test_ac1_no_backlog_column_and_columns_are_pipeline_then_done() -> None:
    """AC1: columns are exactly the pipeline steps then Done."""
    out = _board()
    cols = re.findall(r'<div class="col (\S+?)[ "]', out["html"])
    assert cols == [*out["pipeline"], "done"]
    assert "backlog" not in cols and "<h3>Backlog" not in out["html"]


def test_ac1_ac2_only_current_sprint_cards_and_badge_equals_cards() -> None:
    """AC1/AC2: cards a, b, c only; badge, card count and column counts agree."""
    out = _board()
    html = out["html"]
    assert re.findall(r'class="sid">#\d+ · (\w+) ', html) == ["a", "b", "c"]
    counts = [int(n) for n in re.findall(r"<h3>[^<]*<span>(\d+)</span>", html)]
    badge = re.search(
        r'data-tab="board"[^>]*>Board<span class="count[^"]*">(\d+)</span>', out["tabs"]
    )
    assert sum(counts) == 3 and badge and int(badge.group(1)) == 3
    assert "· c " in html.split('<div class="col done')[1]


def test_ac2_no_sprint_means_empty_board_and_no_badge() -> None:
    """AC2: with no current sprint nothing is on the Board and the tab has no badge."""
    out = _board(BOARD_EDITS + "view.run.sprint = null;")
    assert sum(int(n) for n in re.findall(r"<h3>[^<]*<span>(\d+)</span>", out["html"])) == 0
    assert not re.search(r'data-tab="board"[^>]*>Board<span', out["tabs"])


def _reqs(edits: str) -> dict:
    return _run(
        'renderRequirements(view); out.reqs = els["#reqs"].innerHTML; out.tiles = els["#req-tiles"].hidden; out.matrix = els["#matrix-card"].hidden;',
        edits,
    )


def test_ac4_empty_requirements_say_why_with_the_real_path() -> None:
    """AC4: one line, the config's path in <code>; tiles and matrix hidden."""
    out = _reqs(f'view.requirements = []; view.run.requirements_dir = "{REQ_DIR}";')
    assert (
        out["reqs"]
        == f'<p class="empty">No requirement files yet. They live in <code>{REQ_DIR}/REQ-NNN.md</code>; story s1 introduces them.</p>'
    )
    assert out["tiles"] is True and out["matrix"] is True


def test_ac4_message_gone_with_one_requirement() -> None:
    """AC4: with a requirement the full view renders and the message is gone."""
    out = _reqs(f'view.run.requirements_dir = "{REQ_DIR}";')
    assert "No requirement files yet" not in out["reqs"] and out["tiles"] is False


def test_ac4_older_snapshot_and_escaping() -> None:
    """ADR-0006 fallback path, and ADR-0005 escaping of the path."""
    old = _reqs("view.requirements = []; delete view.run.requirements_dir;")
    assert "<code>docs/requirements/REQ-NNN.md</code>" in old["reqs"]
    esc = _reqs('view.requirements = []; view.run.requirements_dir = "<b>x</b>";')
    assert "&lt;b&gt;" in esc["reqs"] and "<b>" not in esc["reqs"]


def test_snapshot_carries_requirements_dir_through_the_real_entry_point() -> None:
    """AC4: the shipped fixture carries the key the page reads."""
    assert dashboard_node.fixture()["run"]["requirements_dir"] == "docs/requirements"
