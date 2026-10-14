"""s112: static checks of the Activity tab, live panel and fixture (AT, MD, HD, HS, LP, RD, FX).

Behaviour checks need node, so they live in the e2e suite.
"""

import json
import re
from importlib import resources

from agile_team import system

PKG = resources.files("agile_team.dashboard")
PAGE = system.read_text(PKG.joinpath("index.html"))
RD1 = {
    ".brand small": ("12px", "--ink-2"),
    ".task": ("12px", "--ink-2"),
    ".budget": ("12px", "--ink"),
    ".budget small": ("12px", "--ink-2"),
    ".lp-who": ("12px", "--ink"),
    ".lp-when": ("12px", "--ink-2"),
    ".lp-line": ("12px", "--ink-2"),
    ".lp-msg": ("12px", "--ink"),
    ".md-notice": ("12.5px", "--ink-2"),
}


def rule(selector: str) -> str:
    """Body of the first CSS rule whose selector is exactly ``selector``."""
    found = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", PAGE)
    assert found, selector
    return found.group(1)


def test_tabs_put_activity_after_flow() -> None:
    assert PAGE.index('["flow", "Flow"]') < PAGE.index('["activity", "Activity"]')
    assert PAGE.index('["activity", "Activity"]') < PAGE.index('["board",')


def test_the_timeline_lives_in_the_activity_section() -> None:
    flow = PAGE.split('id="tab-flow"')[1].split('id="tab-activity"')[0]
    activity = PAGE.split('id="tab-activity"')[1]
    assert 'id="timeline"' in activity and 'id="tl-filter"' in activity
    assert 'id="timeline"' not in flow and 'id="tl-filter"' not in flow


def test_grid_flow_is_gone() -> None:
    assert "grid-flow" not in PAGE


def test_activity_renders_the_timeline_and_flow_does_not() -> None:
    assert "activity: renderTimeline" in PAGE or "RENDER.activity = renderTimeline" in PAGE
    flow = PAGE.split("function renderFlowTab(")[1].split("\n}")[0]
    assert "renderTimeline" not in flow
    flow_chart = PAGE.split("function renderFlow(")[1].split("\n}")[0]
    assert 'class="fc"' in PAGE or "fc-chart" in flow_chart


def test_the_timeline_is_not_height_capped_on_its_tab() -> None:
    assert "max-height: none" in rule("#tab-activity .timeline")


def test_every_body_is_markdown_except_two_plain_kinds() -> None:
    assert 'PLAIN_BODIES = new Set(["gate-fix", "opinion-act"])' in PAGE
    assert "MARKDOWN_KINDS" not in PAGE
    assert "bodyHtml(e.kind, t.body)" in PAGE
    assert "md(q.text)" in PAGE


def test_story_admin_puts_the_question_in_the_body() -> None:
    assert '[e.data.reason, e.data.question].filter(Boolean).join("\\n\\n")' in PAGE


def test_a_failed_markdown_load_shows_a_notice() -> None:
    assert 'const MD_NOTICE = "Markdown unavailable: showing plain text";' in PAGE
    assert "MD.FAILED" in PAGE and "MD.READY" in PAGE
    assert 'class="md-notice" role="status"' in PAGE


def _head() -> str:
    return PAGE.split('<div class="head">')[1].split('<nav role="tablist"')[0]


def test_the_header_is_left_block_then_panel_then_theme_button() -> None:
    head = _head()
    left = head.split('class="live-panel')[0]
    assert left.index('id="sprint-label"') < left.index('id="task"') < left.index('id="status-row"')
    assert head.index('id="live-panel"') < head.index('id="theme"')
    assert head.split('id="theme"')[1].split("</button>")[1].strip().startswith("</div>")


def test_the_old_header_parts_are_gone() -> None:
    for gone in ('id="meter"', "head-right", "status-bar", "live-details", "ui.details"):
        assert gone not in PAGE, gone


def test_the_goal_is_one_line_with_a_hover_title() -> None:
    assert "white-space: nowrap" in rule(".task")
    assert "text-overflow: ellipsis" in rule(".task")
    assert "view.run.task" in PAGE and ".title" in PAGE


def test_the_header_functions_exist_and_the_old_ones_do_not() -> None:
    new = ("statePill", "managerFlag", "budgetPill", "questionsPill", "checkPcts", "budgetTitle")
    for name in new:
        assert f"function {name}(" in PAGE, name
    for name in ("connectionPill", "smartPill", "pillText", "renderMeter", "renderLiveDetails"):
        assert f"function {name}(" not in PAGE, name
    assert "pill smart" not in PAGE


def test_the_budget_bar_is_120_px() -> None:
    assert "width: 120px" in rule(".budget-bar")


def test_the_panel_states_and_helpers_exist() -> None:
    states = "PANEL_STATES = [stepPanel, eventPanel, stagePanel, chorePanel, idlePanel]"
    assert states in PAGE
    names = (
        *("latestMessage", "clip", "idleWhy", "renderLivePanel", "renderPanelText"),
        *("fillPanelText", "runLabel", "toolLine", "stageAwake", "stageLine"),
        *("firstLine", "newestRow"),
    )
    for name in names:
        assert f"function {name}(" in PAGE, name
    gone_names = ("runnerResult", "renderPanelHead", "awakeText", "panelMeta")
    for gone in (*gone_names, "lp-more", "lp-meta", 'lp-head"'):
        assert gone not in PAGE, gone
    assert "CLIP_LINES = 4" in PAGE and "CLIP_CHARS = 400" in PAGE and "CLAMP_LINES = 3" in PAGE
    assert "● Nothing running" in PAGE


def test_the_panel_is_380_px_and_clamps_the_message() -> None:
    assert "width: 380px" in rule(".live-panel")
    assert "-webkit-line-clamp: 3" in rule(".lp-msg")
    assert "display: none" in rule(".lp-msg[hidden]")


def test_tick_moves_the_panel_text_only() -> None:
    tick = PAGE.split("function tick(")[1].split("\n}")[0]
    assert "renderPanelText" in tick and "renderStatusRow" not in tick


def test_the_panel_keydown_leaves_links_alone() -> None:
    assert 'closest("a")' in PAGE


def test_clicking_the_panel_opens_activity() -> None:
    assert "function openActivity(" in PAGE
    assert "[data-live-panel]" in PAGE


def test_new_text_is_big_enough_and_never_muted() -> None:
    for selector, (size, color) in RD1.items():
        body = rule(selector)
        assert f"font-size: {size}" in body, selector
        assert f"color: var({color})" in body, selector
        assert "--muted" not in body, selector


def test_inline_code_stays_at_least_12_px() -> None:
    assert "font-size: max(12px, .92em)" in rule(".md code")


def test_the_fixture_texts_carry_markdown() -> None:
    data = json.loads(system.read_text(PKG.joinpath("fixtures", "snapshot.json")))
    brief = next(e for e in data["events"] if e.get("id") == "e42" or e.get("seq") == "e42")
    msg = next(m for m in data["messages"] if m["id"] == "m3")
    for text in (brief["data"]["brief"], msg["text"]):
        assert "- **" in text and "`" in text
