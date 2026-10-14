from __future__ import annotations

from group_chat.context import system_prompt, user_prompt
from group_chat.roster import Roster
from group_chat.state import ChatState, Turn


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
