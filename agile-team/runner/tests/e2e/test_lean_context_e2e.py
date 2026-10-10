"""s23 end to end: PO session renewal across a driven run, turns in the ledger and Manager data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agile_team import cli
from agile_team.dispatch import ISOLATION_ENV, build_options
from agile_team.ledger import Entry, Tokens
from agile_team.po_session import HANDOFF_FILE, HANDOFF_PROMPT
from agile_team.relay import Note

from ..pipeline_helpers import PO_ROLE, Script, add_story, build, drive


def renewals(rt) -> list[Any]:
    return [e for e in rt.events.events() if e.kind == "po-session"]


def test_driven_run_compacts_at_story_done(make_runtime) -> None:
    """AC1: the done boundary sends /compact on the saved session; the hand-over follows it."""
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    add_story(rt)
    drive(rt)
    (event,) = renewals(rt)
    assert event.data["path"] == "compact" and event.data["reasons"] == ["s1 done"]
    assert event.data["pre_tokens"] == 1000
    assert len(script.compacts) == 1
    assert rt.state.po_renew_due == []


def test_fallback_writes_handoff_and_starts_fresh_with_open_question(make_runtime) -> None:
    """AC1: no compact boundary -> handoff file, fresh session, the open question survives."""
    script = Script()
    script.answers_compact = False
    rt = build(make_runtime, script, steps=["design"])

    async def write_handoff(runtime) -> None:
        path = runtime.config.repo / HANDOFF_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Next: s2 because of the DB choice.")

    script.po = [None, None, write_handoff]
    add_story(rt)
    rt.relay.post(Note("question", "Which DB?", ["s2"]))
    drive(rt)
    (event,) = renewals(rt)
    assert event.data["path"] == "handoff"
    assert rt.state.po_renew_path == "handoff"
    last = script.po_prompts[-1]
    assert "Next: s2 because of the DB choice." in last
    assert "- m1 (blocks s2): Which DB?" in last
    assert HANDOFF_PROMPT in script.po_prompts


def test_turns_reach_the_ledger_events_and_status(make_runtime, configured, capsys) -> None:
    """AC2/AC3: every role step ledgers turns, step-end carries them, status sees the entries."""
    rt = build(make_runtime, Script(), steps=["design", "review"])
    add_story(rt)
    drive(rt)
    entries = rt.ledger.entries()
    assert entries and all(e.turns == 1 for e in entries)
    ends = [e for e in rt.events.events() if e.kind == "step-end"]
    assert ends and all(e.data["turns"] == 1 for e in ends)
    assert cli.main(["--repo", str(configured), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["budget"]["spent_usd"] > 0
    assert PO_ROLE in {e.role for e in entries}


def test_manager_context_flags_long_running_roles(make_runtime) -> None:
    """AC3: a role with two of its last three steps over 30 turns is handed to the Manager."""
    rt = make_runtime()
    for turns in (50, 10, 45):
        rt.ledger.record(Entry("unit-tester", "m", 0.1, "s1", 0.0, Tokens(1000, 10, 0, 0), turns))
    text = rt._manager_context()
    context = json.loads(text[text.index("{") :])
    (item,) = context["long_running_roles"]
    assert item["role"] == "unit-tester" and item["recent_turns"] == [50, 10, 45]
    assert context["spend_by_role"]["unit-tester"]["latest_turns"] == 45


def test_every_query_isolates_connectors(make_runtime) -> None:
    """AC4/L1: options disable claude.ai connectors and load only declared MCP servers."""
    seen: list[Any] = []
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    original = rt.query_fn

    def spy(*, prompt: str, options: Any):
        seen.append(options)
        return original(prompt=prompt, options=options)

    rt.query_fn = spy
    add_story(rt)
    drive(rt)
    assert seen and all(o.strict_mcp_config for o in seen)
    assert all(o.env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false" for o in seen)
    assert ISOLATION_ENV == {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
    assert build_options is not None


def test_role_files_describe_lean_work() -> None:
    """AC4/AC5: the built-in role files carry the lean rules and docs mention renewal."""
    roles = Path(cli.__file__).parent / "roles"
    assert "## Read little" in (roles / "_shared.md").read_text()
    assert "## Work lean" in (roles / "unit-tester.md").read_text()
    assert ".team/po/**" in (roles / "product-owner.md").read_text()
    protocol = Path(cli.__file__).parents[2] / "reference" / "protocol.md"
    assert "po-session" in protocol.read_text()
