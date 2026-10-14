"""Acceptance: the roster rules in reference/protocol.md and the shipped example roster.

Driven through ``group_chat.cli.run`` with a scripted model only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ..conftest import Cli, FakeBackend
from .conftest import EXAMPLE_ROSTER

pytestmark = pytest.mark.acceptance


def roster_cli(tmp_path: Path, backend: FakeBackend, toml: str) -> Cli:
    path = tmp_path / "roster.toml"
    path.write_text(toml)
    return Cli(path, tmp_path / "chat", backend)


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ("team = 'x'\n", "at least one"),
        ("[[role]]\nname='a'\nprompt='p'\n[[role]]\nname='a'\nprompt='q'\n", "twice"),
        ("[[role]]\nname='all'\nprompt='p'\n", "reserved"),
        ("[[role]]\nname='human'\nprompt='p'\n", "reserved"),
        ("[[role]]\nname='orchestrator'\nprompt='p'\n", "reserved"),
        ("[[role]]\nname='Bad'\nprompt='p'\n", "must match"),
        ("[[role]]\nname='a'\nprompt='p'\nprompt_file='a.md'\n", "exactly one"),
        ("[[role]]\nname='a'\n", "exactly one"),
        ("[[role]]\nname='a'\nprompt='  '\n", "empty prompt"),
        ("[[role]]\nname='a'\nprompt_file='missing.md'\n", "missing.md"),
        ("[[role]\n", "roster.toml"),
    ],
)
def test_bad_roster_is_rejected_on_load(
    tmp_path: Path, backend: FakeBackend, toml: str, message: str
) -> None:
    """Rejected on load: no roles, a duplicate name, a reserved name, a name that breaks the
    pattern, both or neither of prompt/prompt_file, an empty or unreadable prompt."""
    cli = roster_cli(tmp_path, backend, toml)
    result = cli.say("@a hi")
    assert result.code == 2
    assert message in result.err
    assert backend.calls == []
    assert not cli.state_file.exists()


def test_prompt_file_is_relative_to_roster(tmp_path: Path, backend: FakeBackend) -> None:
    """`prompt_file = "prompts/po.md"  # relative to the roster file`."""
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "po.md").write_text("You are the PO.\n")
    cli = roster_cli(tmp_path, backend, "[[role]]\nname='po'\nprompt_file='prompts/po.md'\n")
    assert cli.say("@po hi").code == 0
    assert backend.calls[0].system.startswith("You are the PO.")


def test_title_and_model_defaults(tmp_path: Path, backend: FakeBackend) -> None:
    """title: optional; defaults to name. model: optional; defaults to the CLI's model."""
    toml = "team='t'\n[[role]]\nname='qa'\nprompt='p'\n[[role]]\nname='ux'\nprompt='p'\n"
    toml += "title='Designer'\nmodel='opus'\n"
    cli = roster_cli(tmp_path, backend, toml)
    cli.say("@qa @ux hi")
    assert "@qa (qa), @ux (Designer)" in backend.calls[0].system
    assert [c.model for c in backend.calls] == [None, "opus"]


def test_team_is_shown_to_every_role(tmp_path: Path, backend: FakeBackend) -> None:
    """`team = "leadership"  # optional; shown to every role`."""
    cli = roster_cli(tmp_path, backend, "team='core'\n[[role]]\nname='a'\nprompt='p'\n")
    cli.say("@a hi")
    assert 'group chat "core"' in backend.calls[0].system


def test_example_leadership_roster_loads(leadership: Cli) -> None:
    """Steps 1: otherwise start from `examples/leadership.toml` here."""
    result = leadership.say("@all hello")
    assert result.code == 0
    assert [line.split(":")[0] for line in result.out.split("\n\n") if line] == [
        "@liaison",
        "@manager",
        "@po",
        "@proxy",
    ]


def test_example_roster_titles_and_team(leadership: Cli, backend: FakeBackend) -> None:
    """The example roster's team and titles reach every role."""
    leadership.say("@proxy would this pass?")
    system = backend.calls[0].system
    assert system.startswith("You stand in for the customer.")
    assert 'group chat "agile-team leadership"' in system
    assert "@po (Product Owner), @proxy (Customer Proxy)" in system
    assert EXAMPLE_ROSTER.exists()


@pytest.mark.parametrize("command", ["log", "show"])
def test_bad_roster_is_rejected_by_log_and_show(
    tmp_path: Path, backend: FakeBackend, command: str
) -> None:
    """Roster (TOML, validated on load)."""
    cli = roster_cli(tmp_path, backend, "[[role]]\nname='all'\nprompt='p'\n")
    assert cli.run(command).code == 2
