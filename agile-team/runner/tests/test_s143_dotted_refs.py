"""s143: requirement references accept dotted AC ids such as s141/AC1.1."""

from __future__ import annotations

import pytest
from agile_team import requirements as rq


def requirement(covers: str) -> str:
    return f"---\nid: REQ-001\ntitle: T\nstatus: active\ncovers: {covers}\n---\n\nIn plain words.\n"


def parsed(covers: str) -> rq.Parsed:
    return rq.parse(rq.Source("docs/requirements/REQ-001.md", requirement(covers)))


@pytest.mark.parametrize(
    ("value", "story", "ac"),
    [
        ("s141/AC1.1", "s141", "AC1.1"),
        ("s141/AC8.3", "s141", "AC8.3"),
        ("s1/AC1.2.3", "s1", "AC1.2.3"),
        ("s2/a-b_c.d", "s2", "a-b_c.d"),
        ("s1/AC1", "s1", "AC1"),
        ("s94/A14c", "s94", "A14c"),
        ("s2/a-b_c", "s2", "a-b_c"),
    ],
)
def test_accepts_with_round_trip(value: str, story: str, ac: str) -> None:
    ref = rq.parse_ref(value)
    assert ref == rq.Ref(story, ac)
    assert ref.text() == value


@pytest.mark.parametrize(
    "value",
    [
        "/AC1.1",
        "AC1.1",
        "141/AC1.1",
        "S141/AC1.1",
        "s141/",
        "s141",
        "s141/.1",
        "s141/1.1",
        "s141/AC1 1",
        "s141/AC1:1",
        "s141/AC1/1",
        "s141/AC1.1!",
        " s141/AC1.1",
        "s141/AC1.1 ",
    ],
)
def test_refuses_malformed(value: str) -> None:
    assert rq.parse_ref(value) is None


def test_dotted_cover_has_no_bad_ref() -> None:
    result = parsed('["s141/AC1.1"]')
    assert not any("is not" in p for p in result.problems)
    assert result.requirement is not None


def test_malformed_cover_is_bad_ref() -> None:
    result = parsed('["s141/AC1 1"]')
    assert any(
        p.endswith("""covers item 1: 's141/AC1 1' is not "sN/ACk\"""") for p in result.problems
    )
