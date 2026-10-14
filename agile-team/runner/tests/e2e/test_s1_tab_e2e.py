"""s1 AC5 end to end: the Requirements tab, rendered under node, from snapshot data."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

EL = """const els = {};
const el = () => ({textContent: "", innerHTML: "", title: "", hidden: false, className: "", dataset: {}, attrs: {},
  setAttribute(k, v) { this.attrs[k] = v; }, classList: {toggle() {}}});
globalThis.document.querySelector = (q) => (els[q] ??= el());
"""


def _story(sid: str, trace: str, step: str, acs: int) -> dict:
    return {
        "id": sid,
        "title": sid,
        "sprint": 1,
        "step": step,
        "status": "active",
        "trace": trace,
        "acceptance": [{"id": f"AC{i}", "text": f"text {i}"} for i in range(1, acs + 1)],
    }


def _render(stories: list[dict], covers: list[str]) -> dict:
    """Render the tab for `stories` with one active requirement covering `covers`."""
    view = dashboard_node.fixture()
    view["stories"] = stories
    view["requirements"] = [
        {
            "id": "REQ-001",
            "title": "t",
            "status": "active",
            "covers": covers,
            "text": "x",
            "history": [],
        }
    ]
    driver = f"""const view = {json.dumps(view)};
const out = {{}};
{EL}
renderTabs(view); renderRequirements(view);
out.tabs = els["#tabs"].innerHTML; out.tiles = els["#req-tiles"].innerHTML; out.matrix = els["#matrix"].innerHTML;
console.log(JSON.stringify(out));"""
    return dashboard_node.run_page(driver)


def test_exempt_story_is_not_a_gap_and_a_checked_story_is() -> None:
    """AC5: an exempt story's untraced AC reads "designed before s1" and is no gap; a checked one is."""
    out = _render(
        [_story("s7", "exempt", "implement", 2), _story("s8", "checked", "implement", 1)], []
    )
    assert out["matrix"].count("designed before s1") == 2
    assert out["matrix"].count("untraced past design") == 1
    assert '<div class="label">Gaps in sprint</div><div class="value">1</div>' in out["tiles"]
    assert 'Requirements<span class="count hot">1</span></button>' in out["tabs"]


def test_traced_ac_of_a_checked_story_counts_as_traced_not_a_gap() -> None:
    """AC5: a covered AC shows traced; with every checked AC covered the gap count is 0 and no badge."""
    out = _render(
        [_story("s8", "checked", "implement", 1), _story("s7", "exempt", "implement", 1)],
        ["s8/AC1"],
    )
    assert "traced" in out["matrix"] and "untraced past design" not in out["matrix"]
    assert '<div class="value">0</div>' in out["tiles"]
    assert "Requirements</button>" in out["tabs"]
    assert 'Criteria traced</div><div class="value">1/2' in out["tiles"]
