"""s126 AC9 end to end: a role's stop checks are its after boxes on the Flow chart, under node."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

SUITE = "stop: suite + coverage"
LINT = "stop: lint fix + check"


def _run(body: str) -> dict:
    """Run `body` in the page with the fixture bound as `view`; it fills `out`."""
    fixture = json.dumps(dashboard_node.fixture())
    driver = f"""const view = {fixture};
const out = {{}};
const boxes = () => flowHtml(flowModel(view)).split('<div class="fc-tool ').slice(1).map((s) => '<div class="fc-tool ' + s);
const text = (b) => b.replace(/<[^>]*>/g, "");
(async () => {{
{body}
console.log(JSON.stringify(out));
}})();"""
    return dashboard_node.run_page(driver)


def _box(boxes: list[str], label: str) -> str:
    return next(b for b in boxes if label in b)


def test_stop_checks_are_after_boxes_with_counts_and_refusals() -> None:
    """Idle boxes read `name · ↻ n · time`, plus `· n refused` only for the refused check."""
    out = _run("""
    view.heartbeat.stages = [];
    ui.scope = "run"; out.boxes = boxes().map(text);
    out.tools = roleTools(view)["developer-cli"].after.map((t) => t.stage);
    """)
    suite, lint = _box(out["boxes"], SUITE), _box(out["boxes"], LINT)
    assert "↻ 2 ·" in suite and "· 1 refused" in suite
    assert "↻ 1 ·" in lint and "refused" not in lint
    assert {"stop.suite", "stop.lint"} <= set(out["tools"])


def test_story_scope_on_another_story_shows_no_refusal() -> None:
    """The refusal belongs to s3; focusing another story counts none."""
    out = _run("""
    view.heartbeat.stages = [];
    ui.scope = "story"; ui.focus = "s9"; out.boxes = boxes().map(text);
    """)
    assert "refused" not in _box(out["boxes"], SUITE)


def test_the_running_stop_check_shows_its_attempt_and_the_test_bar() -> None:
    """An open `stop.suite` row renders the running style, `attempt 2 of 3` and the Pass/Fail bar."""
    out = _run("""
    view.heartbeat.stages = [{ stage: "stop.suite", when: "after", attach: "step", description: "x", story: "s3", step: "implement", attempt: { n: 2, of: 3 }, started_at: clockNow(view) - 5, started_mono: null, started_slept: 0, tests: { passed: 3, warned: 0, failed: 1, total: 8, points: [], fail_at: null } }];
    ui.scope = "run"; out.box = boxes().find((b) => b.includes("▶ stop: suite + coverage"));
    """)
    box = out["box"]
    assert "▶ stop: suite + coverage · attempt 2 of 3" in box
    assert "fc-testbar" in box and "3 Pass" in box and "1 Fail" in box
