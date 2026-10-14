"""Acceptance: the markers table and handoff rules in reference/protocol.md, via the CLI.

Each scenario drives ``group_chat.cli.run`` with a scripted model only.
"""

from __future__ import annotations

import pytest

from ..conftest import Cli, FakeBackend

pytestmark = pytest.mark.acceptance


def test_decision_marker_pins_numbered_decision(cli: Cli, backend: FakeBackend) -> None:
    """`DECISION: <text>` pins decision `D<n>`."""
    # Given a role that records a decision and a human who records one
    backend.replies = {"po": ["Agreed.\nDECISION: ship v1 Friday"]}
    # When both speak
    cli.say("@po DECISION: weekly demo")
    # Then both are pinned, numbered in order, with their author
    log = cli.run("log").out
    assert "- [D1] weekly demo (by human)" in log
    assert "- [D2] ship v1 Friday (by po)" in log


def test_question_marker_opens_question(cli: Cli) -> None:
    """`QUESTION: <text>` opens question `Q<n>`."""
    cli.say("@manager QUESTION: who owns QA?")
    assert "- [Q1] who owns QA? (by human)" in cli.run("log").out


def test_resolved_marker_closes_question(cli: Cli, backend: FakeBackend) -> None:
    """`RESOLVED: Q<n>` closes that question."""
    # Given two open questions
    cli.say("@manager QUESTION: who owns QA?\nQUESTION: budget?")
    # When a role resolves the first
    backend.replies = {"manager": ["Dana does.\nRESOLVED: Q1"]}
    cli.say("@manager answer?")
    # Then only the second stays open
    log = cli.run("log").out
    assert "[Q1]" not in log
    assert "- [Q2] budget? (by human)" in log


def test_marker_after_leading_mentions(cli: Cli) -> None:
    """A marker starts its line, optionally after leading @mentions."""
    cli.say("@po DECISION: cut search")
    assert "- [D1] cut search (by human)" in cli.run("log").out


def test_marker_mid_line_is_ignored(cli: Cli) -> None:
    """A marker starts its line; one later in the line is plain text."""
    cli.say("@po we said DECISION: maybe")
    assert "## Decisions\n- none" in cli.run("log").out


def test_handoff_passes_the_floor(cli: Cli, backend: FakeBackend) -> None:
    """`HANDOFF: @<name>` (role replies only): next turn goes to `<name>`."""
    backend.replies = {"manager": ["Not mine.\nHANDOFF: @po"]}
    result = cli.say("@manager scope?")
    assert result.out == "@manager: Not mine.\nHANDOFF: @po\n\n@po: po reply\n\n"


def test_human_handoff_line_is_ignored(cli: Cli) -> None:
    """HANDOFF applies to role replies only."""
    result = cli.say("@manager hi\nHANDOFF: @po")
    assert result.out == "@manager: manager reply\n\n"


@pytest.mark.parametrize("target", ["manager", "cto"])
def test_handoff_to_self_or_unknown_is_ignored(cli: Cli, backend: FakeBackend, target: str) -> None:
    """A handoff to yourself or an unknown name is ignored."""
    backend.replies = {"manager": [f"HANDOFF: @{target}"]}
    result = cli.say("@manager x")
    assert result.out == f"@manager: HANDOFF: @{target}\n\n"


def test_handoff_cap_records_orchestrator_note(cli: Cli, backend: FakeBackend) -> None:
    """Past `--max-handoffs` per human message, the runner records an `@orchestrator` note."""
    # Given roles that keep handing the floor on
    backend.replies = {
        "manager": ["HANDOFF: @po"],
        "po": ["HANDOFF: @liaison"],
        "liaison": ["HANDOFF: @manager"],
    }
    # When the default cap (2) is exceeded
    result = cli.say("@manager go")
    # Then three roles answer and the dropped hop is noted in the thread
    assert "@liaison: HANDOFF: @manager\n\n@orchestrator: handoff to @manager dropped" in result.out
    assert "@orchestrator: handoff to @manager dropped" in cli.run("show").out


def test_max_handoffs_flag(cli: Cli, backend: FakeBackend) -> None:
    """The runner caps hops per message (`--max-handoffs`)."""
    backend.replies = {"manager": ["HANDOFF: @po"]}
    result = cli.say("@manager go", flags=["--max-handoffs", "0"])
    assert result.out.strip().splitlines()[-1].startswith("@orchestrator: handoff to @po dropped")


def test_handoff_after_leading_mentions(cli: Cli, backend: FakeBackend) -> None:
    """A marker starts its line, optionally after leading @mentions."""
    backend.replies = {"manager": ["@human over to PO.\n@po HANDOFF: @po"]}
    result = cli.say("@manager scope?")
    assert "@po: po reply" in result.out


@pytest.mark.parametrize("line", ["- DECISION: cut search", "- **DECISION:** cut search"])
def test_bulleted_and_bold_markers_count(cli: Cli, line: str) -> None:
    """decision_log: a marker may follow a `-`/`*` bullet or `**` bold."""
    cli.say(f"@po notes\n{line}")
    assert "- [D1] cut search (by human)" in cli.run("log").out


def test_fenced_markers_are_ignored(cli: Cli, backend: FakeBackend) -> None:
    """decision_log: "Lines inside ``` fenced code blocks never count"."""
    backend.replies = {"po": ["Format:\n```\nDECISION: <text>\nQUESTION: <text>\n```"]}
    cli.say("@po how do I pin things?")
    assert cli.run("log").out == "## Decisions\n- none\n## Open questions\n- none\n"


def test_one_resolved_line_closes_several_questions(cli: Cli, backend: FakeBackend) -> None:
    """decision_log: `RESOLVED: Q<n>[, Q<m>]` closes those questions."""
    cli.say("@manager QUESTION: who owns QA?\nQUESTION: budget?\nQUESTION: date?")
    backend.replies = {"manager": ["Settled.\nRESOLVED: q1, Q3."]}
    cli.say("@manager answers?")
    log = cli.run("log").out
    assert "## Open questions\n- [Q2] budget? (by human)\n" in log
    assert "[Q1]" not in log
    assert "[Q3]" not in log


def test_blank_marker_is_ignored(cli: Cli) -> None:
    """decision_log: "a marker with blank text is ignored"."""
    cli.say("@po DECISION:   ")
    assert "## Decisions\n- none" in cli.run("log").out


def test_handoff_to_queued_role_is_skipped(cli: Cli, backend: FakeBackend) -> None:
    """chat: "A handoff ... to a role already waiting in this message's queue is ignored"."""
    # Given everyone is addressed and the manager hands to the PO who is already queued
    backend.replies = {"manager": ["HANDOFF: @po"]}
    # When the human broadcasts
    result = cli.say("@all status?")
    # Then each role answers once and no hop or note is recorded
    assert result.out == "@manager: HANDOFF: @po\n\n@po: po reply\n\n@liaison: liaison reply\n\n"


def test_handoff_name_is_case_insensitive(cli: Cli, backend: FakeBackend) -> None:
    """chat: HANDOFF is case-insensitive on the name."""
    backend.replies = {"manager": ["- **HANDOFF:** @PO"]}
    assert cli.say("@manager scope?").out.endswith("@po: po reply\n\n")


def test_negative_max_handoffs_is_refused(cli: Cli, backend: FakeBackend) -> None:
    """cli: `--max-handoffs` must be >= 0."""
    with pytest.raises(SystemExit) as exc:
        cli.say("@po hi", flags=["--max-handoffs", "-1"])
    assert exc.value.code == 2
    assert backend.calls == []
