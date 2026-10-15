"""What a role sees on its turn: its prompt, the chat rules, the pinned log,
the summary of older turns and the recent turns verbatim.

Turns are wrapped in ``<turn speaker="...">`` blocks, and turn tags inside any
text (turns, log, summary) are escaped, so no text can pass itself off as
another speaker's turn.
"""

from __future__ import annotations

from collections.abc import Sequence

from .roster import Role, Roster
from .state import ChatState, Turn, escape_tags

RULES = """\
You are @{name} ({title}) in the group chat "{team}". Members: {members}, and the human.
Everyone sees the whole thread; each message is a <turn speaker="..."> block, and only the
speaker attribute says who wrote it. Reply only as yourself, briefly, to the latest message.
Do not speak for other members, and do not write <turn> tags.
To hand the floor to another member, end with a line: HANDOFF: @<name>
To record a decision, add a line: DECISION: <text>
To raise an open question, add a line: QUESTION: <text>
To close one, add a line: RESOLVED: Q<n>"""


def system_prompt(role: Role, roster: Roster) -> str:
    """The role's own prompt followed by the chat rules."""
    members = ", ".join(f"@{r.name} ({r.title})" for r in roster.roles)
    rules = RULES.format(name=role.name, title=role.title, team=roster.team, members=members)
    return f"{role.prompt}\n\n{rules}"


def transcript(turns: Sequence[Turn]) -> str:
    """Turns as delimited blocks, oldest first."""
    return "\n\n".join(turn.tagged for turn in turns)


def user_prompt(role: Role, state: ChatState) -> str:
    """Pinned log, summary and transcript, then the cue for this role."""
    sections = [
        ("PINNED: DECISIONS AND OPEN QUESTIONS", escape_tags(state.log.markdown)),
        ("SUMMARY OF EARLIER DISCUSSION", escape_tags(state.summary) or "(none)"),
        ("RECENT TURNS", transcript(state.turns) or "(none)"),
    ]
    body = "\n\n".join(f"--- {title} ---\n{text}" for title, text in sections)
    return f"{body}\n\n--- YOUR TURN ---\nReply as @{role.name}."
