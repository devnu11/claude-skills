"""s181: the heartbeat lists every open chore; a chore never outlives its block (CH1-CH9).

The page's behaviour needs node, so it lives in the e2e suite; here the page source is
checked statically.
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import live, system
from agile_team.health import Runner, Vitals
from agile_team.state import RunStatus
from agile_team.stop_checks import STOP_CHORE, StopChecks

from .fake_system import START_CLOCK, FakeSystem

NOW = START_CLOCK
PKG = resources.files("agile_team.dashboard")
PAGE = system.read_text(PKG.joinpath("index.html"))


def pulse_of(fake: FakeSystem) -> live.Pulse:
    pulse = live.Pulse(Path("/fake/run"), 20.0)
    pulse.write = lambda: None  # type: ignore[method-assign]
    return pulse


def names(pulse: live.Pulse) -> list[str]:
    return [c["what"] for c in pulse.heartbeat()["chores"]]


# ----- AC1: a chore never outlives its block (CH1) -----


def test_overlapping_chores_that_end_out_of_order_leave_no_ghost(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    a, b = pulse.doing("A", "s1"), pulse.doing("B", "s2")
    a.__enter__()
    b.__enter__()
    a.__exit__(None, None, None)
    assert [c["what"] for c in pulse.heartbeat()["chores"]] == ["B"]
    assert pulse.heartbeat()["chores"][0]["story"] == "s2"
    b.__exit__(None, None, None)
    assert pulse.heartbeat()["chores"] == []


def test_nested_chores_still_unwind(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    with pulse.doing("outer"):
        with pulse.doing("inner"):
            assert names(pulse) == ["outer", "inner"]
        assert names(pulse) == ["outer"]
    assert names(pulse) == []


def test_a_chore_that_raises_removes_only_its_own_row(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    with pulse.doing("kept", "s1"):
        with pytest.raises(ValueError), pulse.doing("lost", "s2"):
            raise ValueError
        assert names(pulse) == ["kept"]
    assert names(pulse) == []


def test_three_chores_closing_in_any_order_leave_none(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    blocks = [pulse.doing(w, "s1") for w in "xyz"]
    for block in blocks:
        block.__enter__()
    blocks[1].__exit__(None, None, None)
    assert names(pulse) == ["x", "z"]
    blocks[2].__exit__(None, None, None)
    blocks[0].__exit__(None, None, None)
    assert names(pulse) == []


def test_two_chores_with_the_same_text_are_removed_one_at_a_time(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    a, b = pulse.doing("same", "s1"), pulse.doing("same", "s1")
    a.__enter__()
    b.__enter__()
    a.__exit__(None, None, None)
    assert names(pulse) == ["same"]
    b.__exit__(None, None, None)
    assert names(pulse) == []


# ----- AC2: every open chore, with its story and since (CH2-CH4) -----


def test_a_chore_row_has_what_story_since_in_order(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    with pulse.doing("A", "s1"):
        (row,) = pulse.heartbeat()["chores"]
        assert list(row) == ["what", "story", "since"]
        assert row == {"what": "A", "story": "s1", "since": NOW}


def test_a_run_wide_chore_has_a_null_story(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    with pulse.doing("x"):
        assert pulse.heartbeat()["chores"][0]["story"] is None


def test_rows_are_oldest_first_with_their_own_since(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    with pulse.doing("first", "s1"):
        fake.clock += 5
        with pulse.doing("second", "s2"):
            rows = pulse.heartbeat()["chores"]
    assert [(r["what"], r["since"]) for r in rows] == [("first", NOW), ("second", NOW + 5)]


def test_the_heartbeat_has_chores_not_chore_and_is_version_3(fake: FakeSystem) -> None:
    beat = pulse_of(fake).heartbeat()
    assert "chore" not in beat and beat["chores"] == []
    assert live.HEARTBEAT_VERSION == 3 and beat["version"] == 3
    keys = list(beat)
    assert keys.index("slept") < keys.index("chores") < keys.index("step")


def test_an_ended_pulse_writes_no_chores(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    with pulse.doing("x", "s1"):
        pulse.end()
        assert pulse.heartbeat()["chores"] == []


def test_a_chore_ending_still_wakes_the_innermost_reading(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(
        live.Who("developer-cli", "s1", "implement", "sonnet", live.Billing.REPORTED)
    )
    with pulse.doing("x", "s2"):
        fake.clock = NOW + 900
    assert meter.reading.quiet_since == NOW + 900


# ----- AC2: callers pass their story (CH5) -----


def spy_on_doing(pulse: live.Pulse) -> list[tuple[str, str | None]]:
    seen: list[tuple[str, str | None]] = []

    @contextmanager
    def doing(what: str, story: str | None = None):
        seen.append((what, story))
        yield

    pulse.doing = doing  # type: ignore[method-assign]
    return seen


def stop_checks_for(story: Any) -> tuple[StopChecks, list[tuple[str, str | None]]]:
    pulse = live.Pulse(Path("/fake/run"), 20.0)
    seen = spy_on_doing(pulse)

    @contextmanager
    def trying(attempt: Any):
        yield

    runtime = SimpleNamespace(
        pulse=pulse,
        stage_log=SimpleNamespace(trying=trying),
        config=SimpleNamespace(gates=SimpleNamespace(stop_check_budget_s=1e9)),
    )
    plan = SimpleNamespace(story=story, role=SimpleNamespace(name="developer-cli"))
    hook = StopChecks(runtime, plan)  # type: ignore[arg-type]

    async def none(_input: Any) -> list[str]:
        return []

    hook._failures = none  # type: ignore[method-assign]
    return hook, seen


def test_stop_checks_carry_the_plans_story(fake: FakeSystem) -> None:
    hook, seen = stop_checks_for(SimpleNamespace(id="s162"))
    asyncio.run(hook.hook({}, None, None))
    assert seen == [(STOP_CHORE.format(role="developer-cli", story="s162"), "s162")]


def test_stop_checks_without_a_story_carry_none(fake: FakeSystem) -> None:
    hook, seen = stop_checks_for(None)
    asyncio.run(hook.hook({}, None, None))
    assert seen == [(STOP_CHORE.format(role="developer-cli", story="-"), None)]


# ----- AC2: health reads the list (CH6) -----


def vitals_of(beat: dict[str, Any] | None) -> Vitals:
    return Vitals(NOW, RunStatus.RUNNING, None, beat, Runner.UP, cfg.HealthLimits(), mono=NOW)


def beating(**over: Any) -> dict[str, Any]:
    base = {"version": 3, "pid": 1, "beat": "beating", "at": NOW, "started_at": NOW - 9}
    return {**base, "step": None, **over}


def test_chores_is_empty_when_not_beating() -> None:
    assert vitals_of(beating(beat="ended", chores=[{"what": "x"}])).chores == []
    assert vitals_of(None).chores == []


def test_chores_is_empty_when_the_key_is_not_a_list() -> None:
    assert vitals_of(beating(chores=None)).chores == []
    assert vitals_of(beating(chores="x")).chores == []
    assert vitals_of(beating()).chore is None


def test_chore_is_the_oldest_open_row() -> None:
    old = {"what": "old", "story": "s1", "since": NOW - 50}
    new = {"what": "new", "story": "s2", "since": NOW - 5}
    v = vitals_of(beating(chores=[old, new]))
    assert v.chores == [old, new] and v.chore == old and v.busy


# ----- AC3: the page, statically (CH7-CH9) -----


def test_the_panel_has_a_chores_container_between_line_and_message() -> None:
    pos = [PAGE.find(f'id="{i}"') for i in ("lp-line", "lp-chores", "lp-msg")]
    assert -1 not in pos and pos == sorted(pos)
    assert re.search(r'class="lp-chores"[^>]*\bhidden\b', PAGE)


def test_the_chore_helpers_exist_and_use_text_not_html() -> None:
    for name in ("openChores", "choreText", "choresLine", "renderChoreRows"):
        assert f"function {name}(" in PAGE, name
    body = PAGE[PAGE.index("function renderChoreRows(") :].split("\n}\n")[0]
    assert "textContent" in body and "innerHTML" not in body and "replaceChildren" in body


def test_both_renderers_rebuild_the_chore_rows() -> None:
    for name in ("renderLivePanel", "renderPanelText"):
        body = PAGE[PAGE.index(f"function {name}(") :].split("\n}\n")[0]
        assert "renderChoreRows(view)" in body, name


def test_the_page_reads_chores_not_chore() -> None:
    assert "heartbeat.chores" in PAGE and "heartbeat.chore " not in PAGE
    assert "heartbeat.chore;" not in PAGE and "heartbeat.chore)" not in PAGE


def test_the_chore_row_style_exists() -> None:
    assert re.search(r"\.lp-chores\[hidden\]\s*\{\s*display:\s*none", PAGE)
    assert re.search(r"(?m)^\s*\.lp-chore\s*\{[^}]*text-overflow:\s*ellipsis", PAGE)


def test_the_fixture_source_and_snapshot_carry_the_list() -> None:
    root = Path(__file__).resolve().parent.parent
    src = system.read_text(root / "scripts/dashboard_fixture/heartbeat.json")
    snap = system.read_text(root / "agile_team/dashboard/fixtures/snapshot.json")
    source, snapshot = json.loads(src), json.loads(snap)
    assert source["version"] == 3 and "chore" not in source
    assert len(source["chores"]) == 1 and snapshot["heartbeat"]["chores"] == source["chores"]
    assert snapshot["heartbeat"]["version"] == 3
