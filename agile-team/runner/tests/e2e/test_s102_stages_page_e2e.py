"""s102 end to end: runner stages on the Flow chart, the share line, the Time chart and readability, under node."""
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil

import pytest
from agile_team import stages

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

NODES = {
    "st_env": ("Customer", "Prepare env"),
    "st_gate": ("Build", "Implement gate"),
    "st_e2e": ("Verify", "E2E gate"),
    "st_boundary": ("Steering", "Boundary"),
}
FORBIDDEN = ["opacity", "filter", "transform", "mix-blend-mode", "font-size"]


def _run(body: str, view: dict | None = None) -> dict:
    """Run `body` in the page with `view` (default: the fixture) bound; it fills `out`."""
    snap = json.dumps(view or dashboard_node.fixture())
    driver = f"const view = {snap};\nconst out = {{}};\n(async () => {{\n{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


def _node_line(source: str, node_id: str) -> str:
    return next(ln for ln in source.splitlines() if ln.startswith(node_id + "{{"))


def _label(source: str, node_id: str) -> str:
    return _node_line(source, node_id)


def _block(source: str, group: str) -> list[str]:
    lines = source.splitlines()
    start = lines.index(f'subgraph grp{group}["{group}"]')
    return lines[start : lines.index("end", start)]


# ---------------------------------------------------------------- Flow chart


def test_stage_nodes_sit_in_their_groups_as_hexagons() -> None:
    """AC1, SN1-SN4: four hexagons in their subgraphs; dotted edges to their roles."""
    src = _run('ui.scope = "run"; out.src = flowSource(view);')["src"]
    for node_id, (group, label) in NODES.items():
        block = _block(src, group)
        assert any(ln.startswith(f'{node_id}{{{{"{label}<br/>') for ln in block), node_id
        assert sum(ln.startswith(node_id + "{{") for ln in src.splitlines()) == 1
    ids = dict(re.findall(r'^(r\d+)\["([\w-]+)<br/>', src, re.M))
    by_name = {v: k for k, v in ids.items()}
    dotted = [ln for ln in src.splitlines() if "-.->" in ln]
    assert dotted == [
        f"st_env -.-> {by_name['customer-proxy']}",
        f"{by_name['developer-cli']} -.-> st_gate",
        f"{by_name['integration-tester']} -.-> st_e2e",
        "po -.-> st_boundary",
    ]
    assert "developer-db" not in by_name  # unused roles draw no anchor edge


def test_stage_edges_keep_the_labelled_link_styles() -> None:
    """SN4: stage edges come last, each styled weight 1.0; labelled indices unchanged."""
    out = _run("""
    ui.scope = "run";
    const full = flowSource(view);
    const bare = structuredClone(view);
    bare.events = bare.events.filter((e) => e.kind !== "runner-stage");
    out.full = full; out.bare = flowSource(bare);
    """)
    style = lambda s: [ln for ln in s.splitlines() if ln.startswith("linkStyle")]  # noqa: E731
    full, bare = style(out["full"]), style(out["bare"])
    assert full[: len(bare)] == bare
    assert [ln.split(" ", 2)[2].split(",")[0] for ln in full[len(bare) :]] == [
        "stroke-width:1.0px"
    ] * 4
    assert len(full) == len(bare) + 4


def test_no_events_draw_no_stage_node_and_an_open_row_alone_draws_one() -> None:
    """SN2: drawn when an event or an open row names the stage."""
    out = _run("""
    ui.scope = "run";
    view.events = view.events.filter((e) => e.kind !== "runner-stage");
    view.heartbeat.stages = [];
    out.none = flowSource(view);
    view.heartbeat.stages = [{stage: "boundary.push", started_at: clockNow(view) - 5, started_slept: 0}];
    out.open = flowSource(view);
    """)
    assert "st_" not in out["none"]
    assert [n for n in NODES if f"\n{n}{{{{" in out["open"]] == ["st_boundary"]


def test_stage_node_numbers_in_run_story_and_sprint_scope() -> None:
    """SN5, SN6: last, total and runs per scope; idle nodes get the idle class."""
    out = _run("""
    ui.scope = "run"; out.run = flowSource(view);
    ui.scope = "story"; ui.focus = "s3"; out.story = flowSource(view);
    ui.scope = "sprint"; ui.focus = "s1"; out.sprint = flowSource(view);
    const rs = view.events.find((e) => e.id === "rs1");
    view.events.push({...rs, id: "rs9", at: rs.at + 5, data: {...rs.data, seconds: 20}});
    ui.scope = "run"; out.two = flowSource(view);
    """)
    run = out["run"]
    assert "last 1 min · total 1 min · 1 run" in _node_line(run, "st_gate")
    assert "last 60 s · total 60 s · 1 run" in _node_line(run, "st_boundary")
    assert "last 45 s · total 45 s · 1 run" in _node_line(run, "st_env")
    assert "last 30 s · total 30 s · 1 run" in _node_line(run, "st_e2e")
    story = out["story"]
    assert "1 run" in _node_line(story, "st_gate")
    for idle in ("st_env", "st_e2e", "st_boundary"):
        assert _node_line(story, idle).endswith('runner · idle"}}'), idle
        assert f"class {idle} idle" in story
    assert "class st_gate idle" not in story
    assert "last 60 s · total 60 s · 1 run" in _node_line(out["sprint"], "st_boundary")
    assert "last 20 s · total 2 min · 2 runs" in _node_line(out["two"], "st_gate")


def test_a_running_stage_lights_up_and_becomes_the_active_node() -> None:
    """SN7, SN8: the running line, the active halo and class; nothing when idle or in a replay."""
    out = _run("""
    ui.scope = "run";
    const act = activeStep(view.events);
    view.events.push({id: "x1", at: act.at + 1, kind: "step-end", role: act.role, story: act.story, data: {}});
    view.heartbeat.step = null; view.heartbeat.calls = [];
    view.heartbeat.stages = [{stage: "gate.tests+coverage", started_at: clockNow(view) - 41, started_slept: 0}];
    out.on = flowSource(view); out.active = activeNodeId(view);
    view.health.level = "idle";
    out.idle = flowSource(view); out.idleActive = activeNodeId(view);
    view.health.level = "green";
    view.heartbeat = null;
    out.replay = flowSource(view);
    """)
    assert "⏱ running 41 s" in _node_line(out["on"], "st_gate")
    assert out["active"] == "st_gate"
    assert "class st_gate active" in out["on"]
    assert "running" not in _node_line(out["idle"], "st_gate").split("runner")[1]
    assert out["idleActive"] == "po"
    assert "class st_gate active" not in out["idle"]
    assert "⏱ running" not in _node_line(out["replay"], "st_gate")
    assert "class st_gate active" not in out["replay"]


def test_stage_names_are_built_in_stage_names() -> None:
    """SN1: every name in STAGE_NODES is one of stages.STAGES."""
    out = _run("out.names = STAGE_NODES.flatMap((n) => n.stages);")
    builtin = {n.value for n in stages.STAGES}
    assert out["names"] and set(out["names"]) <= builtin


# ---------------------------------------------------------------- share line


def test_agent_boxes_show_model_against_tool_share() -> None:
    """SB1, SB3: developer-cli reads 15% model, 85% tools; an empty split draws no line."""
    out = _run("""
    ui.scope = "run"; out.src = flowSource(view);
    out.none = shareLine({model: 0, tools: 0});
    """)
    src = out["src"]
    ids = dict(re.findall(r'^(r\d+)\["([\w-]+)<br/>', src, re.M))
    dev = next(
        ln
        for ln in src.splitlines()
        if ln.startswith(next(k for k, v in ids.items() if v == "developer-cli") + "[")
    )
    assert "model 15% ██░░░░░░░░ tools 85%" in dev
    no_split = [ln for ln in src.splitlines() if re.match(r"r\d+\[", ln) and "model " not in ln]
    assert no_split  # roles without a split have no line
    assert out["none"] == ""


def test_po_share_in_run_scope_only() -> None:
    """SB2: the po label has the share line in Run scope and none in Story scope."""
    out = _run("""
    ui.scope = "run"; out.run = flowSource(view);
    ui.scope = "story"; ui.focus = "s3"; out.story = flowSource(view);
    """)
    po = lambda s: next(ln for ln in s.splitlines() if ln.startswith("po["))  # noqa: E731
    assert "model 100% ██████████ tools 0%" in po(out["run"])
    assert "model " not in po(out["story"])


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
    assert (t["runner"]["runs"], t["runner"]["parts"]["runner"]) == (5, 245)
    po = t["product-owner"]
    assert po["turns"] == 1 and po["parts"]["model"] == 9.5 and po["parts"]["tools"] == 0
    assert po["parts"]["waiting"] == 312.5 and po["seconds"] == 322
    for role, work in out["work"].items():
        assert t[role]["parts"]["work"] == pytest.approx(work)
    assert out["after"]["runner"] == t["runner"]


def test_time_totals_by_story() -> None:
    """TM4: s3 has runner time beside its work; the boundary and the PO turn are under (no story)."""
    t = _run('out.t = timeTotals(view, "story");')["t"]
    assert t["s3"]["parts"]["runner"] == 100 and t["s3"]["parts"]["work"] > 0
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
    """RD1: font and scale, no compositing in classDefs, contrast in every theme."""
    out = _run("""
    ui.scope = "story"; ui.focus = "s3";
    const act = activeStep(view.events);
    view.events.push({id: "x1", at: act.at + 1, kind: "step-end", role: act.role, story: act.story, data: {}});
    view.heartbeat.step = null; view.heartbeat.calls = [];
    view.heartbeat.stages = [{stage: "gate.tests+coverage", started_at: clockNow(view) - 41, started_slept: 0}];
    out.src = flowSource(view);
    out.px = FLOW_FONT_PX; out.use = mermaidConfig({}).flowchart.useMaxWidth;
    """)
    assert out["px"] >= 12 and out["use"] is False
    defs = [ln for ln in out["src"].splitlines() if ln.startswith("classDef")]
    assert any(ln.startswith("classDef idle") for ln in defs)
    for line in defs:
        assert not any(word in line for word in FORBIDDEN), line
    assert "class st_gate active" in out["src"] and re.search(r"class st_\w+ idle", out["src"])
    assert re.search(r"#flow\s*\{[^}]*overflow-x:\s*auto", CSS)
    for name, v in _theme_vars().items():
        assert _contrast(v["--ink"], v["--surface"]) >= 4.5, name
        assert _contrast(v["--ink-2"], v["--surface-2"]) >= 4.5, name
        assert _contrast(v["--ink"], _blend(v["--accent"], v["--surface"], 0x2E / 255)) >= 4.5, name


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
