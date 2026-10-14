"""Unit tests for ``roster``: loading and validating roster TOML."""

from __future__ import annotations

from pathlib import Path

import pytest
from group_chat.roster import ROLE_FIELDS, TOP_FIELDS, Role, Roster, RosterError, load, parse

pytestmark = pytest.mark.unit


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
        ({"role": [role(name=3)]}, "name must be a str"),
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


def test_title_and_model_are_kept() -> None:
    parsed = parse({"role": [role(title="Boss", model="opus")]}, Path())
    assert parsed.roles[0] == Role("manager", "Boss", "p", "opus")


def test_non_string_title_is_rejected() -> None:
    with pytest.raises(RosterError, match="title must be a str"):
        parse({"role": [role(title=7)]}, Path())


def test_non_string_model_is_rejected() -> None:
    with pytest.raises(RosterError):
        parse({"role": [role(model=3)]}, Path())


def test_name_with_trailing_newline_is_rejected() -> None:
    with pytest.raises(RosterError):
        parse({"role": [role(name="po\n")]}, Path())


@pytest.mark.parametrize("name", ["a", "a" * 32, "qa-2", "x9"])
def test_valid_names(name: str) -> None:
    assert parse({"role": [role(name=name)]}, Path()).names() == (name,)


@pytest.mark.parametrize("name", ["a" * 33, "2a", "-a", "a_b", "", "orchestrator"])
def test_invalid_names(name: str) -> None:
    with pytest.raises(RosterError):
        parse({"role": [role(name=name)]}, Path())


def test_prompt_is_stripped() -> None:
    assert parse({"role": [role(prompt="\n  hi  \n")]}, Path()).roles[0].prompt == "hi"


def test_empty_prompt_file(tmp_path: Path) -> None:
    (tmp_path / "e.md").write_text("\n\n")
    with pytest.raises(RosterError, match="empty prompt"):
        parse({"role": [{"name": "a", "prompt_file": "e.md"}]}, tmp_path)


def test_role_must_be_array_of_tables() -> None:
    with pytest.raises(RosterError, match="role must be a list"):
        parse({"role": {"name": "a"}}, Path())


def test_non_string_team_is_rejected() -> None:
    with pytest.raises(RosterError, match="team must be a str"):
        parse({"team": 5, "role": [role()]}, Path())


def test_roster_order_is_kept() -> None:
    data = {"role": [role(name="z"), role(name="a"), role(name="m")]}
    assert parse(data, Path()).names() == ("z", "a", "m")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"teem": "x", "role": [role()]}, r"roster has unknown key\(s\): teem"),
        ({"role": [role(modle="opus")]}, r"each \[\[role\]\] has unknown key\(s\): modle"),
        ({"role": [role(prompt=1)]}, "prompt must be a str"),
        ({"role": [{"name": "a", "prompt_file": 1}]}, "prompt_file must be a str"),
        ({"role": "x"}, "role must be a list"),
        ({"role": [role(model=None)]}, "model must be a str"),
    ],
)
def test_unknown_keys_and_wrong_types_are_refused(data: dict[str, object], message: str) -> None:
    with pytest.raises(RosterError, match=message):
        parse(data, Path())


def test_roster_must_be_a_table() -> None:
    with pytest.raises(RosterError, match="roster must be a table"):
        parse([], Path())  # type: ignore[arg-type]


def test_field_tables_cover_documented_keys() -> None:
    assert set(TOP_FIELDS) == {"team", "role"}
    assert set(ROLE_FIELDS) == {"name", "title", "model", "prompt", "prompt_file"}


def test_load_reports_non_utf8_roster(tmp_path: Path) -> None:
    path = tmp_path / "r.toml"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(RosterError, match=r"r\.toml"):
        load(path)


def test_non_utf8_prompt_file(tmp_path: Path) -> None:
    (tmp_path / "p.md").write_bytes(b"\xff\xfe")
    with pytest.raises(RosterError, match=r"p\.md"):
        parse({"role": [{"name": "a", "prompt_file": "p.md"}]}, tmp_path)
