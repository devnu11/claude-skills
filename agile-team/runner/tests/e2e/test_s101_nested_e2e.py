"""s101 end to end: a step row expands into its tool calls, under the node harness and a real dashboard."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil
import urllib.parse

import pytest

from .. import dashboard_node
from .test_s83_backlog_e2e import _call
from .test_s104_flow_e2e import served  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _run(body: str) -> dict:
    """Run `body` with `view`, `s3` and `open` (every bar key opened) bound; it fills `out`."""
    snap = dashboard_node.fixture()
    driver = f"""const snap = {json.dumps(snap)};
data.cursor = Infinity;
const view = asOf(snap, Infinity);
data.skew = view.generated_at - Date.now() / 1000;  // pin "now": the fixture's running step must not stretch with the real clock
const s3 =view.stories.find((s) => s.id === "s3");
const base = timelineModel({{ view, now: tlNow(view), open: new Set() }}, s3, "story");
const open = new Set(base.groups[0].bars.map((b) => b.key).filter(Boolean));
const out = {{}};
(async () => {{
{body}
console.log(JSON.stringify(out));
}})();"""
    return dashboard_node.run_page(driver)


def test_expanded_steps_nest_model_and_calls() -> None:
    """AC1-AC3: opened steps draw a model row, call bars in lanes, the red and hatched states."""
    out = _run("""
    ui.tlOpen = open;
    out.html = timelineHtml(view, s3);
    """)
    html = out["html"]
    assert 'data-bar="model"' in html and "data-call=" in html
    for state in ("ok", "error", "timeout", "unfinished"):
        assert f'data-outcome="{state}"' in html, state
    assert "-unfinished)" in html
    assert 'data-lane="1"' in html  # parallel calls stack
    assert "Dev: run the unit tests" in html and "uv run pytest" in html
    assert 'data-open="true"' in html


def test_collapsed_story_draws_no_calls() -> None:
    """AC1: nothing is nested until a bar is opened."""
    out = _run("""
    ui.tlOpen = new Set();
    out.html = timelineHtml(view, s3);
    """)
    assert "data-call=" not in out["html"] and 'data-bar="model"' not in out["html"]


def test_po_turn_expands_to_run_role_wait() -> None:
    """AC1, AC4: a PO turn opens to the po.run_role call."""
    out = _run("""
    ui.tlOpen = open;
    out.html = timelineHtml(view, s3);
    """)
    assert "po.run_role" in out["html"]


def test_misc_box_is_off_axis_and_lists_on_demand() -> None:
    """AC5: label, no axis position, tooltip text, and an on-demand list."""
    out = _run("""
    ui.tlOpen = open;
    const html = timelineHtml(view, s3);
    const box = /<g[^>]*data-misc="[^"]*"[\\s\\S]*?<\\/g>/.exec(html);
    out.box = box && box[0];
    out.listBefore = html.includes("data-misc-list");
    """)
    box = out["box"]
    assert box and "misc · 3 calls" in box
    assert "gathered from across the step" in box
    assert "data-from" not in box and "data-to" not in box
    assert not out["listBefore"]


def test_text_in_nested_views_is_readable() -> None:
    """AC-R: every sized text in the expanded timeline is at least 12 px at scale one."""
    out = _run("""
    ui.tlOpen = open;
    const html = timelineHtml(view, s3);
    out.sizes = [...html.matchAll(/data-text="[^"]*"[^>]*?font-size[:=]"?(\\d+(?:\\.\\d+)?)/g)].map((m) => Number(m[1]));
    """)
    assert out["sizes"] and min(out["sizes"]) >= 12


def _write_tools(rt, n: int) -> dict:
    """Write `n` short calls for one step to tools.jsonl; return the ask for them."""
    ask = {"role": "developer", "story": "s1", "step": "design", "opened_at": "1000.0"}
    rows = [
        {
            "role": "developer",
            "story": "s1",
            "step": "design",
            "opened_at": 1000.0,
            "tool": "Read",
            "tool_use_id": f"t{i}",
            "label": "Dev: Read",
            "detail": f"f{i}.py",
            "at": 1010.0 + i,
            "mono": 50.0 + i,
            "slept": 0.0,
            "seconds": 0.01,
            "ended_at": 1010.01 + i,
            "status": "ok",
        }
        for i in range(n)
    ]
    path = rt.config.run_dir / "tools.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return ask


def _get(url: str, ask: dict) -> tuple[int, bytes]:
    return _call(url, "GET", "/api/misc?" + urllib.parse.urlencode(ask))


def test_served_misc_route_lists_gathered_calls(served) -> None:  # noqa: F811
    """AC5: a real dashboard re-gathers a step's misc calls; a bad ask is 404."""
    rt, url = served
    ask = _write_tools(rt, 3)
    status, body = _get(url, ask)
    assert status == 200 and len(json.loads(body)) == 3
    assert _get(url, {**ask, "opened_at": "nope"})[0] == 404
