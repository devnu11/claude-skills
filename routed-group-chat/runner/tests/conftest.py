"""Shared fixtures: a three-role roster and a scripted backend."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from group_chat.roster import Role, Roster

ROSTER_TOML = """\
team = "leadership"

[[role]]
name = "manager"
title = "Manager"
prompt = "You manage delivery."

[[role]]
name = "po"
title = "Product Owner"
prompt_file = "po.md"
model = "haiku"

[[role]]
name = "liaison"
prompt = "You relay to the team."
"""

CUE_RE = re.compile(r"Reply as @([a-z][a-z0-9-]*)\.$")


@dataclass
class Call:
    system: str
    prompt: str
    model: str | None


@dataclass
class FakeBackend:
    """Answers from a script keyed by the role named in the prompt's cue."""

    replies: dict[str, list[str]] = field(default_factory=dict)
    summary: str = "SUMMARY"
    calls: list[Call] = field(default_factory=list)

    def complete(self, system: str, prompt: str, model: str | None) -> str:
        self.calls.append(Call(system, prompt, model))
        cue = CUE_RE.search(prompt)
        if cue is None:
            return self.summary
        queue = self.replies.get(cue.group(1), [])
        return queue.pop(0) if queue else f"{cue.group(1)} reply"


@pytest.fixture
def roster() -> Roster:
    return Roster(
        "leadership",
        (
            Role("manager", "Manager", "You manage delivery."),
            Role("po", "Product Owner", "You own the backlog.", "haiku"),
            Role("liaison", "liaison", "You relay to the team."),
        ),
    )


@pytest.fixture
def roster_file(tmp_path: Path) -> Path:
    (tmp_path / "po.md").write_text("You own the backlog.\n")
    path = tmp_path / "roster.toml"
    path.write_text(ROSTER_TOML)
    return path


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


MakeBackend = Callable[..., FakeBackend]
