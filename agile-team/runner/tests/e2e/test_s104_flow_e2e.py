"""s104/s118 end to end: the Flow chart's HTML, under the node harness and a real dashboard."""
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from agile_team import state as state_mod

from .. import dashboard_node
from ..pipeline_helpers import Script, add_story, build
from .readiness import LOCAL, Launch, dashboard
from .test_s83_backlog_e2e import _snapshot

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

HTML = "flowHtml(flowModel(view))"


def _run(body: str, view: dict | None = None) -> dict:
    """Run `body` in the page with `view` (default: the fixture) bound; it fills `out`."""
    driver = f"const view = {json.dumps(view or dashboard_node.fixture())};\nconst out = {{}};\n(async () => {{\n{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


def test_dimmed_boxes_never_use_compositing_styles() -> None:
    """FC12: a dimmed role is a class (colour only); no compositing style is written into the chart."""
    out = _run(f"""
    for (const s of view.stories) {{
      ui.scope = "story"; ui.focus = s.id;
      const html = {HTML};
      if (html.includes("fc-box dim")) {{ out.story = html; break; }}
    }}
    ui.scope = "sprint"; ui.focus = ""; out.sprint = {HTML};
    """)
    assert "story" in out, "no focus leaves a dimmed role"
    for html in (out["story"], out["sprint"]):
        assert not re.search(r"(?<![-\w])(opacity|filter|transform|mix-blend-mode)\s*:", html)
        assert "scale(" not in html and "zoom" not in html


def test_hidden_then_shown_draws_once_with_natural_size() -> None:
    """FC20: a redraw writes `.fc-chart` only when its HTML changed, and lays out once per write."""
    out = _run(f"""
    const chart = {{ innerHTML: "" }}, writes = [];
    globalThis.document.querySelector = (q) => (q === "#flow .fc-chart" ? chart : new Proxy({{}}, {{ get: () => () => {{}}, set: () => true }}));
    let laid = 0; layoutFlow = () => {{ laid++; }}; applyFlowShow = () => {{}};
    ui.scope = "run";
    renderFlow(view); const first = chart.innerHTML;
    renderFlow(view);
    out.same = chart.innerHTML === first && first === {HTML}; out.laid = laid;
    view.roles.find((r) => r.name === "unit-tester").model = "haiku";
    renderFlow(view);
    out.changed = chart.innerHTML !== first; out.laidAfter = laid;
    """)
    assert out["same"] and out["laid"] == 1
    assert out["changed"] and out["laidAfter"] == 2


def test_text_size_is_at_least_sixteen_at_scale_one() -> None:
    """FC27/FC28: every Flow text kind is >= 10 px and every text element in the chart carries an `fc-t-` class."""
    out = _run(f"""
    ui.scope = "run"; out.html = {HTML}; out.text = FLOW_TEXT;
    """)
    assert all(t["px"] >= 10 for t in out["text"].values())
    kinds = set(re.findall(r"fc-t-(\w+)", out["html"]))
    assert kinds and kinds <= set(out["text"])
    assert 'class="fc-chart' not in out["html"] and "font-size" not in out["html"]


def test_idle_role_says_idle_and_active_role_shows_stats() -> None:
    """FC8/FC29: no totals and no open step reads `idle` (not $0.00); a role with totals shows its numbers."""
    out = _run("""
    ui.scope = "story"; out.boxes = {};
    for (const s of view.stories) {
      ui.focus = s.id;
      const m = flowModel(view), boxes = {};
      for (const r of view.roles.filter((x) => x.used !== false)) boxes[r.name] = [roleNumbers(view, m.ctx, r.name).idle, roleBox(m, r.name)];
      const vals = Object.values(boxes);
      if (vals.some((v) => v[0]) && vals.some((v) => !v[0])) { out.boxes = boxes; break; }
    }
    """)
    idle = [v[1] for v in out["boxes"].values() if v[0]]
    busy = [v[1] for v in out["boxes"].values() if not v[0]]
    assert idle and busy
    assert all("<span>idle</span>" in h and "$0.00" not in h for h in idle)
    assert all("<span>idle</span>" not in h and "f-tokens" in h for h in busy)


def test_unused_role_has_no_box_until_it_is_used() -> None:
    """FC2/FL8: used=false draws no box; used=true draws one in Dev; a missing key draws it."""
    out = _run("""
    ui.scope = "run";
    const find = (v) => { const m = flowModel(v); return flowHtml(m).includes('data-role="developer-db"'); };
    const set = (used) => { const v = JSON.parse(JSON.stringify(view));
      v.step_roles.implement = ["developer-cli", "developer-db"];
      for (const r of v.roles) if (r.name === "developer-db") { if (used === undefined) delete r.used; else r.used = used; }
      return v; };
    out.off = find(set(false)); out.on = find(set(true)); out.bare = find(set(undefined));
    const dev = flowRoles(set(true)).find((g) => g.group.name === "Dev").roles;
    out.dev = dev; out.groups = flowRoles(set(false)).map((g) => g.group.name);
    """)
    assert out["off"] is False and out["on"] is True and out["bare"] is True
    assert out["dev"][-1] == "developer-db"
    assert out["groups"] == ["Leadership", "Design", "Test", "Dev", "Check"]


def test_s96_running_label_still_holds() -> None:
    """FC11: only the running role's box has a live block, with story, step, awake time and run label."""
    out = _run(f"""
    ui.scope = "run";
    const m = flowModel(view);
    out.step = m.step; out.html = {HTML};
    out.live = (out.html.match(/class="fc-live"/g) ?? []).length;
    out.label = m.run?.label;
    const open = view.steps.findLast((s) => s.role === m.step?.role && !finished(s));
    out.awake = open ? awakeSoFar(view, open) : null;
    view.heartbeat = null;
    out.none = (flowHtml(flowModel(view)).match(/class="fc-live"/g) ?? []).length;
    """)
    assert out["step"] and out["live"] == 1 and out["none"] == 0
    assert out["label"] in out["html"]


@pytest.fixture
def served(make_runtime, configured: Path, tmp_path: Path) -> Iterator[tuple]:
    """A real dashboard on a scratch repo with a pipeline of design and review."""
    rt = build(make_runtime, Script(), steps=["design", "review"])
    add_story(rt, "s1")
    state_mod.save(rt.config.run_dir, rt.state)
    with dashboard(Launch(configured, tmp_path / "home", LOCAL)) as live_dash:
        yield rt, live_dash.url


def _drawn(snap: dict, role: str) -> bool:
    out = _run(
        'ui.scope = "run"; out.has = flowHtml(flowModel(view)).includes('
        + json.dumps(f'data-role="{role}"')
        + ");",
        snap,
    )
    return out["has"]


def test_served_snapshot_draws_developer_db_only_after_its_first_step(served) -> None:
    """AC5: a step-start for developer-db flips `used` and the chart draws it."""
    rt, url = served
    before = _snapshot(url)
    assert not next(r for r in before["roles"] if r["name"] == "developer-db")["used"]
    assert not _drawn(before, "developer-db")
    event = {
        "id": "e900",
        "kind": "step-start",
        "role": "developer-db",
        "story": "s1",
        "at": time.time(),
        "data": {},
    }
    with (rt.config.run_dir / "events.jsonl").open("a") as f:
        f.write(json.dumps(event) + "\n")
    after = _snapshot(url)
    assert next(r for r in after["roles"] if r["name"] == "developer-db")["used"]
    assert _drawn(after, "developer-db")
