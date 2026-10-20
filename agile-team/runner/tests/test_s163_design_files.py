"""s163 F1/F2: the design's ## Files section and the design gate that demands it."""

from __future__ import annotations

from agile_team import gates, shares
from agile_team.design_files import FILES_HEADING, parse_files
from agile_team.gates import Verdict
from agile_team.roles import Handoff

from .test_s120_gates import at, pipe
from .test_s120_shares import entry


def test_the_heading_is_files() -> None:
    assert FILES_HEADING == "## Files"


def test_bullets_backticks_and_trailing_notes_are_stripped_f1() -> None:
    text = "# T\n\n## Files\n\n- `a/b.py` (new)\n* c/d.py\ne/*.md  glob\n\n"
    assert parse_files(text) == ["a/b.py", "c/d.py", "e/*.md"]


def test_the_section_ends_at_the_next_heading_f1() -> None:
    text = "## Files\n- a.py\n## Other\n- b.py\n"
    assert parse_files(text) == ["a.py"]


def test_a_sub_heading_line_also_ends_the_section_f1() -> None:
    assert parse_files("## Files\n- a.py\n# Top\n- b.py\n") == ["a.py"]


def test_a_missing_heading_gives_nothing_f1() -> None:
    assert parse_files("# T\n- a.py\n") == []


def test_an_empty_section_gives_nothing_f1() -> None:
    assert parse_files("## Files\n\n\n## Next\n- a.py\n") == []


def test_empty_text_gives_nothing_f1() -> None:
    assert parse_files("") == []


def test_the_design_gate_bounces_a_done_design_with_no_files_section_f2() -> None:
    p = pipe(shares.Check(shares.Listed()), "# design\n")
    out = p.evaluate(at("design"), Handoff("done"))
    assert out.verdict is Verdict.BOUNCE
    assert gates.FILES_MISSING.format(file="docs/design/s1.md") in out.reason


def test_designed_passes_a_design_with_a_files_section_f2() -> None:
    p = pipe(shares.Check(shares.Listed()), "## Files\n- a.py\n")
    assert p.checks.designed(at("design")).verdict is Verdict.PASS


def test_a_files_heading_with_no_entry_is_missing_f2() -> None:
    p = pipe(shares.Check(shares.Listed()), "## Files\n\n")
    assert "## Files" in p.checks.designed(at("design")).reason


def test_files_missing_is_listed_with_the_other_reasons_f2() -> None:
    p = pipe(shares.Check(shares.Listed((entry(),))), "")
    reasons = p.checks.designed(at("design")).reason.splitlines()
    assert len(reasons) == 2
    assert any(r == gates.FILES_MISSING.format(file="docs/design/s1.md") for r in reasons)
