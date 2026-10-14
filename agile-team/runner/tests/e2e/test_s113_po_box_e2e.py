"""s113 end to end on the page: the PO box's time, waiting and shared turns (AC1, AC3, AC4)."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

# Turn numbers: (model_s, tool_s, waiting_s) -> awake = model + (tool - waiting).
TURNS = {
    "none": ([], 10, 30, 20),  # awake 20, waiting 20
    "a": (["sA"], 4, 16, 6),  # awake 14, waiting 6
    "ab": (["sA", "sB"], 2, 11, 1),  # awake 12, waiting 1
}


def _run(scope: str, focus: str, keys: list[str], extra: str = "") -> dict:
    """Render the Flow chart with the chosen `po-turn` events; return the PO box and tools."""
    turns = [
        {"stories": TURNS[k][0], "m": TURNS[k][1], "t": TURNS[k][2], "w": TURNS[k][3]} for k in keys
    ]
    driver = f"""const view = {json.dumps(dashboard_node.fixture())};
const turns = {json.dumps(turns)};
const starts = view.events.filter((e) => e.kind === "sprint-start");
const at0 = starts[0].at + 1;
view.events = view.events.filter((e) => e.kind !== "po-turn");
turns.forEach((t, i) => {{
  const data = {{ opened_at: at0, model_s: t.m, tool_s: t.t, waiting_s: t.w, mono: 1, slept: 0, rate: [1, 2, 3] }};
  if (t.stories) data.stories = t.stories;
  view.events.push({{ id: "p" + i, at: at0 + i, kind: "po-turn", role: "product-owner", story: null, data }});
}});
ui.scope = {json.dumps(scope)}; ui.focus = {json.dumps(focus)};
{extra}
const html = flowHtml(flowModel(view));
const box = (r) => html.split('<div class="fc-box').slice(1).find((b) => b.includes('data-role="' + r + '"')) || "";
const out = {{ po: box("product-owner"), others: view.roles.filter((r) => r.name !== "product-owner").map((r) => box(r.name)).filter((b) => b.includes("f-wait")).length }};
console.log(JSON.stringify(out));"""
    return dashboard_node.run_page(driver)


def _time(box: str) -> str:
    return box.split('<span class="f-time">')[1].split("</span>")[0]


def _wait(box: str) -> str:
    return box.split('f-time f-wait fc-t-meta">')[1].split("</div>")[0]


def test_run_scope_shows_awake_time_and_waiting_separately() -> None:
    """AC1: Run scope sums every turn: awake 46s, waiting 27s, nothing shared."""
    out = _run("run", "s1", ["none", "a", "ab"])
    assert _time(out["po"]) == "46s"
    assert _wait(out["po"]) == "waiting on roles 27s"
    assert out["others"] == 0


def test_sprint_scope_counts_the_turns_inside_the_sprint_window() -> None:
    """AC1: Sprint scope takes the unstoried turns in the window, same format as Run."""
    out = _run("sprint", "s1", ["a", "ab"])
    assert _time(out["po"]) == "26s"
    assert _wait(out["po"]) == "waiting on roles 7s"


def test_story_scope_counts_turns_touching_the_story_and_says_shared() -> None:
    """AC3/AC4: focus sA counts the one-story and the two-story turn, not the no-story one."""
    out = _run("story", "sA", ["none", "a", "ab"])
    assert _time(out["po"]) == "26s"
    assert _wait(out["po"]) == "waiting on roles 7s · shared turns"


def test_a_shared_turn_counts_in_each_story() -> None:
    """AC3: focus sB sees only the shared turn."""
    out = _run("story", "sB", ["none", "a", "ab"])
    assert _time(out["po"]) == "12s"
    assert _wait(out["po"]).endswith(" · shared turns")


def test_story_scope_without_shared_turns_does_not_say_shared() -> None:
    """AC3: only a one-story turn: no "shared turns"."""
    out = _run("story", "sA", ["a"])
    assert _time(out["po"]) == "14s"
    assert "shared" not in _wait(out["po"])


def test_story_scope_with_no_touching_turn_reads_dash_and_no_wait_line() -> None:
    """AC3/AC4: no turn on the story (and an event from before s113) gives — and no waiting line."""
    out = _run(
        "story", "sZ", ["none", "a"], 'delete view.events.find((e) => e.id === "p0").data.stories;'
    )
    assert _time(out["po"]) == "—"
    assert "f-wait" not in out["po"]
    assert out["po"].count("—") == 3


def test_the_waiting_line_is_hidden_with_the_time() -> None:
    """AC1: the line carries the f-time class, so the awake-time switch hides it."""
    out = _run("run", "s1", ["a"])
    assert 'class="f-time f-wait' in out["po"]


def test_story_scope_share_bar_follows_the_touched_turns() -> None:
    """AC3: the bar is drawn from the touched turns (model 4 of 14s = 29%), dashed with none."""
    assert "model 29%" in _run("story", "sA", ["a"])["po"]
    assert "no model/tool timing yet" in _run("story", "sZ", ["a"])["po"]
