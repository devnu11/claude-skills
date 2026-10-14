"""s1: the Requirements tab leaves pre-s1 stories out of its gaps; the snapshot carries `trace`.

Static checks of the page source, the snapshot and the fixture (unit). Rendering under node
is real-OS work: moves to e2e (see the handoff).
"""

from __future__ import annotations

import json
from pathlib import Path

from agile_team import state as state_mod
from agile_team.gates import StoryState, Trace
from agile_team.state import RunState

from .test_s121_board import function_body
from .test_snapshot import FIXTURE_TEXT, build, make_config

FIXTURE = json.loads(FIXTURE_TEXT)


def test_gap_tone_is_empty_for_an_exempt_story() -> None:
    body = function_body("gapTone")
    assert 'story.trace === "exempt"' in body
    assert 'return ""' in body


def test_is_gap_is_one_function_over_requirements_and_tone() -> None:
    body = function_body("isGap")
    assert "!c.reqs.length" in body and "gapTone(view, c.story)" in body
    assert "Boolean(" in body


def test_tab_badge_and_gap_list_use_is_gap() -> None:
    assert "isGap(view, c)" in function_body("renderTabs")
    assert "isGap(view, c)" in function_body("renderRequirements")
    assert "c.story.sprint" not in function_body("renderTabs")
    assert "c.story.sprint" not in function_body("renderRequirements")


def test_coverage_status_says_designed_before_s1_for_exempt_stories() -> None:
    body = function_body("coverageStatus")
    assert '<span class="empty">designed before s1</span>' in body
    assert "exempt" in body
    assert "needs a requirement" in body and "untraced past design" in body


def test_page_still_lists_requirement_ids_titles_status_and_covers() -> None:
    body = function_body("renderReqList")
    assert "r.id" in body and "r.title" in body and "r.status" in body and "r.covers" in body


def test_snapshot_story_has_trace_after_rounds(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    stories = {
        "s1": StoryState("s1", "a", "design"),
        "s2": StoryState("s2", "b", "implement", trace=Trace.EXEMPT),
    }
    state_mod.save(config.run_dir, RunState(stories=stories))
    out = {s["id"]: s for s in build(config, scratch)["stories"]}
    assert out["s1"]["trace"] == "checked" and out["s2"]["trace"] == "exempt"
    keys = list(out["s1"])
    assert keys[keys.index("rounds") + 1] == "trace"


def test_fixture_stories_all_carry_trace_and_one_is_exempt() -> None:
    traces = [s["trace"] for s in FIXTURE["stories"]]
    assert set(traces) == {"checked", "exempt"}
    assert traces.count("exempt") == 1


def test_snapshot_requirements_dir_comes_from_the_requirements_module(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    assert build(config, scratch)["run"]["requirements_dir"] == "docs/requirements"
