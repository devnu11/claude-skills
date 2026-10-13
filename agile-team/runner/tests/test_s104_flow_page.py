# ruff: noqa: E501  (embedded JavaScript lines)
"""The Flow chart source and drawing, pinned at the cause (s104, FL1-FL8)."""

from __future__ import annotations

import json
import re
from typing import Any

from .dashboard_node import dashboard_file, fixture, run_page

SETUP = f"""
const FIX = {json.dumps(fixture())};
globalThis.history = {{ replaceState() {{}} }};
const viewWith = (extra) => ({{ ...FIX, ...extra }});
const lineOf = (src, needle) => src.split("\\n").find((l) => l.includes(needle)) ?? "";
const banned = /opacity|filter|transform|mix-blend-mode/;
"""


def run(driver: str) -> Any:
    return run_page(SETUP + "(async () => {\n" + driver + "\n})();")


def test_no_class_definition_composites_a_node_in_any_scope() -> None:
    result = run("""
    const out = [];
    for (const scope of ["story", "sprint", "run"]) {
      ui.scope = scope;
      for (const focus of ["", ...FIX.stories.map((s) => s.id)]) {
        ui.focus = focus;
        const src = flowSource(asOf(FIX, Infinity));
        out.push({ scope, idle: src.split("\\n").filter((l) => /^class r\\d+ idle$/.test(l)).length,
                   defs: src.split("\\n").filter((l) => l.startsWith("classDef")) });
      }
    }
    console.log(JSON.stringify(out));
    """)
    assert any(r["scope"] == "story" and r["idle"] > 0 for r in result)
    for r in result:
        assert not any(re.search(r"opacity|filter|transform|mix-blend-mode", d) for d in r["defs"])


def test_the_idle_class_only_recolours() -> None:
    [line] = run("""
    ui.scope = "story";
    console.log(JSON.stringify([lineOf(flowSource(asOf(FIX, Infinity)), "classDef idle")]));
    """)
    body = line.removeprefix("classDef idle ")
    assert sorted(p.split(":")[0] for p in body.split(",")) == ["color", "fill", "stroke"]


def test_the_chart_is_drawn_at_natural_size_with_a_16px_font() -> None:
    result = run("""
    const cfg = mermaidConfig(themeVars());
    console.log(JSON.stringify({ use: cfg.flowchart.useMaxWidth, font: cfg.themeVariables.fontSize, theme: cfg.theme }));
    """)
    assert result == {"use": False, "font": "16px", "theme": "base"}


def test_the_svg_has_no_width_cap() -> None:
    rule = re.search(r"\.flow svg \{[^}]*\}", dashboard_file("index.html"))
    assert rule and "max-width: 100%" not in rule.group(0)
    assert "max-width: none" in rule.group(0)


def test_a_hidden_flow_tab_is_drawn_once_when_shown() -> None:
    result = run("""
    const seen = { init: [], sources: [] };
    mermaidModule = Promise.resolve({
      initialize: (o) => seen.init.push(o),
      render: async (id, src) => { seen.sources.push(src); return { svg: "<svg></svg>" }; },
    });
    data.snap = FIX; ui.tab = "board";
    render();
    await new Promise((r) => setTimeout(r, 0));
    const before = { init: seen.init.length, sources: seen.sources.length };
    showTab("flow");
    await new Promise((r) => setTimeout(r, 0));
    console.log(JSON.stringify({ before, init: seen.init, sources: seen.sources }));
    """)
    assert result["before"] == {"init": 0, "sources": 0}
    [options] = result["init"]
    assert options["flowchart"]["useMaxWidth"] is False
    assert options["themeVariables"]["fontSize"] == "16px"
    [source] = result["sources"]
    assert not any(re.search(r"opacity|filter|transform|mix-blend-mode", line) for line in source.split("\n") if line.startswith("classDef"))


def test_a_role_with_no_data_reads_idle_not_zero() -> None:
    result = run("""
    ui.scope = "run";
    const ghost = { name: "ghost-role", model: "m1", provider: "anthropic", used: true };
    const view = viewWith({ roles: [...FIX.roles, ghost] });
    const src = flowSource(view);
    const totals = flowContext(view).totals;
    const withData = FIX.roles.map((r) => r.name).find((n) => totals[n] && !openStep(view, n));
    console.log(JSON.stringify({ ghost: lineOf(src, "ghost-role"), data: lineOf(src, withData + "<br/>"), withData }));
    """)
    assert "m1 · idle" in result["ghost"] and "$0.00" not in result["ghost"]
    assert result["withData"] and "idle" not in result["data"] and "$" in result["data"]


def test_unused_roles_are_not_drawn_but_roles_without_the_key_are() -> None:
    result = run("""
    const mk = (extra) => ({ name: "developer-db", model: "sonnet", provider: "anthropic", ...extra });
    const has = (r) => flowSource(viewWith({ roles: [...FIX.roles.filter((x) => x.name !== "developer-db"), r] })).split("developer-db").length - 1;
    console.log(JSON.stringify({ off: has(mk({ used: false })), on: has(mk({ used: true })), none: has(mk({})) }));
    """)
    assert result == {"off": 0, "on": 1, "none": 1}


def test_the_node_ids_follow_the_drawn_roles_only() -> None:
    result = run("""
    const roles = [...FIX.roles, { name: "zz-unused", model: "m", provider: "anthropic", used: false }];
    const view = viewWith({ roles });
    console.log(JSON.stringify({ id: roleNodeId(view, "zz-unused"), po: roleNodeId(view, PO) }));
    """)
    assert result["id"] is None
