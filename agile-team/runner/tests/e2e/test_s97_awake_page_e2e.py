"""s97 end to end: the page shows awake time (running line, Time tooltip, legend, replay) under node."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

NOW = 100000


def _run(body: str) -> dict:
    """Run `body` in the page with the fixture as `view`; it fills `out`."""
    view = dashboard_node.fixture()
    driver = f"const view = {json.dumps(view)};\nconst out = {{}};\n(async () => {{\n{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


def _running(clock: str, slept: float) -> str:
    return f"""
    data.skew = {NOW} - Date.now() / 1000;
    view.steps = [{{role: "developer", story: "s1", model: "m", sprint: 1, at: {NOW - 600}, ended_at: null, seconds: null, status: null, clock: "{clock}", slept: {slept}}}];
    out.line = runningLine(view, "developer");
    """


def test_running_line_takes_out_sleep_or_marks_wall() -> None:
    """AC2 (AW10): awake step drops its slept seconds; wall step is marked."""
    awake = _run(_running("awake", 120))["line"]
    assert "running 8 min" in awake and "may include sleep" not in awake
    wall = _run(_running("wall", 0))["line"]
    assert "running 10 min (may include sleep)" in wall


def test_time_by_counts_wall_and_tooltip_marks_it() -> None:
    """AW11: timeBy counts wall steps; only those groups carry the tooltip note."""
    out = _run("""
    const mk = (wall) => ({role: "r", story: "s1", count: "steps", wall, parts: {work: 60}});
    out.by = timeBy([mk(true), mk(false), mk(false)], "role");
    const row = (t) => timeRow({role: "r", t, whole: 100, total: t.seconds}, 0, 1);
    out.withWall = row({steps: 2, seconds: 60, wall: 1, parts: {work: 60}});
    out.noWall = row({steps: 2, seconds: 60, wall: 0, parts: {work: 60}});
    """)
    by = out["by"]["r"]
    assert (by["steps"], by["seconds"], by["wall"]) == (3, 180, 1)
    assert "1 may include sleep" in out["withWall"]
    assert "may include sleep" not in out["noWall"]


def test_legend_says_awake_time() -> None:
    """AC4 (AW12)."""
    assert "Awake time:" in _run("out.l = timeLegend();")["l"]


def test_replay_nulls_clock_and_slept_on_reopened_step() -> None:
    """AW13: a step ended after the cursor is reopened with clock and slept null."""
    out = _run("""
    const s = {role: "r", story: "s1", at: 10, ended_at: 50, seconds: 40, status: "done", clock: "awake", slept: 5};
    out.steps = stepsAsOf([s], 20);
    out.kept = stepsAsOf([s], 60);
    """)
    assert out["steps"][0]["clock"] is None and out["steps"][0]["slept"] is None
    assert out["kept"][0]["clock"] == "awake" and out["kept"][0]["slept"] == 5
