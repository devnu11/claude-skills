"""s118 AC13 end to end: the tool box's description line, the command tooltip and `% complete` (FC30, FC18)."""
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

GATE = "gate.tests+coverage"
DESC = "Implement gate: the full suite with coverage, once; every test must pass and coverage must meet the threshold"
PREVIEW = "Deploy the branch to the preview site"


def _run(body: str) -> dict:
    """Run `body` in the page with the fixture bound as `view`; it fills `out`."""
    fixture = json.dumps(dashboard_node.fixture())
    driver = f"""const view = {fixture};
const out = {{}};
const closed = (id, at, stage, detail) => ({{ id, at, kind: "runner-stage", role: "runner", story: "s3", data: {{ stage, when: "after", attach: "step", step: "implement", detail, code: 0, raised: null, started_at: at - 10, started_mono: null, started_slept: 0, seconds: 10 }} }});
const idle = () => {{ view.heartbeat.stages = []; view.events = view.events.filter((e) => e.kind !== "runner-stage"); ui.scope = "run"; }};
const boxes = () => flowHtml(flowModel(view)).split('<div class="fc-tool ').slice(1).map((s) => '<div class="fc-tool ' + s);
(async () => {{
{body}
console.log(JSON.stringify(out));
}})();"""
    return dashboard_node.run_page(driver)


def _gate_box(boxes: list[str]) -> str:
    return next(b for b in boxes if GATE in b)


def test_a_built_in_tool_shows_its_description_line() -> None:
    """AC13: the idle `gate.tests+coverage` box carries its description line."""
    out = _run(f"""
    idle(); view.events.push(closed("g1", 1791470000, "{GATE}", null));
    out.box = boxes().find((b) => b.includes("{GATE}"));
    """)
    assert f'<div class="fc-tooldesc fc-t-toolDesc">{DESC}</div>' in out["box"]
    assert "title=" not in out["box"].split(">", 1)[0]


def test_a_repo_tool_shows_its_own_description_line() -> None:
    """AC13: a `deploy.preview` run gets the text the snapshot gives that stage."""
    out = _run(f"""
    idle(); view.stage_descriptions["deploy.preview"] = "{PREVIEW}";
    view.events.push(closed("d1", 1791470000, "deploy.preview", null));
    out.box = boxes().find((b) => b.includes("deploy.preview"));
    """)
    assert f'fc-t-toolDesc">{PREVIEW}</div>' in out["box"]


def test_a_stage_without_a_description_has_no_line() -> None:
    """AC13: no entry in `stage_descriptions` (or a non-string) means no description line."""
    out = _run(f"""
    idle(); delete view.stage_descriptions["{GATE}"];
    view.events.push(closed("g1", 1791470000, "{GATE}", null));
    out.missing = boxes().find((b) => b.includes("{GATE}"));
    view.stage_descriptions["{GATE}"] = 7;
    out.nonstring = boxes().find((b) => b.includes("{GATE}"));
    """)
    assert "fc-tooldesc" not in out["missing"] and "fc-tooldesc" not in out["nonstring"]


@pytest.mark.parametrize("bad", ["null", "[]", '"text"', "undefined"])
def test_stage_descriptions_default_to_empty_object(bad: str) -> None:
    """FC30: `normalize` turns a missing, array or non-object value into `{}`."""
    out = _run(f"""
    const v = JSON.parse(JSON.stringify(view)); v.stage_descriptions = {bad};
    out.fixed = normalize(v).stage_descriptions;
    """)
    assert out["fixed"] == {}


def test_tooltip_is_the_newest_command_and_is_escaped() -> None:
    """AC13: `title` is the newer run's command; an empty newer detail keeps the older; `"` and `<` are escaped."""
    out = _run(f"""
    idle();
    view.events.push(closed("g1", 1791470000, "{GATE}", "old cmd"), closed("g2", 1791470100, "{GATE}", 'pytest "a" <b>'));
    out.newest = _gateTitle();
    view.events.pop(); view.events.push(closed("g3", 1791470200, "{GATE}", ""));
    out.older = _gateTitle();
    function _gateTitle() {{ return boxes().find((b) => b.includes("{GATE}")).split(">", 1)[0]; }}
    """)
    assert 'title="pytest &quot;a&quot; &lt;b&gt;"' in out["newest"]
    assert 'title="old cmd"' in out["older"]


def test_no_detail_means_no_title_and_an_out_of_scope_detail_still_sets_it() -> None:
    """AC13: no `title` without a detail; a detail from another story still sets it in story scope."""
    out = _run(f"""
    idle(); view.events.push(closed("g1", 1791470000, "{GATE}", null));
    out.none = boxes().find((b) => b.includes("{GATE}")).split(">", 1)[0];
    const other = closed("g2", 1791470100, "{GATE}", "other story cmd"); other.story = "s2";
    view.events.push(other);
    ui.scope = "story"; ui.focus = "s3";
    out.scoped = boxes().find((b) => b.includes("{GATE}")).split(">", 1)[0];
    """)
    assert "title=" not in out["none"]
    assert 'title="other story cmd"' in out["scoped"]


def test_running_box_has_the_description_after_its_head_and_the_same_title() -> None:
    """AC13: the running box shows head, then description line, then the title from the newest finished run."""
    out = _run(f"""
    ui.scope = "run"; view.events.push(closed("g1", 1791470000, "{GATE}", "uv run pytest"));
    out.box = boxes().find((b) => b.includes("▶ {GATE}"));
    """)
    box = out["box"]
    assert box.split(">", 1)[0].endswith('title="uv run pytest"')
    assert re.search(
        r"▶ gate\.tests\+coverage[^<]*</span><span>[^<]*</span></div><div class=\"fc-tooldesc fc-t-toolDesc\">"
        + re.escape(DESC),
        box,
    )


def test_hide_tools_hides_the_idle_line_but_not_the_running_one() -> None:
    """AC13: the idle box has `f-tools` (hidden by `hide-tools`); the running box has none."""
    out = _run(f"""
    ui.scope = "run"; out.running = boxes().find((b) => b.includes("▶ {GATE}"));
    idle(); view.events.push(closed("g1", 1791470000, "{GATE}", null));
    out.idle = boxes().find((b) => b.includes("{GATE}"));
    """)
    assert (
        re.match(r'<div class="fc-tool running[^"]*"', out["running"])
        and "f-tools" not in out["running"]
    )
    assert out["idle"].startswith('<div class="fc-tool f-tools"')


@pytest.mark.parametrize("total", ["null", "0"])
def test_no_total_means_no_percent_complete(total: str) -> None:
    """FC18: `completePct` is null without a positive total, and the running box drops the `% complete` row and sparkline."""
    out = _run(f"""
    const t = {{ passed: 3, warned: 0, failed: 0, total: {total}, points: [], fail_at: null }};
    out.pct = completePct(t);
    view.heartbeat.stages[0].tests = {{ ...t, points: [10, 20, 30] }};
    ui.scope = "run"; out.box = boxes().find((b) => b.includes("▶ {GATE}"));
    out.real = completePct({{ passed: 3, warned: 0, failed: 0, total: 6, points: [], fail_at: null }});
    """)
    assert out["pct"] is None and out["real"] == 50
    assert "% complete" not in out["box"] and "fc-status" not in out["box"]
    assert "3 Pass" in out["box"]
