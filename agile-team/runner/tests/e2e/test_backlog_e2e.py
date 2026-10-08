"""s3 end to end: backlog and sprint membership through real files and the CLI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agile_team import cli, state
from agile_team.po_tools import Tools

BACKLOG_REFUSAL = "story {} is in the backlog; add it to a sprint"


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def cli_status(repo: Path, capsys) -> dict:
    assert cli.main(["--repo", str(repo), "status"]) == 0
    return json.loads(capsys.readouterr().out)


def open_all(tools: Tools, *ids: str) -> None:
    for sid in ids:
        call(tools.open_story({"id": sid, "title": sid}))


def test_opened_stories_start_in_backlog_on_disk(make_runtime, configured, capsys) -> None:
    """s3/AC1: new stories persist with sprint null; CLI status shows it (s3/AC4)."""
    rt = make_runtime()
    open_all(Tools(rt), "s1", "s2")
    raw = json.loads((rt.config.run_dir / state.STATE_FILE).read_text())
    assert raw["stories"]["s1"]["sprint"] is None
    report = cli_status(configured, capsys)
    assert {k: v["sprint"] for k, v in report["stories"].items()} == {"s1": None, "s2": None}


def test_start_sprint_membership_flow(make_runtime, configured, capsys) -> None:
    """s3/AC2, AC4: listed stories join; unlisted unfinished go back; done stay put."""
    rt = make_runtime()
    tools = Tools(rt)
    open_all(tools, "s1", "s2", "s3")
    call(tools.start_sprint({"goal": "one", "stories": ["s1", "s2", "s3"]}))
    rt.state.stories["s3"].status = state.StoryStatus.DONE
    rt.save()
    out = call(tools.start_sprint({"goal": "two", "stories": ["s1"]}))
    assert out["sprint"] == 2
    assert rt.events.events()[-1].data == {"sprint": 2, "goal": "two", "stories": ["s1"]}
    report = cli_status(configured, capsys)
    assert {k: v["sprint"] for k, v in report["stories"].items()} == {
        "s1": 2,
        "s2": None,
        "s3": 1,
    }


def test_start_sprint_refuses_unknown_story(make_runtime) -> None:
    """s3/AC2: unknown ids are refused with a reason and nothing changes."""
    rt = make_runtime()
    tools = Tools(rt)
    open_all(tools, "s1")
    out = call(tools.start_sprint({"goal": "g", "stories": ["s1", "nope"]}))
    assert out["status"] == "refused"
    assert "nope" in out["reason"]
    assert rt.state.sprint == 0
    assert rt.state.stories["s1"].sprint is None


def test_run_role_on_backlog_story_refused_exactly(make_runtime) -> None:
    """s3/AC3: story-bound run_role on a backlog story gets the exact refusal."""
    rt = make_runtime()
    tools = Tools(rt)
    open_all(tools, "s1")
    out = call(tools.run_role({"role": "architect", "brief": "b", "story": "s1"}))
    assert out == {"status": "refused", "reason": BACKLOG_REFUSAL.format("s1")}


def test_manager_unaffected_by_backlog(make_runtime) -> None:
    """s3/AC3: story-less roles are not blocked by backlog stories."""
    rt = make_runtime()
    tools = Tools(rt)
    open_all(tools, "s1")
    out = call(tools.run_role({"role": "manager", "brief": "b", "story": ""}))
    assert out["status"] == "done"


def test_sprint_story_is_not_refused_as_backlog(make_runtime) -> None:
    """s3/AC3: once in a sprint, the backlog refusal no longer applies."""
    rt = make_runtime()
    tools = Tools(rt)
    open_all(tools, "s1")
    call(tools.start_sprint({"goal": "g", "stories": ["s1"]}))
    call(tools.run_role({"role": "manager", "brief": "b", "story": ""}))
    out = call(tools.run_role({"role": "architect", "brief": "b", "story": "s1"}))
    assert "backlog" not in out.get("reason", "")


def test_legacy_state_without_sprint_loads(configured, capsys) -> None:
    """s3/AC1: a state.json predating the field loads; stories default to backlog."""
    run_dir = configured / ".team" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    legacy = {
        "status": "running",
        "sprint": 1,
        "stories": {"s1": {"id": "s1", "title": "Old", "step": "design", "rounds": 0}},
    }
    (run_dir / state.STATE_FILE).write_text(json.dumps(legacy))
    report = cli_status(configured, capsys)
    assert report["stories"]["s1"]["sprint"] is None
