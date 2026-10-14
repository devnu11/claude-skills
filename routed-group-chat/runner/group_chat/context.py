"""What a role sees on its turn: its prompt, the chat rules, the pinned log,
the summary of older turns and the recent turns verbatim.
"""

from __future__ import annotations

from .roster import Role, Roster
from .state import ChatState

RULES = """\
You are @{name} ({title}) in the group chat "{team}". Members: {members}, and the human.
Everyone sees the whole thread. Reply only as yourself, briefly, to the latest message.
Do not speak for other members.
To hand the floor to another member, end with a line: HANDOFF: @<name>
To record a decision, add a line: DECISION: <text>
To raise an open question, add a line: QUESTION: <text>
To close one, add a line: RESOLVED: Q<n>"""


def system_prompt(role: Role, roster: Roster) -> str:
    """The role's own prompt followed by the chat rules."""
    members = ", ".join(f"@{r.name} ({r.title})" for r in roster.roles)
    rules = RULES.format(name=role.name, title=role.title, team=roster.team, members=members)
    return f"{role.prompt}\n\n{rules}"


def user_prompt(role: Role, state: ChatState) -> str:
    """Pinned log, summary and transcript, then the cue for this role."""
    sections = [
        ("PINNED: DECISIONS AND OPEN QUESTIONS", state.log.render()),
        ("SUMMARY OF EARLIER DISCUSSION", state.summary or "(none)"),
        ("RECENT TURNS", "\n\n".join(turn.render() for turn in state.turns) or "(none)"),
    ]
    body = "\n\n".join(f"--- {title} ---\n{text}" for title, text in sections)
    return f"{body}\n\n--- YOUR TURN ---\nReply as @{role.name}."
