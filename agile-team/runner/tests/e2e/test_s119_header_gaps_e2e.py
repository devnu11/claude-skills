"""s119 end to end: the sprint goal, the stage line, the manager flag and the live panel, under node."""
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

LONG_GOAL = (
    "Make the dashboard header match the approved mock and keep every gap pinned by a test. " * 3
)
EL = """const els = {};
const el = () => ({textContent: "", innerHTML: "", title: "", hidden: false, className: "", dataset: {}, attrs: {},
  setAttribute(k, v) { this.attrs[k] = v; }, classList: {toggle() {}}});
globalThis.document.querySelector = (q) => (els[q] ??= el());
"""


def _run(body: str) -> dict:
    """Run `body` in the page with the fixture bound as `view`; it fills `out`."""
    snap = json.dumps(dashboard_node.fixture())
    driver = f"const view = {snap};\nconst out = {{}};\n(async () => {{\n{EL}{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


def _page() -> str:
    return dashboard_node.dashboard_file("index.html")


def _start(goal: str, at: int) -> str:
    event = {
        "id": f"g{at}",
        "at": at,
        "kind": "sprint-start",
        "role": "product-owner",
        "story": None,
        "data": {"sprint": 1, "goal": goal},
    }
    return json.dumps(event)


# ---------------------------------------------------------------- AC1


def test_goal_line_shows_the_newest_sprint_goal_and_its_fallbacks() -> None:
    """AC1, G1-G3: long goal in text and title; newest of two; task fallback; blank last."""
    out = _run(f"""
    view.run.task = "";
    view.events = view.events.filter((e) => e.kind !== "sprint-start");
    view.events.push({_start(LONG_GOAL, 1791460000)});
    renderGoal(view);
    out.long = [els["#task"].textContent, els["#task"].title];
    view.events.push({_start("newer goal", 1791461000)});
    renderGoal(view);
    out.newest = els["#task"].textContent;
    view.events = view.events.filter((e) => e.kind !== "sprint-start");
    view.run.task = "the task";
    renderGoal(view);
    out.task = [els["#task"].textContent, els["#task"].title];
    view.run.task = "";
    renderGoal(view);
    out.none = [els["#task"].textContent, els["#task"].title];
    """)
    assert out["long"] == [LONG_GOAL.strip(), LONG_GOAL.strip()] and len(LONG_GOAL) > 200
    assert out["newest"] == "newer goal"
    assert out["task"] == ["the task", "the task"]
    assert out["none"] == ["", ""]
    rule = re.search(r"\.task\s*\{([^}]*)\}", _page()).group(1)  # type: ignore[union-attr]
    for decl in ("white-space: nowrap", "overflow: hidden", "text-overflow: ellipsis"):
        assert decl in rule


# ---------------------------------------------------------------- AC2


def test_stage_panel_names_only_the_open_stage() -> None:
    """AC2, ST2: the line is the row's description, never an older boundary event."""
    out = _run("""
    view.heartbeat.step = null;
    view.heartbeat.stages = [{stage: "gate.tests+coverage", description: "Run the tests and coverage", story: "s95", step: "implement", started_at: clockNow(view) - 45, started_slept: 0}];
    const old = {id: "b1", at: clockNow(view) - 600, kind: "boundary", role: "runner", story: null,
      data: {sprint: 40, edge: "start", stage: "check", outcome: "done", reason: "check: done"}};
    view.events.push(old);
    const state = panelState(view);
    out.state = state;
    out.text = [state.who, state.when, state.line].join(" ");
    out.old = rowOf(old, {events: view.events});
    view.heartbeat.stages[0].description = undefined;
    out.blank = panelState(view).line;
    """)
    assert out["state"]["kind"] == "stage"
    text = out["text"]
    assert "gate.tests+coverage" in text and "Run the tests and coverage" in text
    assert "check: done" not in text and "sprint 40 start" not in text
    if out["old"]:
        assert out["old"]["what"] not in text
    assert out["blank"] == ""


# ---------------------------------------------------------------- AC4


def test_manager_flag_holds_the_reason_in_its_title_not_in_any_pill_text() -> None:
    """AC4a, P1: one flag pill, the reason on hover, the goal in no visible pill text."""
    goal = "Dashboard readability and the header gaps"
    reason = f"sprint 40 start: {goal} (s112, s118)"
    out = _run(f"""
    view.events.push({_start(goal, 1791461000)});
    view.run.manager_due = [{json.dumps(reason)}];
    out.due = statusPills(view).join("");
    view.run.manager_due = [];
    out.none = statusPills(view).join("");
    """)
    assert out["due"].count("⚑ manager due") == 1
    flag = re.search(r'<span class="pill flag"[^>]*>', out["due"])
    assert (
        flag and "manager due:" in flag.group(0) and reason in flag.group(0).replace("&amp;", "&")
    )
    pills = re.findall(r'<span class="pill[^"]*"[^>]*>(.*?)</span>', out["due"])
    assert pills
    for pill in pills:
        assert goal not in re.sub(r"<[^>]*>", "", pill)
    assert "manager due" not in out["none"]


def test_live_panel_shows_who_when_tool_message_and_clamp() -> None:
    """AC4b, P2: role · story · step, age · run label, the open call, the clipped message."""
    out = _run("""
    renderLivePanel(view);
    out.who = els["#lp-who"].textContent; out.when = els["#lp-when"].textContent;
    out.line = els["#lp-line"].textContent;
    out.hidden = els["#lp-msg"].hidden; out.msg = els["#lp-msg"].innerHTML;
    out.step = view.heartbeat.step;
    out.clipped = clip(Array.from({length: 8}, (_, i) => "line " + i).join("\\n"));
    """)
    assert re.fullmatch(r".+ · s\d+ · \w+", out["who"]), out["who"]
    assert re.fullmatch(r".+ · (first run|round \d+|↻ restarted)", out["when"]), out["when"]
    assert out["line"].strip()
    assert out["hidden"] is False and out["msg"].strip()
    assert len([ln for ln in out["clipped"].split("\n") if ln.strip()]) == 4
    rule = re.search(r"\.lp-msg\s*\{([^}]*)\}", _page()).group(1)  # type: ignore[union-attr]
    assert "-webkit-line-clamp: 3" in rule
