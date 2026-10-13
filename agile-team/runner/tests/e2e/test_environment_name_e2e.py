"""s64/s94 end to end: open_story accepts only story files naming configured [[environment]]s."""

from __future__ import annotations

import asyncio
import json

from agile_team import cli, state
from agile_team.po_tools import Tools

from ..conftest import write_story


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def stories_on_disk(rt) -> dict:
    return json.loads((rt.config.run_dir / state.STATE_FILE).read_text())["stories"]


def test_prose_environment_refused_with_names_and_nothing_saved(make_runtime) -> None:
    """AC1: a prose environment in the file is refused, valid names listed, nothing saved."""
    rt = make_runtime()
    write_story(rt.config, "s1", "runner (guard)")
    out = call(Tools(rt).open_story({"id": "s1", "title": "t"}))
    assert out["status"] == "refused"
    assert "not a configured [[environment]]" in out["reason"]
    assert out["reason"].endswith("use one of: cli")
    assert "s1" not in rt.state.stories
    assert not [e for e in rt.events.events() if e.kind == "story-opened"]


def test_exact_name_accepted_and_case_refused(make_runtime, configured, capsys) -> None:
    """AC3: exact name opens; 'CLI' and 'cli ' are refused; status lists the story."""
    rt = make_runtime()
    tools = Tools(rt)
    for bad in ("CLI", '"cli "'):
        write_story(rt.config, "s9", bad)
        assert call(tools.open_story({"id": "s9", "title": "t"}))["status"] == "refused"
    write_story(rt.config, "s1", "cli")
    assert call(tools.open_story({"id": "s1", "title": "t"}))["status"] == "opened"
    assert "s1" in stories_on_disk(rt)
    assert cli.main(["--repo", str(configured), "status"]) == 0
    assert "s1" in json.loads(capsys.readouterr().out)["stories"]


def test_missing_environment_refused(make_runtime) -> None:
    """s94 AC: an AC with no environment is refused."""
    rt = make_runtime()
    write_story(rt.config, "s1")
    out = call(Tools(rt).open_story({"id": "s1", "title": "t"}))
    assert out["status"] == "refused"


def test_no_environments_configured_says_so(make_runtime) -> None:
    """AC4: refusal names no list when none are configured."""
    rt = make_runtime()
    write_story(rt.config, "s1", "cli")
    rt.config.environments.clear()
    out = call(Tools(rt).open_story({"id": "s1", "title": "t"}))
    assert out["status"] == "refused"
    assert "configures no" in out["reason"] and "use one of" not in out["reason"]


def test_duplicate_id_checked_first(make_runtime) -> None:
    """Duplicate id wins over a bad story file."""
    rt = make_runtime()
    tools = Tools(rt)
    write_story(rt.config, "s1", "cli")
    call(tools.open_story({"id": "s1", "title": "t"}))
    write_story(rt.config, "s1", "bogus")
    out = call(tools.open_story({"id": "s1", "title": "t"}))
    assert out["reason"] == "story s1 already exists"
