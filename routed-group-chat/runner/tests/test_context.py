"""Unit tests for ``context``: the system and user prompts a role sees."""

from __future__ import annotations

import pytest
from group_chat.context import system_prompt, user_prompt
from group_chat.roster import Role, Roster
from group_chat.state import ChatState, Turn

pytestmark = pytest.mark.unit


def test_system_prompt_has_role_prompt_members_and_rules(roster: Roster) -> None:
    text = system_prompt(roster.get("po"), roster)
    assert text.startswith("You own the backlog.")
    assert 'You are @po (Product Owner) in the group chat "leadership"' in text
    assert "@manager (Manager), @po (Product Owner), @liaison (liaison)" in text
    assert "HANDOFF: @<name>" in text


def test_user_prompt_orders_pinned_summary_turns_cue(roster: Roster) -> None:
    state = ChatState(summary="earlier stuff")
    state.add(Turn("human", "@po DECISION: go"))
    text = user_prompt(roster.get("po"), state)
    positions = [
        text.index(s) for s in ("[D1] go", "earlier stuff", "@human: @po", "Reply as @po.")
    ]
    assert positions == sorted(positions)


def test_user_prompt_empty_state(roster: Roster) -> None:
    text = user_prompt(roster.get("manager"), ChatState())
    assert text.count("(none)") == 2


def test_system_prompt_default_team_and_title() -> None:
    roster = Roster("group chat", (Role("qa", "qa", "Test it."),))
    text = system_prompt(roster.get("qa"), roster)
    assert 'You are @qa (qa) in the group chat "group chat"' in text
    assert "Members: @qa (qa), and the human." in text


def test_system_prompt_lists_every_marker(roster: Roster) -> None:
    text = system_prompt(roster.get("manager"), roster)
    for marker in ("DECISION: <text>", "QUESTION: <text>", "RESOLVED: Q<n>"):
        assert marker in text


def test_user_prompt_shows_open_questions_and_summary(roster: Roster) -> None:
    state = ChatState(summary="folded earlier")
    state.add(Turn("po", "QUESTION: who owns QA?"))
    text = user_prompt(roster.get("manager"), state)
    assert "- [Q1] who owns QA? (by po)" in text
    assert "--- SUMMARY OF EARLIER DISCUSSION ---\nfolded earlier" in text


def test_user_prompt_ends_with_cue_for_role(roster: Roster) -> None:
    for name in roster.names():
        assert user_prompt(roster.get(name), ChatState()).endswith(f"Reply as @{name}.")
