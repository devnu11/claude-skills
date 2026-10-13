"""s64 end to end: open_story accepts only configured [[environment]] names."""

from __future__ import annotations

import asyncio
import json

from agile_team import cli, state
from agile_team.po_tools import Tools


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def stories_on_disk(rt) -> dict:
    return json.loads((rt.config.run_dir / state.STATE_FILE).read_text())["stories"]


def test_prose_environment_refused_with_names_and_nothing_saved(make_runtime) -> None:
    """AC1: prose is refused, valid names listed, no state or event change."""
    rt = make_runtime()
    out = call(Tools(rt).open_story({"id": "s1", "title": "t", "environment": "runner (guard)"}))
    assert out["status"] == "refused"
    assert "not a configured [[environment]]" in out["reason"]
    assert out["reason"].endswith("use one of: cli")
    assert "s1" not in rt.state.stories
    assert not [e for e in rt.events.events() if e.kind == "story-opened"]


def test_exact_name_accepted_and_case_refused(make_runtime, configured, capsys) -> None:
    """AC3: exact name opens; 'CLI' and 'cli ' are refused; status shows the acceptance environment."""
    rt = make_runtime()
    tools = Tools(rt)
    for bad in ("CLI", "cli "):
        assert (
            call(tools.open_story({"id": "s9", "title": "t", "environment": bad}))["status"]
            == "refused"
        )
    ok = call(tools.open_story({"id": "s1", "title": "t", "environment": "cli"}))
    assert ok["status"] == "opened"
    assert stories_on_disk(rt)["s1"]["environment"] == "cli"
    assert cli.main(["--repo", str(configured), "status"]) == 0
    assert "s1" in json.loads(capsys.readouterr().out)["stories"]


def test_empty_environment_accepted(make_runtime) -> None:
    """Empty acceptance environment still means the first configured one."""
    rt = make_runtime()
    assert call(Tools(rt).open_story({"id": "s1", "title": "t"}))["status"] == "opened"


def test_no_environments_configured_says_so(make_runtime) -> None:
    """AC4: refusal names no list when none are configured."""
    rt = make_runtime()
    rt.config.environments.clear()
    out = call(Tools(rt).open_story({"id": "s1", "title": "t", "environment": "cli"}))
    assert out["status"] == "refused"
    assert "configures none" in out["reason"] and "use one of" not in out["reason"]


def test_duplicate_id_checked_first(make_runtime) -> None:
    """Duplicate id wins over a bad acceptance environment."""
    rt = make_runtime()
    tools = Tools(rt)
    call(tools.open_story({"id": "s1", "title": "t"}))
    out = call(tools.open_story({"id": "s1", "title": "t", "environment": "bogus"}))
    assert out["reason"] == "story s1 already exists"
