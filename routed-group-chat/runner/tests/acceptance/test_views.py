"""Acceptance: `log`, `show`, compaction and what each role sees, through the CLI.

Rules quoted from SKILL.md and reference/protocol.md; only the model is scripted.
"""

from __future__ import annotations

import json

import pytest

from ..conftest import Cli, FakeBackend

pytestmark = pytest.mark.acceptance


def test_log_prints_decisions_and_open_questions(cli: Cli, backend: FakeBackend) -> None:
    """`log` prints pinned decisions and open questions."""
    backend.replies = {"po": ["DECISION: cut search\nQUESTION: who tests?"]}
    cli.say("@po scope?")
    result = cli.run("log")
    assert result.code == 0
    assert result.out == (
        "## Decisions\n- [D1] cut search (by po)\n## Open questions\n- [Q1] who tests? (by po)\n"
    )


def test_show_prints_summary_and_recent_turns(cli: Cli) -> None:
    """`show` prints the summary and recent turns."""
    cli.say("@po hi")
    result = cli.run("show")
    assert result.out == "--- summary ---\n(none)\n\n@human: @po hi\n\n@po: po reply\n\n"


def test_compaction_keeps_last_four_turns(cli: Cli, backend: FakeBackend) -> None:
    """The oldest turns are folded into the summary, always keeping the last 4 turns."""
    # Given a tiny token budget
    backend.summary = "they talked"
    # When several messages are exchanged
    for word in ("one", "two", "three"):
        cli.say(f"@po {word}", flags=["--recent-tokens", "1"])
    # Then exactly the last 4 turns stay verbatim and the rest are in the summary
    shown = cli.run("show").out
    assert shown.startswith("--- summary ---\nthey talked\n")
    turns = json.loads(cli.state_file.read_text())["turns"]
    assert [t["text"] for t in turns] == ["@po two", "po reply", "@po three", "po reply"]


def test_compaction_never_folds_the_log(cli: Cli, backend: FakeBackend) -> None:
    """The decision log is never folded."""
    cli.say("@po DECISION: cut search\nQUESTION: who tests?", flags=["--recent-tokens", "1"])
    for i in range(5):
        cli.say(f"@po filler {i}", flags=["--recent-tokens", "1"])
    assert "@po DECISION" not in cli.run("show").out
    log = cli.run("log").out
    assert "- [D1] cut search (by human)" in log
    assert "- [Q1] who tests? (by human)" in log
    assert "- [D1] cut search (by human)" in backend.calls[-2].prompt


def test_no_compaction_under_default_budget(cli: Cli, backend: FakeBackend) -> None:
    """Compaction runs only if the verbatim turns exceed `--recent-tokens` (default 6000)."""
    for i in range(5):
        cli.say(f"@po msg {i}")
    assert len(backend.calls) == 5
    assert cli.run("show").out.startswith("--- summary ---\n(none)")


def test_role_sees_sections_in_order(cli: Cli, backend: FakeBackend) -> None:
    """What each role sees: prompt + rules (system); pinned log; summary; recent turns; cue."""
    cli.say("@po DECISION: go")
    cli.say("@manager ok?")
    call = backend.calls[-1]
    assert call.system.startswith("You manage delivery.")
    assert "Members: @manager (Manager), @po (Product Owner), @liaison (liaison)" in call.system
    order = ["--- PINNED", "--- SUMMARY", "--- RECENT TURNS", "Reply as @manager."]
    positions = [call.prompt.index(part) for part in order]
    assert positions == sorted(positions)


def test_state_is_written_after_every_message(cli: Cli) -> None:
    """`<dir>/state.json`: turns, summary, last addressee and decision log, written after
    every message."""
    cli.say("@po hi")
    data = json.loads(cli.state_file.read_text())
    assert set(data) == {"turns", "summary", "last_addressed", "log"}
    cli.say("@manager hi")
    assert len(json.loads(cli.state_file.read_text())["turns"]) == 4
