"""PO MCP tools and the PO loop."""

import asyncio
import json

import pytest
from agile_team import po_tools
from agile_team.po_tools import Start, StartMode, Tools
from agile_team.providers import Provider, Providers
from agile_team.state import RunStatus

from .conftest import FakeQuery


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def test_open_story_and_status(make_runtime) -> None:
    t = Tools(make_runtime())
    assert call(t.open_story({"id": "s1", "title": "Add", "delivery": "cli"}))["step"] == "design"
    assert call(t.open_story({"id": "s1", "title": "Add"}))["status"] == "refused"
    status = call(t.story_status({}))
    assert status["stories"]["s1"]["delivery"] == "cli"
    opened = t.runtime.events.events()
    assert len(opened) == 1 and opened[0].data == {"title": "Add", "step": "design"}
    assert "developer" in status["roles"]


def open_stories(t: Tools, *ids: str) -> None:
    for sid in ids:
        call(t.open_story({"id": sid, "title": sid}))


def test_open_story_starts_in_backlog(make_runtime) -> None:
    t = Tools(make_runtime())
    open_stories(t, "s1")
    assert t.runtime.state.stories["s1"].sprint is None
    assert call(t.story_status({}))["stories"]["s1"]["sprint"] is None


def test_start_sprint_requires_manager(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s1")
    out = call(t.start_sprint({"goal": "MVP", "stories": ["s1"]}))
    assert out == {"sprint": 1, "stories": ["s1"], "next": "run the manager"}
    event = rt.events.events()[-1]
    assert event.data == {"sprint": 1, "goal": "MVP", "stories": ["s1"]}
    assert rt.state.stories["s1"].sprint == 1
    assert rt.state.manager_due == ["sprint 1 start: MVP (s1)"]
    assert "manager review due" in call(t.run_role({"role": "architect", "brief": "b"}))["reason"]
    assert call(t.run_role({"role": "manager", "brief": "b", "story": ""}))["status"] == "done"
    assert rt.state.manager_due == []


def test_start_sprint_manager_due_lists_stories(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s1", "s2")
    call(t.start_sprint({"goal": "G", "stories": ["s1", "s2"]}))
    assert rt.state.manager_due == ["sprint 1 start: G (s1, s2)"]


def test_start_sprint_dedupes_ids(make_runtime) -> None:
    t = Tools(make_runtime())
    open_stories(t, "s1", "s2")
    out = call(t.start_sprint({"goal": "G", "stories": ["s2", "s1", "s2"]}))
    assert out["stories"] == ["s2", "s1"]
    assert t.runtime.events.events()[-1].data["stories"] == ["s2", "s1"]


def test_start_sprint_replaces_scope(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s1", "s2", "s3")
    call(t.start_sprint({"goal": "one", "stories": ["s1", "s2"]}))
    rt.state.stories["s2"].status = "done"
    out = call(t.start_sprint({"goal": "two", "stories": ["s3"]}))
    assert out["sprint"] == 2
    sprints = {k: v.sprint for k, v in rt.state.stories.items()}
    assert sprints == {"s1": None, "s2": 1, "s3": 2}


def test_start_sprint_carries_over_listed_story(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s1")
    call(t.start_sprint({"goal": "one", "stories": ["s1"]}))
    call(t.start_sprint({"goal": "two", "stories": ["s1"]}))
    assert rt.state.stories["s1"].sprint == 2


def test_start_sprint_listing_done_story_leaves_it(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s1")
    call(t.start_sprint({"goal": "one", "stories": ["s1"]}))
    rt.state.stories["s1"].status = "done"
    call(t.start_sprint({"goal": "two", "stories": ["s1"]}))
    assert rt.state.stories["s1"].sprint == 1


def snapshot(rt) -> tuple:
    state_file = rt.config.run_dir / "state.json"
    text = state_file.read_text() if state_file.is_file() else None
    return (rt.state.to_json(), text, len(rt.events.events()))


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"goal": "G"}, "no stories listed; pass the story ids this sprint commits to"),
        (
            {"goal": "G", "stories": []},
            "no stories listed; pass the story ids this sprint commits to",
        ),
        (
            {"goal": "G", "stories": ["s1", "s9", "s7"]},
            "unknown stories: s9, s7; open them with open_story first",
        ),
    ],
)
def test_start_sprint_refusals_have_no_side_effects(make_runtime, args, reason) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s1")
    rt.save()
    before = snapshot(rt)
    out = call(t.start_sprint(args))
    assert out == {"status": "refused", "reason": reason}
    assert snapshot(rt) == before
    assert rt.state.sprint == 0 and rt.state.manager_due == []
    assert rt.state.stories["s1"].sprint is None


def test_story_status_shows_sprint(make_runtime) -> None:
    t = Tools(make_runtime())
    open_stories(t, "s1", "s2")
    call(t.start_sprint({"goal": "G", "stories": ["s1"]}))
    status = call(t.story_status({}))
    assert status["sprint"] == 1
    assert status["stories"]["s1"]["sprint"] == 1
    assert status["stories"]["s2"]["sprint"] is None


def test_start_sprint_schema_takes_stories_list() -> None:
    desc, schema = po_tools.SCHEMAS["start_sprint"]
    assert schema == {"goal": str, "stories": list}
    assert "backlog" in desc


def test_ask_notify_and_wait(make_runtime) -> None:
    rt = make_runtime()
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)
        rt.relay.answer("m1", "sqlite")

    t = Tools(rt, sleep=sleep)
    q = call(t.ask_user({"text": "DB?", "stories": ["s1"]}))
    assert q == {"id": "m1", "blocks": ["s1"]}
    assert call(t.wait_for_answers({"ids": ["m1"]})) == {"m1": "sqlite"}
    assert slept == [po_tools.POLL_S]
    call(t.notify_user({"text": "progress"}))
    assert rt.state.status != "sprint-end"
    call(t.notify_user({"text": "review", "kind": "sprint-end"}))
    assert rt.state.status == "sprint-end"


def test_wait_times_out(make_runtime) -> None:
    async def sleep(_s: float) -> None:
        return None

    t = Tools(make_runtime(), sleep=sleep)
    call(t.ask_user({"text": "?"}))
    assert call(t.wait_for_answers({"ids": ["m1"], "timeout_s": 10})) == {}


OVERRIDE = {
    "role": "developer",
    "provider": "anthropic",
    "model": "opus",
    "effort": "high",
    "reason": "hard",
}


def test_budget_and_set_role_model(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    assert call(t.budget({}))["budget_usd"] == 10.0
    assert (
        call(
            t.set_role_model(
                {"role": "x", "provider": "anthropic", "model": "m", "effort": "e", "reason": "r"}
            )
        )["status"]
        == "refused"
    )
    assert "reason" in call(t.set_role_model({**OVERRIDE, "reason": ""}))["reason"]
    assert call(t.set_role_model(OVERRIDE))["status"] == "set"
    assert rt.state.overrides["developer"].model == "opus"
    assert "review model override for developer" in rt.state.manager_due
    assert rt.events.events()[-1].data["reason"] == OVERRIDE["reason"]


def test_mcp_server_and_names() -> None:
    names = po_tools.tool_names()
    assert "mcp__team__run_role" in names and len(names) == len(po_tools.SCHEMAS)


def test_run_po_records_cost_and_session(make_runtime) -> None:
    q = FakeQuery("All done.", cost=0.5)
    rt = make_runtime(q)
    result = asyncio.run(po_tools.run_po(rt, Start("Build a todo CLI")))
    assert result.text == "All done."
    opts = q.calls[0]["options"]
    assert opts.model == "opus" and "team" in opts.mcp_servers
    assert "mcp__team__ask_user" in opts.allowed_tools
    assert "Build a todo CLI" in q.calls[0]["prompt"] and "Cadence: sprint" in q.calls[0]["prompt"]
    assert rt.ledger.by_role() == {"product-owner": 0.5}
    assert rt.ledger.entries()[0].tokens.total() == 460
    assert rt.state.po_session == "sess" and rt.state.status == "idle"


def test_run_po_resume_and_onboard(make_runtime) -> None:
    q = FakeQuery("ok")
    rt = make_runtime(q)
    rt.state.po_session = "old"
    asyncio.run(po_tools.run_po(rt, Start("", StartMode.RESUME)))
    assert q.calls[0]["options"].resume == "old"
    assert q.calls[0]["prompt"] == po_tools.RESUME_NOTE
    asyncio.run(po_tools.run_po(rt, Start("Also fix X", StartMode.RESUME)))
    assert q.calls[1]["prompt"].endswith("New from the human:\nAlso fix X")
    rt.state.status = RunStatus.DONE
    asyncio.run(po_tools.run_po(rt, Start("t", StartMode.ONBOARD)))
    assert "onboarding sprint" in q.calls[2]["prompt"]


def test_set_role_model_moves_a_role_between_providers(make_runtime) -> None:
    rt = make_runtime(providers=Providers({"local": Provider("local", "http://localhost:11434")}))
    rt.book.config_roles["scribe"] = {"provider": "local", "model": "qwen3-coder"}
    assert "scribe (local: qwen3-coder)" in po_tools.first_prompt(rt, Start("t"))
    t = Tools(rt)
    ghost = call(t.set_role_model({**OVERRIDE, "role": "scribe", "provider": "ghost"}))
    assert ghost["reason"] == "unknown provider 'ghost'"
    call(t.set_role_model({**OVERRIDE, "role": "scribe", "model": "sonnet"}))
    assert rt.resolve("scribe").provider == "anthropic"
    assert rt.resolve("scribe").model == "sonnet"
