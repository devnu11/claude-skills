"""The ``po-turn`` event names the stories the turn touched (s113, PT1-PT4)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest
from agile_team import po_tools
from agile_team.events import Event, EventKind
from agile_team.po_tools import SCHEMAS, Start, StartMode, Tools, named_stories
from claude_agent_sdk import ResultError

from .conftest import result_message
from .test_halt import limit_error


def test_a_story_argument_names_one_story() -> None:
    assert named_stories("run_role", {"story": "s1", "role": "architect"}) == ["s1"]


def test_a_stories_argument_names_each_story() -> None:
    assert named_stories("ask_user", {"stories": ["s1", "s2"]}) == ["s1", "s2"]


def test_other_tools_do_not_name_through_id() -> None:
    assert named_stories("run_role", {"id": "s9"}) == []


def test_no_story_argument_names_nothing() -> None:
    assert named_stories("budget_status", {}) == []


def test_empty_and_non_string_values_are_skipped() -> None:
    assert named_stories("run_role", {"story": ""}) == []
    assert named_stories("run_role", {"story": 5}) == []
    assert named_stories("ask_user", {"stories": ["s1", 2, "", None]}) == ["s1"]
    assert named_stories("ask_user", {"stories": 7}) == []


def test_both_keys_are_read_for_a_default_tool() -> None:
    assert named_stories("hold_story", {"story": "s1", "stories": ["s2"]}) == ["s1", "s2"]


def test_the_tables_are_data() -> None:
    assert po_tools.STORY_ARGS == {}
    assert po_tools.DEFAULT_STORY_ARGS == ("story", "stories")


def test_touched_keeps_first_named_order_and_drops_repeats() -> None:
    touched = po_tools.Touched()
    touched.note("run_role", {"story": "s2"})
    touched.note("ask_user", {"stories": ["s1", "s2"]})
    touched.note("hold_story", {"story": "s1"})
    touched.note("budget_status", {})
    assert touched.ids == ["s2", "s1"]


def test_touched_starts_empty_and_is_not_shared() -> None:
    first, second = po_tools.Touched(), po_tools.Touched()
    first.note("run_role", {"story": "s1"})
    assert second.ids == []


def test_tools_carry_their_own_touched(make_runtime: Any) -> None:
    rt = make_runtime()
    assert Tools(rt).touched is not Tools(rt).touched


def test_a_noted_call_notes_the_story_before_the_method_runs(make_runtime: Any) -> None:
    tools = Tools(make_runtime())
    seen: list[list[str]] = []

    async def method(args: dict[str, Any]) -> dict[str, Any]:
        seen.append(list(tools.touched.ids))
        return {"ok": True}

    tools.continue_story = method  # type: ignore[method-assign]
    result = asyncio.run(tools.noted("continue_story")({"story": "s1"}))
    assert seen == [["s1"]] and result == {"ok": True}


def test_a_refused_call_still_counts(make_runtime: Any) -> None:
    tools = Tools(make_runtime())
    asyncio.run(tools.noted("continue_story")({"story": "nope"}))
    assert tools.touched.ids == ["nope"]


def test_a_raising_call_still_counts(make_runtime: Any) -> None:
    tools = Tools(make_runtime())

    async def boom(args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("tool broke")

    tools.continue_story = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        asyncio.run(tools.noted("continue_story")({"story": "s1"}))
    assert tools.touched.ids == ["s1"]


def test_every_schema_name_has_a_noted_callable(make_runtime: Any) -> None:
    tools = Tools(make_runtime())
    for name in SCHEMAS:
        assert callable(tools.noted(name))
    assert tools.noted("budget_status") is not None


def test_plan_for_and_po_plan_both_build_a_plan(make_runtime: Any) -> None:
    rt = make_runtime()
    turn = po_tools.PoTurn("go", None)
    assert po_tools.plan_for(Tools(rt), turn).prompt == "go"
    assert po_tools.po_plan(rt, turn).prompt == "go"


class TurnTools(Tools):
    """Records every ``Tools`` the PO run builds, so a fake PO can call them."""

    made: ClassVar[list[Tools]] = []

    def __post_init__(self) -> None:
        TurnTools.made.append(self)

    async def ask_user(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    async def run_role(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}


class CallingPo:
    """A fake PO query that calls tools by name, then ends or raises ``then``."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]], then: BaseException | None = None):
        self.calls, self.then = calls, then

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for name, args in self.calls:
            await TurnTools.made[-1].noted(name)(args)
        if self.then:
            raise self.then
        yield result_message("PO text", session="po-sess")


def po_turns(rt: Any) -> list[Event]:
    return [e for e in rt.events.events() if e.kind is EventKind.PO_TURN]


def run_po(rt: Any) -> None:
    asyncio.run(po_tools.run_po(rt, Start("", StartMode.RESUME)))


@pytest.fixture
def recording(monkeypatch: pytest.MonkeyPatch) -> None:
    TurnTools.made = []
    monkeypatch.setattr(po_tools, "Tools", TurnTools)


@pytest.mark.usefixtures("recording")
def test_the_po_turn_event_names_the_stories_called(make_runtime: Any) -> None:
    calls = [
        ("continue_story", {"story": "s1"}),
        ("ask_user", {"stories": ["s2", "s1"]}),
        ("budget_status", {}),
        ("hold_story", {"story": "s2"}),
    ]
    rt = make_runtime(CallingPo(calls))
    rt.state.po_session = "po-sess"
    run_po(rt)
    (turn, *_) = po_turns(rt)
    assert turn.data["stories"] == ["s1", "s2"]
    assert turn.story is None


@pytest.mark.usefixtures("recording")
def test_a_turn_that_called_no_story_tool_has_an_empty_list(make_runtime: Any) -> None:
    rt = make_runtime(CallingPo([("budget_status", {})]))
    rt.state.po_session = "po-sess"
    run_po(rt)
    assert po_turns(rt)
    assert all(t.data["stories"] == [] for t in po_turns(rt))


@pytest.mark.usefixtures("recording")
def test_each_turn_has_its_own_stories(make_runtime: Any) -> None:
    rt = make_runtime(CallingPo([("run_role", {"story": "s1", "role": "x"})]))
    rt.state.po_session = "po-sess"
    run_po(rt)
    run_po(rt)
    assert all(t.data["stories"] == ["s1"] for t in po_turns(rt))


@pytest.mark.usefixtures("recording")
def test_a_raising_query_still_emits_its_stories(make_runtime: Any) -> None:
    po = CallingPo([("continue_story", {"story": "s7"})], then=limit_error())
    rt = make_runtime(po)
    rt.state.po_session = "po-sess"
    with pytest.raises(ResultError):
        run_po(rt)
    turns = po_turns(rt)
    assert turns and turns[0].data["stories"] == ["s7"]
