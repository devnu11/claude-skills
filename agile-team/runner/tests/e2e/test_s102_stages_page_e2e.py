"""s102/s118 end to end: runner tools on the Flow chart, the share bar, the Time chart and readability, under node."""
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil

import pytest
from agile_team import stages

from .. import dashboard_node
from ..clock import about

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _run(body: str, view: dict | None = None) -> dict:
    """Run `body` in the page with `view` (default: the fixture) bound; it fills `out`."""
    snap = json.dumps(view or dashboard_node.fixture())
    driver = f"const view = {snap};\nconst out = {{}};\n(async () => {{\n{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


def _tools(extra: str = "") -> str:
    """JS that fills `out.tools` with `{role: {before: [stage], after: [stage]}}` from the fixture."""
    return f"""
    ui.scope = "run";
    {extra}
    const rt = roleTools(view);
    out.tools = Object.fromEntries(Object.entries(rt).map(([r, t]) => [r, {{ before: t.before.map((x) => x.stage), after: t.after.map((x) => x.stage) }}]));
    """


# ---------------------------------------------------------------- Flow chart (FC16-FC18)


def test_stage_tools_sit_under_their_roles() -> None:
    """FC16/FC17: after a step -> its role; before -> the role that starts next; boundary -> PO; checkout.* nowhere."""
    tools = _run(_tools())["tools"]
    assert tools["developer-cli"]["after"] == ["gate.tests+coverage", "stop.lint", "stop.suite"]
    assert "env.prepare" in tools["customer-proxy"]["before"]
    assert tools["product-owner"]["before"] == ["boundary.sync"]
    assert tools["integration-tester"]["after"] == ["presentation.trial"]
    assert not any("checkout." in st for t in tools.values() for st in t["before"] + t["after"])
    assert "developer-db" not in tools  # unused roles draw no tool


def test_tool_boxes_are_idle_with_runs_and_time() -> None:
    """FC17: an idle box reads `name · ↻ N · time`; a tool in no scope run reads `↻ 0`."""
    out = _run("""
    ui.scope = "run"; out.run = flowHtml(flowModel(view));
    ui.scope = "story"; ui.focus = "s3"; out.story = flowHtml(flowModel(view));
    """)
    tool = '<span class="fc-toollabel">presentation trial</span><span class="f-toolstats">'
    assert tool + " · ↻ 1 · 30s</span>" in out["run"]
    assert 'class="fc-tool f-tools"' in out["run"] and 'class="fc-t-tool"' in out["run"]
    assert tool + " · ↻ 0</span>" in out["story"]


def test_no_events_draw_no_tool_and_an_open_row_alone_draws_one() -> None:
    """FC16/FC17: tools are drawn when an event or an open row names the stage."""
    out = _run("""
    ui.scope = "run";
    view.events = view.events.filter((e) => e.kind !== "runner-stage");
    view.heartbeat.stages = [];
    out.none = roleTools(view);
    view.heartbeat.stages = [{stage: "boundary.push", when: "after", attach: "boundary", started_at: clockNow(view) - 5, started_slept: 0}];
    out.open = roleTools(view);
    """)
    assert out["none"] == {}
    assert list(out["open"]) == ["product-owner"]
    assert out["open"]["product-owner"]["after"][0]["open"]["stage"] == "boundary.push"


def test_tool_run_numbers_in_run_story_and_sprint_scope() -> None:
    """FC15/FC17: runs and seconds per scope; the run number counts earlier runs of the stage on the story."""
    out = _run("""
    ui.scope = "run"; out.run = roleTools(view)["developer-cli"].after[0];
    ui.scope = "story"; ui.focus = "s3"; out.story = roleTools(view)["developer-cli"].after[0];
    ui.scope = "sprint"; ui.focus = "s1"; out.sprint = roleTools(view)["product-owner"].before[0];
    const rs = view.events.find((e) => e.id === "rs1");
    out.first = toolRunNumber(view, { stage: rs.data.stage, story: "s3" });
    view.events.push({...rs, id: "rs9", at: rs.at + 5, data: {...rs.data, seconds: 20}});
    ui.scope = "run"; out.two = roleTools(view)["developer-cli"].after[0];
    out.second = toolRunNumber(view, { stage: rs.data.stage, story: "s3" });
    """)
    assert (out["run"]["runs"], out["run"]["seconds"]) == (1, about(100))
    assert (out["story"]["runs"], out["story"]["seconds"]) == (1, about(100))
    assert (out["sprint"]["runs"], out["sprint"]["seconds"]) == (1, about(60))
    assert (out["two"]["runs"], out["two"]["seconds"]) == (2, about(120))
    assert (out["first"], out["second"]) == (2, 3)


def test_a_running_stage_becomes_a_solid_running_tool_with_a_test_caption() -> None:
    """FC18: the running tool has the run class, elapsed time, the counts caption and no `f-tools` class."""
    out = _run("""
    ui.scope = "run";
    const html = flowHtml(flowModel(view));
    out.html = html; out.caption = testsCaption(view.heartbeat.stages[0].tests);
    out.idle = (() => { view.health.level = "idle"; return flowHtml(flowModel(view)); })();
    """)
    running = re.search(
        r'<div class="fc-tool running (run\d)"[^>]*>(.*?)</div></div>|<div class="fc-tool running (run\d)"[^>]*>.*',
        out["html"],
        re.S,
    )
    assert running
    assert "▶ pytest + coverage" in out["html"]
    assert out["caption"] == "273 Pass + 32 Warn + 9 Fail / 506 Total · 3 Pending"
    assert "273 Pass" in out["html"] and "complete" in out["html"]
    tool = out["html"][out["html"].index('<div class="fc-tool running') :].split(">", 1)[0]
    assert "f-tools" not in tool
    assert "fc-tool running" not in out["idle"]


def test_stage_names_are_built_in_stage_names() -> None:
    """FC16/FC17: every stage a tool box names in the fixture is one of stages.STAGES (or a runner-tool)."""
    out = _run(
        'ui.scope = "run"; out.names = Object.values(roleTools(view)).flatMap((t) => [...t.before, ...t.after].map((x) => x.stage));'
    )
    builtin = {n.value for n in stages.STAGES}
    assert out["names"] and set(out["names"]) <= builtin


# ---------------------------------------------------------------- share bar (FC9)


def test_agent_boxes_show_model_against_tool_share() -> None:
    """FC9: developer-cli reads 15% model, 85% tools; an empty split reads `no model/tool timing yet`."""
    out = _run("""
    ui.scope = "run"; const m = flowModel(view);
    out.dev = roleBox(m, "developer-cli"); out.empty = roleBox(m, "manager");
    out.none = shareParts({model: 0, tools: 0}); out.split = shareParts({model: 3, tools: 1});
    """)
    assert "model 15%" in out["dev"] and "tools 85%" in out["dev"]
    assert "no model/tool timing yet" in out["empty"]
    assert out["none"] is None and out["split"] == {"model": 75, "tools": 25}


def test_po_share_in_run_scope_only() -> None:
    """FC8/FC9: the PO box has its share bar in Run scope, and `—` for tokens, cost and time in Story scope."""
    out = _run("""
    ui.scope = "run"; out.run = roleBox(flowModel(view), "product-owner");
    ui.scope = "story"; ui.focus = "s3"; out.story = roleBox(flowModel(view), "product-owner");
    """)
    assert "model 100%" in out["run"] and "tools 0%" in out["run"]
    assert out["story"].count('<span class="f-tokens">—</span>') == 1
    assert 'f-cost">—' in out["story"] and 'f-time">—' in out["story"]


# ---------------------------------------------------------------- Time chart


def test_time_totals_by_role() -> None:
    """TM2-TM4: the runner row, the PO's three parts; a `during` stage is left out."""
    out = _run("""
    out.before = timeTotals(view, "role");
    const rs = view.events.find((e) => e.id === "rs1");
    view.events.push({...rs, id: "rs8", data: {...rs.data, stage: "run_tests", when: "during", seconds: 500}});
    out.after = timeTotals(view, "role");
    out.work = Object.fromEntries(view.steps.filter((s) => s.ended_at && s.role !== "product-owner").map((s) => [s.role, 0]));
    for (const s of view.steps) if (s.ended_at && s.role !== "product-owner") out.work[s.role] += s.seconds ?? 0;
    """)
    t = out["before"]
    assert (t["runner"]["runs"], t["runner"]["parts"]["runner"]) == (8, pytest.approx(658.4))
    po = t["product-owner"]
    assert (
        po["turns"] == 1 and po["parts"]["model"] == about(9.5) and po["parts"]["tools"] == about(0)
    )
    assert po["parts"]["waiting"] == about(312.5) and po["seconds"] == about(322)
    for role, work in out["work"].items():
        assert t[role]["parts"]["work"] == pytest.approx(work)
    assert out["after"]["runner"] == t["runner"]


def test_time_totals_by_story() -> None:
    """TM4: s3 has runner time beside its work; the boundary and the PO turn are under (no story)."""
    t = _run('out.t = timeTotals(view, "story");')["t"]
    assert t["s3"]["parts"]["runner"] == pytest.approx(513.4) and t["s3"]["parts"]["work"] > 0
    nostory = t["(no story)"]
    assert nostory["parts"]["runner"] == 60 and nostory["turns"] == 1


def test_po_row_segments_tooltip_and_share() -> None:
    """TM5-TM7: two segments (--s1, --ink-2), the waiting note, % without waiting."""
    out = _run("""
    ui.unit = "time"; ui.group = "role";
    const rows = barRows(view);
    out.whole = rows[0].whole;
    out.shares = rows.reduce((a, r) => a + r.t.seconds - r.t.parts.waiting, 0);
    const i = rows.findIndex((r) => r.role === "product-owner");
    out.html = timeRow(rows[i], i, 1);
    out.row = rows[i].t.seconds;
    """)
    paths = re.findall(r'<path[^>]*fill="var\(([^)]+)\)"[^>]*data-tip="([^"]*)"', out["html"])
    assert [p[0] for p in paths] == ["--s1", "--ink-2"]
    assert "not in the share" in paths[0][1]
    assert out["whole"] == pytest.approx(out["shares"])
    assert "of time" in paths[0][1] and f"{(322 - 312.5) / out['whole'] * 100:.0f}%" in paths[0][1]


def test_time_legend_names_the_parts_and_drops_agent_steps_only() -> None:
    """TM8, D2: `Awake time:` and the five part labels; the old words are gone."""
    legend = _run("out.l = timeLegend();")["l"]
    assert "Awake time:" in legend
    for label in ("Agent steps", "Runner stages", "PO model", "PO tools", "PO waiting on a step"):
        assert label in legend
    assert "agent steps only" not in legend and "see A6" not in legend


# ---------------------------------------------------------------- readability

CSS = dashboard_node.dashboard_file("index.html")


def _vars(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def _theme_vars() -> dict[str, dict[str, str]]:
    light = re.search(r":root\s*\{([^}]*)\}", CSS).group(1)  # type: ignore[union-attr]
    dark_attr = re.search(r':root\[data-theme="dark"\]\s*\{([^}]*)\}', CSS).group(1)  # type: ignore[union-attr]
    dark_media = re.search(
        r'prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\s*\{([^}]*)\}',
        CSS,
    ).group(1)  # type: ignore[union-attr]
    return {
        "light": _vars(light),
        "dark": {**_vars(light), **_vars(dark_attr)},
        "dark-media": {**_vars(light), **_vars(dark_media)},
    }


def _lum(hex_: str) -> float:
    rgb = [int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _blend(fg: str, bg: str, alpha: float) -> str:
    mix = [
        round(int(fg[i : i + 2], 16) * alpha + int(bg[i : i + 2], 16) * (1 - alpha))
        for i in (1, 3, 5)
    ]
    return "#" + "".join(f"{c:02x}" for c in mix)


def test_flow_chart_stays_natural_size_and_node_colours_are_readable() -> None:
    """FC4/FC27: no scaling or compositing in the chart, #flow scrolls sideways, contrast in every theme."""
    out = _run("""
    ui.scope = "story"; ui.focus = "s3"; out.html = flowHtml(flowModel(view)); out.text = FLOW_TEXT;
    """)
    assert not re.search(r"(?<![-\w])(opacity|filter|transform|mix-blend-mode)\s*:", out["html"])
    assert all(t["px"] >= 10 for t in out["text"].values())
    assert re.search(r"#flow\s*\{[^}]*overflow-x:\s*auto", CSS)
    for name, v in _theme_vars().items():
        assert _contrast(v["--ink"], v["--surface"]) >= 4.5, name
        assert _contrast(v["--ink-2"], v["--surface-2"]) >= 4.5, name


@pytest.mark.parametrize("unit", ["tokens", "usd", "time"])
def test_bar_chart_is_drawn_at_scale_one_with_readable_text(unit: str) -> None:
    """RD2, RD3: width equals viewBox width; every text is in TL_TEXT, >= 12 px, contrast >= 4.5 in every theme."""
    out = _run(f"""
    const els = {{ "#mix": {{}}, "#mix-legend": {{}} }};
    globalThis.document.querySelector = (q) => els[q] ?? new Proxy({{}}, {{ get: () => () => {{}}, set: () => true }});
    globalThis.$ = (q) => els[q] ?? (els[q] = {{}});
    ui.unit = "{unit}"; ui.group = "role";
    renderBars(view);
    out.html = els["#mix"].innerHTML; out.tl = TL_TEXT;
    """)
    html = out["html"]
    svg = re.search(
        r'<svg viewBox="0 0 (\d+) (\d+)" width="(\d+)" height="(\d+)" style="([^"]*)"', html
    )
    assert svg, html[:200]
    vw, vh, w, h, style = svg.groups()
    assert (vw, vh) == (w, h) and f"width:{w}px;height:{h}px;max-width:none" in style
    assert re.search(r"#mix\s*\{[^}]*overflow-x:\s*auto", CSS)
    texts = re.findall(r'<text data-text="(\w+)" style="([^"]*)"', html)
    assert texts
    themes = _theme_vars()
    for kind, style in texts:
        assert kind in out["tl"]
        size = float(re.search(r"font-size:\s*([\d.]+)px", style).group(1))  # type: ignore[union-attr]
        assert size * int(w) / int(vw) >= 12
        ink = re.search(r"var\((--[\w-]+)\)", style).group(1)  # type: ignore[union-attr]
        for name, v in themes.items():
            assert _contrast(v[ink], v["--surface"]) >= 4.5, (kind, name)
