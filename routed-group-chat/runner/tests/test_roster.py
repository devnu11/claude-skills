from __future__ import annotations

from pathlib import Path

import pytest
from group_chat.roster import Role, Roster, RosterError, load, parse


def role(**fields: object) -> dict[str, object]:
    return {"name": "manager", "prompt": "p", **fields}


def test_load_reads_inline_and_file_prompts(roster_file: Path) -> None:
    roster = load(roster_file)
    assert roster.team == "leadership"
    assert roster.names() == ("manager", "po", "liaison")
    assert roster.get("po") == Role("po", "Product Owner", "You own the backlog.", "haiku")
    assert roster.get("liaison").title == "liaison"


def test_load_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RosterError, match=r"nope\.toml"):
        load(tmp_path / "nope.toml")


def test_load_reports_bad_toml(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("[[role]\n")
    with pytest.raises(RosterError, match=r"bad\.toml"):
        load(path)


def test_default_team_name() -> None:
    assert parse({"role": [role()]}, Path()).team == "group chat"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "at least one"),
        ({"role": []}, "at least one"),
        ({"role": ["x"]}, "must be a table"),
        ({"role": [role(name="Bad Name")]}, "must match"),
        ({"role": [role(name=3)]}, "must match"),
        ({"role": [role(name="all")]}, "reserved"),
        ({"role": [role(name="human")]}, "reserved"),
        ({"role": [{"name": "a"}]}, "exactly one"),
        ({"role": [role(prompt_file="x.md")]}, "exactly one"),
        ({"role": [role(prompt="  ")]}, "empty prompt"),
        ({"role": [role(), role()]}, "appears twice"),
    ],
)
def test_parse_rejects(data: dict[str, object], message: str) -> None:
    with pytest.raises(RosterError, match=message):
        parse(data, Path())


def test_missing_prompt_file(tmp_path: Path) -> None:
    data = {"role": [{"name": "a", "prompt_file": "gone.md"}]}
    with pytest.raises(RosterError, match=r"gone\.md"):
        parse(data, tmp_path)


def test_get_unknown_role(roster: Roster) -> None:
    with pytest.raises(RosterError, match="nobody"):
        roster.get("nobody")


def test_example_roster_is_valid() -> None:
    example = Path(__file__).parents[2] / "examples" / "leadership.toml"
    assert load(example).names() == ("liaison", "manager", "po", "proxy")
