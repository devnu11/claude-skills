"""s112: static checks of the Activity tab, live panel and fixture (AT, MD, LP, BM, RD, FX).

Behaviour checks need node, so they live in the e2e suite.
"""

import json
import re
from importlib import resources

from agile_team import system

PKG = resources.files("agile_team.dashboard")
PAGE = system.read_text(PKG.joinpath("index.html"))
RD1 = {
    ".lp-head": ("13px", "--ink"),
    ".lp-meta": ("12px", "--ink-2"),
    ".lp-msg": ("12.5px", "--ink-2"),
    ".lp-more": ("12.5px", "--ink-2"),
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


def test_the_live_panel_is_in_the_header_and_the_meter_in_the_status_bar() -> None:
    right = PAGE.split('class="head-right"')[1].split("</header>")[0]
    assert 'id="live-panel"' in right and 'id="meter"' not in right
    bar = PAGE.split('class="status-bar"')[1]
    assert bar.index('id="meter"') < bar.index('id="status-row"')


def test_the_panel_states_and_helpers_exist() -> None:
    assert "PANEL_STATES = [stepPanel, stagePanel, idlePanel]" in PAGE
    for name in ("latestMessage", "clip", "idleWhy", "renderLivePanel", "renderPanelHead"):
        assert f"function {name}(" in PAGE
    assert "CLIP_LINES = 6" in PAGE and "CLIP_CHARS = 600" in PAGE
    assert "● Nothing running: " in PAGE and "No activity yet." in PAGE


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
