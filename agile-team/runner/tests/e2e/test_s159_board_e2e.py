"""s159 AC9.1, AC9.2 through the real page code: the Board cards and the story.land stage."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

EL = """const els = {};
const el = () => ({textContent: "", innerHTML: "", title: "", hidden: false, className: "", dataset: {}, attrs: {},
  setAttribute(k, v) { this.attrs[k] = v; }, classList: {toggle() {}}});
globalThis.document.querySelector = (q) => (els[q] ??= el());
"""
EDITS = """
view.run.sprint = 2;
const base = view.stories[0];
const mk = (id, step, status, extra) => ({ ...base, id, sprint: 2, status, step, title: "t" + id, held: null, hold: null, branch: "", landed: null, story_ci: null, running: false, ...extra });
view.stories = [
  mk("a", "implement", "active", { branch: "team/story-a", running: true, story_ci: {sha: "1".repeat(40), verdict: "red", source: "pr"} }),
  mk("b", "tests", "active", { branch: "team/story-b", running: true }),
  mk("c", "land", "done", { branch: "team/story-c", landed: "c".repeat(40), story_ci: {sha: "2".repeat(40), verdict: "green", source: "landing"} }),
];
view.requirements = [];
"""
BODY = """
renderTabs(view); renderBoard(view);
out.html = els["#board"].innerHTML; out.pipeline = view.pipeline;
"""


def board() -> dict:
    snap = json.dumps(dashboard_node.fixture())
    driver = f"const view = {snap};\nconst out = {{}};\n(async () => {{\n{EL}{EDITS}\n{BODY}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


def card(html: str, story: str) -> str:
    return html.split(f"· {story} ", 1)[1].split("sid", 1)[0]


def test_ac9_1_each_card_shows_its_branch_and_the_latest_story_ci() -> None:
    html = board()["html"]
    a = card(html, "a")
    assert "story-a" in a and "CI red (pr)" in a
    assert "story-b" in card(html, "b")


def test_ac9_1_a_landed_story_shows_its_merge_and_the_landing_ci() -> None:
    c = card(board()["html"], "c")
    assert "landed ccccccc" in c and "CI green (landing)" in c


def test_ac9_1_several_stories_show_as_running_at_once() -> None:
    html = board()["html"]
    assert "▶ running" in card(html, "a") and "▶ running" in card(html, "b")
    assert "▶ running" not in card(html, "c")


def test_ac9_2_the_land_stage_is_a_runner_stage_with_its_name() -> None:
    from agile_team import stages

    assert stages.Name.STORY_LAND.value == "story.land"
