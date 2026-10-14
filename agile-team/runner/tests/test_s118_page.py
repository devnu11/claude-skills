"""s118: static checks of the HTML Flow chart's page source (FC4, FC12, FC24, FC26-FC28).

Behaviour checks need node and live in the e2e suite.
"""

from __future__ import annotations

import re
from importlib import resources

import pytest
from agile_team import system

PKG = resources.files("agile_team.dashboard")
PAGE = system.read_text(PKG.joinpath("index.html"))
FLOW_TAB = PAGE.split('id="tab-flow"')[1].split('id="tab-activity"')[0]

REMOVED = [
    "MERMAID_URL", "FLOW_FONT_PX", "MERMAID_OPTIONS", "mermaidConfig", "mmdText", "liveLines",
    "runningLine", "statsText", "nodeLabel", "STEER", "PHASE_ROLES", "SIDE_ROLES", "GROUP_ORDER",
    "twoWayEdge", "flowEdgeList", "flowGroupLines", "roleNodeId", "activeNodeId", "idleClassDef",
    "flowSource", "tintFill", "liveClassLines", "flowClassLines", "STAGE_NODES", "stageNodeLine",
    "addStageNodes", "SHARE_CELLS", "shareLine", "mermaidModule", "loadMermaid", "themeVars",
    "flowUnavailable", "drawFlow", "EVENT_EDGE", "findEdge", "hitEdge", "flowNodeEl", "markActive",
]  # fmt: skip
NEW_NAMES = [
    "FLOW_GROUPS", "FLOW_SKIP_STAGES", "BACK_VERDICTS", "FLOW_SHOW", "FLOW_SHOW_KEY", "FLOW_TEXT",
    "DOT_LOOKS", "flowGroup", "flowRoles", "flowModel", "roleNumbers", "shareParts", "rateSeries",
    "sparkSvg", "stepRunNumber", "runLook", "toolRunNumber", "stageRole", "roleTools",
    "testsCaption", "statusSpark", "roleBox", "toolBox", "flowHtml", "dotFor", "flowShowClasses",
    "flowTextCss", "ensureOverlay", "alignArrows", "layoutFlow", "runDot", "litPath",
    "renderFlowShow", "restoreFlowShow", "setFlowShow", "dur1",
]  # fmt: skip
SHOW_KEYS = [
    "tokens", "cost", "time", "bounces", "share", "spark", "tools", "toolstats", "legend",
]  # fmt: skip


def css_rules() -> list[tuple[str, str]]:
    """Every ``selector { body }`` of the page's style block."""
    style = PAGE.split("<style>")[1].split("</style>")[0]
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", style)]


def flow_rules() -> list[tuple[str, str]]:
    """The CSS rules whose selector names the chart."""
    named = re.compile(r"\.fc\b|\.fc-|#flow\b|#flow-show")
    return [(sel, body) for sel, body in css_rules() if named.search(sel)]


# ----- AC1: no Mermaid -----


def test_the_page_has_no_mermaid() -> None:
    assert "mermaid" not in PAGE.lower()


def test_markdown_it_is_the_only_outside_url() -> None:
    urls = re.findall(r"https?://[^\s\"'`)<>]+", PAGE)
    outside = [u for u in urls if not u.startswith("http://www.w3.org/")]
    assert outside and all("markdown-it" in u for u in outside)


@pytest.mark.parametrize("name", REMOVED)
def test_the_old_mermaid_code_is_gone(name: str) -> None:
    assert not re.search(rf"\b{re.escape(name)}\b", PAGE)


@pytest.mark.parametrize("name", NEW_NAMES)
def test_the_new_names_exist(name: str) -> None:
    assert re.search(rf"\b{re.escape(name)}\b", PAGE)


def test_old_flow_css_is_gone() -> None:
    selectors = " ".join(sel for sel, _ in css_rules())
    for old in (".flow svg", ".flow pre", ".flow-dot", ".edge-hit", ".live-halo"):
        assert old not in selectors


# ----- the tab's markup -----


def test_the_flow_tab_has_the_button_the_popover_and_no_static_legend() -> None:
    assert 'id="flow-show-btn"' in FLOW_TAB and "⚙ Show…" in FLOW_TAB
    assert 'id="flow-show"' in FLOW_TAB and "hidden" in FLOW_TAB.split('id="flow-show"')[1][:80]
    assert 'class="legend"' not in FLOW_TAB
    assert re.search(r'id="flow"[^>]*class="fc"|class="fc"[^>]*id="flow"', FLOW_TAB)


def test_the_flow_sub_text_is_the_new_one() -> None:
    assert "Who is working where. The Product Owner sends each step to a group" in FLOW_TAB
    assert "work moves left to right." in FLOW_TAB


def test_text_styles_come_from_one_style_element() -> None:
    assert 'id="fc-text"' in PAGE


# ----- FC4, FC6, FC12: nothing scales, colour only -----


def test_no_scaling_or_fading_in_any_chart_rule() -> None:
    banned = [r"\btransform\s*:", r"\bzoom\s*:", r"scale\(", r"(?<![\w-])opacity\s*:",
              r"\bfilter\s*:", r"mix-blend-mode", r"max-width:\s*100%"]  # fmt: skip
    rules = flow_rules()
    assert rules
    for sel, body in rules:
        for pattern in banned:
            assert not re.search(pattern, body), (sel, pattern)


def test_the_overlay_may_use_fill_opacity_only_as_an_attribute() -> None:
    assert "fill-opacity" not in " ".join(body for _, body in flow_rules())
    assert 'fill-opacity=".16"' in PAGE


@pytest.mark.parametrize(
    "setting", ["--group-max: 236px", "--group-min: 216px", "--gap-min: 24px", "--role-gap: 20px"]
)
def test_each_layout_setting_is_declared_once(setting: str) -> None:
    assert PAGE.count(setting) == 1
    name = setting.split(":")[0]
    assert len(re.findall(rf"{re.escape(name)}\s*:", PAGE)) == 1


def test_the_settings_sit_together_on_fc() -> None:
    body = dict(css_rules()).get(".fc", "")
    for name in ("--group-max", "--group-min", "--gap-min", "--role-gap"):
        assert name in body


def test_a_group_shrinks_between_its_bounds_and_a_gap_stretches() -> None:
    bodies = [b for _, b in flow_rules()]
    group = next(b for b in bodies if "flex: 0 1 var(--group-max)" in b)
    assert "min-width: var(--group-min)" in group
    assert any("flex: 1 0 var(--gap-min)" in b for b in bodies)
    assert "--group-w" not in PAGE


def test_the_group_bounds_are_declared_on_fc() -> None:
    assert re.search(r"--group-max:\s*236px\s*;", dict(css_rules())[".fc"])
    assert re.search(r"--group-min:\s*216px\s*;", dict(css_rules())[".fc"])


def test_the_flow_scrolls_sideways_below_the_fit_width() -> None:
    assert "overflow-x: auto" in dict(css_rules())["#flow"]


def test_units_are_separated_by_a_divider_and_the_role_gap() -> None:
    body = next(b for s, b in css_rules() if re.search(r"\.fc-unit\s*\+\s*\.fc-unit", s))
    assert "border-top: 1px solid" in body
    assert "margin-top: var(--role-gap)" in body and "padding-top: var(--role-gap)" in body


def test_the_overlay_never_takes_a_click() -> None:
    body = next(b for s, b in css_rules() if "fc-overlay" in s)
    for part in ("position: absolute", "inset: 0", "pointer-events: none", "z-index: 3"):
        assert part in body
    assert "overflow: visible" in body


def test_a_dimmed_box_is_recoloured() -> None:
    body = next(b for s, b in css_rules() if re.search(r"\.fc-box\.dim", s))
    assert "var(--surface-2)" in body


def test_the_running_box_glows_in_its_run_colour() -> None:
    assert "box-shadow: 0 0 9px color-mix(in srgb, var(--run1) 60%, transparent)" in PAGE
    for n in (1, 2, 3):
        assert re.search(rf"\.fc-box\.run{n}\b", PAGE)


# ----- FC24: settings -----


def test_every_show_row_has_a_hide_rule() -> None:
    block = PAGE.split("const FLOW_SHOW = ")[1].split("];")[0]
    assert re.findall(r'\["(\w+)",', block) == SHOW_KEYS
    for key in SHOW_KEYS:
        rule = next(b for s, b in css_rules() if f".hide-{key} .f-{key}" in s)
        assert "display: none !important" in rule


def test_the_settings_key_and_storage() -> None:
    assert 'FLOW_SHOW_KEY = "agile-team-flow-show"' in PAGE


# ----- FC26: tokens -----


TOKENS = {
    "--run1": "#2e9d5b", "--run2": "#8b5cf6", "--run3": "#e0901f", "--pass": "#2e9d5b",
    "--warn": "#c9b22c", "--skip": "#8c939d", "--fail": "var(--critical)",
    "--flow-forward": "var(--s2)",
    "--flow-model": "var(--s1)", "--flow-tools": "var(--s4)",
}  # fmt: skip


def theme_blocks() -> list[str]:
    """Bodies of the light, dark-media and dark-override ``:root`` blocks."""
    style = PAGE.split("<style>")[1]
    light = style.split(":root {")[1].split("}")[0]
    media = style.split(':root:not([data-theme="light"]) {')[1].split("}")[0]
    dark = style.split(':root[data-theme="dark"] {')[1].split("}")[0]
    return [light, media, dark]


@pytest.mark.parametrize("block", range(3))
def test_every_theme_block_declares_the_flow_tokens(block: int) -> None:
    body = theme_blocks()[block]
    for name, value in TOKENS.items():
        assert re.search(rf"{re.escape(name)}:\s*{re.escape(value)}\s*;", body), (block, name)


# ----- FC27, FC28: text from one table, measured -----


def flow_text() -> dict[str, tuple[int, str]]:
    block = PAGE.split("const FLOW_TEXT = {")[1].split("};")[0]
    found = re.findall(r'(\w+):\s*\{\s*px:\s*(\d+),\s*ink:\s*"(--[\w-]+)"\s*\}', block)
    return {kind: (int(px), ink) for kind, px, ink in found}


def test_the_text_table_has_every_kind() -> None:
    assert set(flow_text()) == {
        "name",
        "meta",
        "live",
        "tool",
        "toolRun",
        "toolDesc",
        "caption",
        "title",
        "pill",
        "legend",
        "settings",
    }
    assert flow_text()["name"][0] == 12


def test_the_tool_description_text_is_12_px_ink_2() -> None:
    assert flow_text()["toolDesc"] == (12, "--ink-2")


def test_every_text_is_at_least_10_px() -> None:
    assert all(px >= 10 for px, _ in flow_text().values())


def test_no_chart_rule_sets_text_size_or_colour() -> None:
    for sel, body in flow_rules():
        assert not re.search(r"(?<![-\w])font-size\s*:", body), sel
        if re.search(r"(?<![-\w])color\s*:", body):
            assert re.search(r"fc-t-|\.dim", sel), sel


def test_subtle_text_never_uses_muted() -> None:
    assert all(ink != "--muted" for _, ink in flow_text().values())


def channel(value: int) -> float:
    unit = value / 255
    return unit / 12.92 if unit <= 0.03928 else ((unit + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def token(body: str, name: str) -> str:
    return re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", body).group(1)  # type: ignore[union-attr]


@pytest.mark.parametrize("block", [0, 1, 2], ids=["light", "dark-media", "dark"])
def test_every_ink_has_4_5_contrast_on_boxes_and_groups(block: int) -> None:
    body = theme_blocks()[block]
    for kind, (_, ink) in flow_text().items():
        for ground in ("--surface", "--surface-2"):
            ratio = contrast(token(body, ink), token(body, ground))
            assert ratio >= 4.5, (kind, ink, ground, ratio)


def test_the_contrast_helper_knows_black_on_white() -> None:
    assert round(contrast("#000000", "#ffffff")) == 21


# ----- FC26 (round 2): the Skip grey -----


def test_skip_is_used_only_for_its_swatch_and_bar_segment() -> None:
    bodies = {sel: body for sel, body in css_rules() if "var(--skip)" in body}
    assert any(".fc-sw.skip" in sel for sel in bodies)
    assert any(".fc-testbar .skip" in sel for sel in bodies)
    assert all(re.search(r"background|border", body) for body in bodies.values())
