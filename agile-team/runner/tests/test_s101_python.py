"""Open calls in the heartbeat, ``GET /api/misc`` and its helpers (s101, N11, N12)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import tool_calls as tc
from agile_team.dashboard import server, snapshot
from agile_team.dashboard import tool_groups as tg
from agile_team.dashboard.server import Dashboard
from agile_team.dashboard.tool_groups import MiscAsk

from .fake_system import FakeSystem
from .test_s98_live import PO, WHO, asks, pulse_of
from .test_s98_snapshot import span
from .test_server import Wire
from .test_snapshot import FIXTURE_TEXT, make_config, write_jsonl
from .test_tool_calls import SPAN_KEYS, WHERE, calls, mark, result, use

# ----- tool_calls: start_row, open_row, Calls.opened (N11) -----


def test_start_row_has_the_span_keys_up_to_slept_in_order() -> None:
    call = tc.Call.of(use("u1", "Read", file_path="a.py"), mark(5.0))
    row = tc.start_row(WHERE, call)
    assert list(row) == SPAN_KEYS[: SPAN_KEYS.index("slept") + 1]
    assert row["at"] == 5.0 and row["tool_use_id"] == "u1"


def test_open_row_adds_the_open_status() -> None:
    call = tc.Call.of(use("u1"), mark(5.0))
    row = tc.open_row(WHERE, call)
    assert list(row) == [*SPAN_KEYS[: SPAN_KEYS.index("slept") + 1], "status"]
    assert row["status"] == "open" == tc.OPEN


def test_opened_lists_open_calls_in_opening_order_and_empties_when_finished() -> None:
    c = calls()
    c.start([use("u1"), use("u2")], mark(1.0))
    assert [r["tool_use_id"] for r in c.opened()] == ["u1", "u2"]
    c.finish([result("u1")], mark(2.0))
    assert [r["tool_use_id"] for r in c.opened()] == ["u2"]
    c.finish([result("u2")], mark(3.0))
    assert c.opened() == []


def test_a_span_dict_keeps_its_keys() -> None:
    c = calls()
    c.start([use("u1")], mark(1.0))
    c.finish([result("u1")], mark(2.0))
    assert list(c.spans[0].as_dict()) == SPAN_KEYS


# ----- live: heartbeat calls (N11) -----


def test_heartbeat_calls_hold_every_open_meter_outer_first(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    outer = pulse.open(PO)
    outer.take(asks("p1", "mcp__team__run_role", role="architect"))
    inner = pulse.open(WHO)
    inner.take(asks("b1", command="ls"))
    beat = pulse.heartbeat()
    assert [c["tool_use_id"] for c in beat["calls"]] == ["p1", "b1"]
    assert all(c["status"] == "open" for c in beat["calls"])
    keys = list(beat)
    assert keys.index("calls") == keys.index("step") + 1


def test_heartbeat_calls_are_empty_without_open_calls_and_after_end(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(WHO)
    assert pulse.heartbeat()["calls"] == []
    meter.take(asks("b1"))
    assert len(pulse.heartbeat()["calls"]) == 1
    pulse.end()
    assert pulse.heartbeat()["calls"] == []


# ----- tool_groups: ask_key, gathered_calls (N12) -----


def ask(role: str = "developer", story: str = "s1", step: str = "implement", at: str = "1.0"):
    return MiscAsk(role, story, step, at)


def test_ask_key_turns_empty_story_and_step_into_none() -> None:
    assert tg.ask_key(ask()) == ("developer", "s1", "implement", 1.0)
    assert tg.ask_key(ask(story="", step="")) == ("developer", None, None, 1.0)


@pytest.mark.parametrize(
    "bad", [ask(role=""), ask(at=""), ask(at="x"), ask(at="nan"), ask(at="inf")]
)
def test_ask_key_is_none_for_a_bad_ask(bad: MiscAsk) -> None:
    assert tg.ask_key(bad) is None


def test_miscask_fields() -> None:
    assert MiscAsk._fields == ("role", "story", "step", "opened_at")


def test_gathered_calls_are_the_misc_rows_of_that_group_sorted_by_at() -> None:
    rows = [
        span(0.03, 5.0),
        span(5.0, 4.0),
        span(0.01, 2.0, "Bash"),
        span(0.02, 3.0, role="architect"),
        {"role": "developer"},  # invalid
    ]
    got = tg.gathered_calls(rows, ("developer", "s1", "implement", 1.0), 0.1)
    assert [r["at"] for r in got] == [2.0, 5.0]
    assert got[0] is rows[2]
    assert tg.gathered_calls(rows, ("nobody", "s1", "implement", 1.0), 0.1) == []


# ----- snapshot.misc_calls -----


def test_misc_calls_use_the_tail_and_the_configured_limit(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    write_jsonl(config.run_dir / tc.TOOLS, [span(0.01, 1.0), span(5.0, 2.0), span(0.02, 3.0)])
    got = snapshot.misc_calls(config, ask())
    assert got is not None and [r["at"] for r in got] == [1.0, 3.0]
    zero = make_config(scratch / "repo", dashboard={"collapse_under_s": 0})
    assert snapshot.misc_calls(zero, ask()) == []


def test_misc_calls_are_none_for_a_bad_ask(scratch: Path) -> None:
    assert snapshot.misc_calls(make_config(scratch / "repo"), ask(role="")) is None


def test_the_fixture_heartbeat_has_the_open_call_and_three_tool_groups() -> None:
    fixture = json.loads(FIXTURE_TEXT)
    beat = fixture["heartbeat"]
    keys = list(beat)
    assert keys.index("calls") == keys.index("step") + 1
    (open_call,) = beat["calls"]
    assert open_call["status"] == "open" and open_call["tool_use_id"] == "toolu_open"
    assert list(open_call) == [*SPAN_KEYS[: SPAN_KEYS.index("slept") + 1], "status"]
    groups = fixture["tools"]
    assert len(groups) == 3
    po = next(g for g in groups if g["role"] == "product-owner")
    assert po["opened_at"] != 0.0
    turn = next(e for e in fixture["events"] if e["kind"] == "po-turn")
    assert po["opened_at"] == turn["data"]["opened_at"]


# ----- GET /api/misc -----


def misc_app(seen: list[MiscAsk] | None = None) -> Dashboard:
    def read(a: MiscAsk) -> list[dict[str, Any]] | None:
        if seen is not None:
            seen.append(a)
        return None if tg.ask_key(a) is None else [{"tool": "Read", "at": 1.0}]

    return Dashboard(lambda: {}, lambda: [], misc_calls=read)


def get_misc(app: Dashboard, query: str) -> Wire:
    wire = Wire(f"/api/misc{query}", app)
    server.Handler.do_GET(wire)  # type: ignore[arg-type]
    return wire


def test_misc_route_returns_a_json_array() -> None:
    wire = get_misc(misc_app(), "?role=developer&story=s1&step=implement&opened_at=1.0")
    assert wire.status == 200
    assert wire.header("Content-Type").startswith("application/json")
    assert json.loads(wire.body) == [{"tool": "Read", "at": 1.0}]


def test_misc_route_passes_first_values_and_empty_when_missing() -> None:
    seen: list[MiscAsk] = []
    get_misc(misc_app(seen), "?role=a&role=b&opened_at=2")
    assert seen == [MiscAsk("a", "", "", "2")]


def test_misc_route_404s_on_a_bad_opened_at_and_by_default() -> None:
    assert get_misc(misc_app(), "?role=developer&opened_at=zzz").status == 404
    plain = Dashboard(lambda: {}, lambda: [])
    assert plain.misc_calls(ask()) is None
    assert get_misc(plain, "?role=developer&opened_at=1").status == 404
