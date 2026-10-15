"""s150 end to end: a Board card's wait pill holds the reason only and no card pill wraps (node harness)."""
# ruff: noqa: E501

from __future__ import annotations

import html
import json
import re
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

LONG = ("the export spills to disk " * 12)[:300]
PILL = re.compile(r'<span class="pill[^"]*"(?: title="([^"]*)")?>(.*?)</span>', re.S)


def _card(wait: dict) -> str:
    """Render fixture story s4 as a working card with `wait`, a revert and an environment."""
    snap = dashboard_node.fixture()
    driver = f"""const snap = {json.dumps(snap)};
data.cursor = Infinity;
const view = asOf(snap, Infinity);
const s = view.stories.find((x) => x.id === "s4");
s.wait = {json.dumps(wait)};
s.reverts = 2;
s.environments = [{{ name: "dashboard", verdict: "" }}];
const out = {{ card: storyCard(view, s, {{ story: "s4", role: "developer-gui-with-a-very-long-specialisation-name" }}) }};
console.log(JSON.stringify(out));"""
    return dashboard_node.run_page(driver, snap["generated_at"])["card"]


def _pills(card: str) -> list[tuple[str, str]]:
    """(visible text, title) of each pill on the card, entities unescaped."""
    stripped = card.replace('<span class="dot"></span>', "")
    return [(html.unescape(t), html.unescape(ti or "")) for ti, t in PILL.findall(stripped)]


def _cancel() -> str:
    return _card(
        {
            "reason": "cancel requested",
            "on": ["m9: Cancel story s4?", LONG],
            "title": "cancel requested: " + LONG,
        }
    )


def _text(card: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", card))


def test_t1_wait_pill_is_the_reason_only() -> None:
    """AC1, AC4: text is the reason; the full title is the tooltip."""
    pills = dict(_pills(_cancel()))
    assert pills["⏸ cancel requested"] == "cancel requested: " + LONG


@pytest.mark.parametrize("reason", ["held", "round cap"])
def test_t2_other_reasons(reason: str) -> None:
    """AC1: reason-only waits keep the reason as text and title."""
    pills = dict(_pills(_card({"reason": reason, "on": ["x"], "title": reason})))
    assert pills[f"⏸ {reason}"] == reason


def test_t3_detail_shows_once_in_waits_on_line() -> None:
    """AC2, AC4: the detail is visible once, in the cut waits-on line, whose title holds all."""
    card = _cancel()
    text = _text(card)
    assert text.count(LONG[:60]) == 1
    line = re.search(r'<div class="rounds" title="([^"]*)">([^<]*)</div>', card)
    assert line and html.unescape(line.group(2)).startswith("waits on: ")
    assert LONG[:60] in html.unescape(line.group(2))
    assert len(html.unescape(line.group(2))) <= 140
    assert html.unescape(line.group(1)) == "waits on: m9: Cancel story s4? · " + LONG


def test_t4_no_pill_text_holds_the_detail() -> None:
    """AC2, AC4: the detail never reaches a pill's visible text."""
    assert all(LONG[:20] not in text for text, _ in _pills(_cancel()))


def test_t5_every_pill_has_a_title() -> None:
    """AC3: each pill carries its full text as a tooltip."""
    pills = _pills(_cancel())
    assert len(pills) >= 4 and all(title for _, title in pills)
    titles = [t for _, t in pills]
    assert "▶ developer-gui-with-a-very-long-specialisation-name" in titles
    assert "reverted (2\u00d7)" in titles


def test_t6_one_line_through_the_css() -> None:
    """AC3, AC4: the .story .pill rule keeps one line, ellipsis; no pill holds a break."""
    page = dashboard_node.dashboard_file("index.html")
    rule = re.search(r"\.story \.pill\s*\{([^}]*)\}", page).group(1)
    for decl in (
        "display: inline-block",
        "white-space: nowrap",
        "overflow: hidden",
        "text-overflow: ellipsis",
        "max-width: 100%",
    ):
        assert decl in rule, decl
    assert not re.search(r"\.story \.pill[^{]*\{[^}]*white-space:\s*normal", page)
    assert all("<br" not in t and "\n" not in t for t, _ in _pills(_cancel()))
