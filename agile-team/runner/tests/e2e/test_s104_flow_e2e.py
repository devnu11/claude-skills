"""s104 end to end: the Flow chart's source and Mermaid settings, under the node harness and a real dashboard."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from agile_team import state as state_mod

from .. import dashboard_node
from ..pipeline_helpers import Script, add_story, build
from .test_dashboard_e2e import BOOT, RUNNER
from .test_s83_backlog_e2e import _snapshot, _url

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

FORBIDDEN = ["opacity", "filter", "transform", "mix-blend-mode"]


def _run(body: str, view: dict | None = None) -> dict:
    """Run `body` in the page with `view` (default: the fixture) bound; it fills `out`."""
    driver = f"const view = {json.dumps(view or dashboard_node.fixture())};\nconst out = {{}};\n(async () => {{\n{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


def _check_classdefs(source: str) -> None:
    defs = [ln for ln in source.splitlines() if ln.startswith("classDef")]
    assert defs
    for line in defs:
        assert not any(word in line for word in FORBIDDEN), line
    idle = next(ln for ln in defs if ln.startswith("classDef idle"))
    props = [p.split(":")[0] for p in idle.split(" ", 2)[2].split(",")]
    assert props == ["fill", "stroke", "color"], idle


def test_dimmed_boxes_never_use_compositing_styles() -> None:
    """AC4 (cause): Story scope with dimmed roles and Sprint scope on the same data."""
    out = _run("""
    for (const id of Object.keys(view.run.stories ?? {}).concat(view.stories.map((s) => s.id))) {
      ui.scope = "story"; ui.focus = id;
      const src = flowSource(view);
      if (/class r\\d+ idle/.test(src)) { out.story = src; break; }
    }
    ui.scope = "sprint"; ui.focus = ""; out.sprint = flowSource(view);
    """)
    assert "story" in out, "no focus leaves a dimmed role"
    _check_classdefs(out["story"])
    _check_classdefs(out["sprint"])


def test_hidden_then_shown_draws_once_with_natural_size() -> None:
    """AC4: render while the Flow tab is hidden records nothing; showing it draws with fixed settings."""
    out = _run("""
    const rec = { init: [], src: [] };
    mermaidModule = Promise.resolve({
      initialize: (o) => rec.init.push(o),
      render: async (id, s) => { rec.src.push(s); return { svg: "<svg></svg>" }; },
    });
    globalThis.history = { replaceState() {} };
    data.snap = view; data.cursor = null;
    ui.tab = "board"; render();
    out.hidden = [rec.init.length, rec.src.length];
    showTab("flow");
    await new Promise((r) => setTimeout(r, 20));
    out.init = rec.init; out.src = rec.src;
    """)
    assert out["hidden"] == [0, 0]
    assert len(out["init"]) == 1
    assert out["init"][0]["flowchart"]["useMaxWidth"] is False
    assert out["init"][0]["themeVariables"]["fontSize"] == "16px"
    assert len(out["src"]) == 1
    _check_classdefs(out["src"][0])


def test_text_size_is_at_least_sixteen_at_scale_one() -> None:
    """AC3: font 16px and no shrink-to-fit, so box stats render at >= 12 CSS px."""
    out = _run("""
    const c = mermaidConfig(themeVars());
    out.font = parseFloat(c.themeVariables.fontSize); out.max = c.flowchart.useMaxWidth;
    """)
    assert out["font"] >= 16 and out["max"] is False


def test_idle_role_says_idle_and_active_role_shows_stats() -> None:
    """AC2: no totals and no open step reads `· idle` (not $0.00); a role with totals shows stats."""
    out = _run("""
    ui.scope = "story"; out.labels = {};
    for (const s of view.stories) {
      ui.focus = s.id;
      const ctx = flowContext(view), rows = {};
      for (const n of ringRoles(view)) rows[n] = [nodeLabel(view, n, ctx), !!ctx.totals[n], !!openStep(view, n)];
      const vals = Object.values(rows);
      if (vals.some((v) => !v[1] && !v[2]) && vals.some((v) => v[1])) { out.labels = rows; break; }
    }
    """)
    idle = [v for v in out["labels"].values() if not v[1] and not v[2]]
    busy = [v for v in out["labels"].values() if v[1]]
    assert idle and busy
    assert all("· idle" in v[0] and "$0.00" not in v[0] for v in idle)
    assert all("· idle" not in v[0] and "$" in v[0] for v in busy)


def test_unused_role_has_no_box_until_it_is_used() -> None:
    """AC5/FL8: used=false draws no node; used=true draws one; a missing key draws it."""
    out = _run("""
    const find = (v) => flowSource(v).split("\\n").filter((l) => l.includes("developer-db")).length;
    const set = (used) => { const v = JSON.parse(JSON.stringify(view));
      for (const r of v.roles) if (r.name === "developer-db") { if (used === undefined) delete r.used; else r.used = used; }
      return v; };
    out.off = find(set(false)); out.on = find(set(true)); out.bare = find(set(undefined));
    """)
    assert out["off"] == 0 and out["on"] >= 1 and out["bare"] >= 1


def test_s96_running_label_still_holds() -> None:
    """The s96 expectations: a running role's label has `⏱ running` and a time span."""
    out = _run("""
    const v = JSON.parse(JSON.stringify(view));
    out.line = runningLine(v, "no-such-role");
    const open = v.steps.findLast((s) => !finished(s));
    out.open = open ? runningLine(v, open.role) : null;
    """)
    assert out["line"] == ""
    assert out["open"] is None or "⏱ running" in out["open"]


@pytest.fixture
def served(make_runtime, configured: Path, tmp_path: Path) -> Iterator[tuple]:
    """A real dashboard on a scratch repo with a pipeline of design and review."""
    rt = build(make_runtime, Script(), steps=["design", "review"])
    add_story(rt, "s1")
    state_mod.save(rt.config.run_dir, rt.state)
    env = {**os.environ, "AGILE_TEAM_HOME": str(tmp_path / "home")}
    cmd = [sys.executable, "-c", BOOT, "--repo", str(configured), "dashboard"]
    cmd += ["--host", "127.0.0.1", "--port", "0", "--no-open"]
    proc = subprocess.Popen(
        cmd, cwd=RUNNER, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        yield rt, _url(proc)
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _drawn(snap: dict, role: str) -> bool:
    out = _run("out.has = flowSource(view).includes(" + json.dumps(role) + ");", snap)
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
