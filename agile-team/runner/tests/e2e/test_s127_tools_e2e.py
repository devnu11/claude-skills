"""s127 end to end in node: the idle sparkline captions (RT2, AC9) and `stage_labels` (TL1, TL3, LB4)."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

TOO_SHORT = "last step · too short for a sparkline"
NO_RATE = "last step · no rate yet"


def _run(body: str) -> dict:
    """Run `body` in the page with the fixture bound as `view`; it fills `out`."""
    fixture = json.dumps(dashboard_node.fixture())
    driver = f"""const view = {fixture};
const out = {{}};
(async () => {{
{body}
console.log(JSON.stringify(out));
}})();"""
    return dashboard_node.run_page(driver)


def _caption(rate: str) -> str:
    """The idle `developer` row's sparkline HTML when its newest step-end has `rate`."""
    out = _run(f"""
    view.heartbeat.stages = []; view.heartbeat.step = null; ui.scope = "run";
    view.events = view.events.filter((e) => !(e.kind === "step-end" && e.role === "zz"));
    const data = {{ status: "done", {rate} }};
    view.events.push({{ id: "zz1", at: 1791470000, kind: "step-end", role: "zz", story: "s3", data }});
    out.html = sparkHtml({{ view, run: {{ cls: "x" }}, now: 1791470100 }}, "zz");
    """)
    return out["html"]


@pytest.mark.parametrize("rate", ["rate: [840.0]", "rate: []"])
def test_a_recorded_short_rate_says_too_short(rate: str) -> None:
    """AC9: a recorded rate of under two points reads `too short for a sparkline`, with no SVG."""
    html = _caption(rate)
    assert TOO_SHORT in html and NO_RATE not in html and "<svg" not in html


def test_a_step_end_with_no_rate_key_says_no_rate_yet() -> None:
    """AC9: no `rate` key reads `no rate yet`, not the other caption."""
    html = _caption("")
    assert NO_RATE in html and TOO_SHORT not in html and "<svg" not in html


def test_two_or_more_points_draw_the_sparkline_and_no_caption() -> None:
    """AC9: 2+ points give an SVG and neither caption."""
    html = _caption("rate: [10, 20, 30]")
    assert "<svg" in html and TOO_SHORT not in html and NO_RATE not in html


@pytest.mark.parametrize("bad", ["null", "[]", '"text"', "undefined"])
def test_bad_stage_labels_normalize_to_an_empty_object(bad: str) -> None:
    """TL1: a null, array, string or missing `stage_labels` becomes `{}`."""
    out = _run(f"""
    const v = JSON.parse(JSON.stringify(view)); v.stage_labels = {bad};
    out.fixed = normalize(v).stage_labels;
    """)
    assert out["fixed"] == {}


def test_a_repo_tool_label_shows_in_its_box_and_its_name_leads_the_title() -> None:
    """TL1/TL3: a repo tool's `stage_labels` entry is the box text; the title starts with the tool name."""
    out = _run("""
    view.heartbeat.stages = []; view.events = view.events.filter((e) => e.kind !== "runner-stage"); ui.scope = "run";
    view.stage_labels["deploy.preview"] = "Preview";
    view.events.push({ id: "d1", at: 1791470000, kind: "runner-stage", role: "runner", story: "s3", data: { stage: "deploy.preview", when: "after", attach: "step", step: "implement", detail: null, code: 0, raised: null, started_at: 1791469990, started_mono: null, started_slept: 0, seconds: 10 } });
    out.box = flowHtml(flowModel(view)).split('<div class="fc-tool ').slice(1).find((b) => b.includes("deploy.preview"));
    """)
    head = out["box"].split(">", 1)[0]
    assert 'title="deploy.preview' in head and "Preview" in out["box"].split(">", 1)[1]
