"""s1: requirement files: parsing, the checks across files, coverage, the report, the briefs."""

from __future__ import annotations

import pytest
from agile_team import requirements as rq

FOLDER = "docs/requirements"


def path(n: int | str = 1) -> str:
    name = f"REQ-{n:03d}" if isinstance(n, int) else n
    return f"{FOLDER}/{name}.md"


def text(
    id: str = "REQ-001",
    title: str = "Title",
    status: str = "active",
    covers: str = '["s1/AC1"]',
    body: str = "In plain words.",
) -> str:
    return f"---\nid: {id}\ntitle: {title}\nstatus: {status}\ncovers: {covers}\n---\n\n{body}\n"


def parse(content: str | None, file: str | None = None) -> rq.Parsed:
    return rq.parse(rq.Source(file or path(1), content))


def line(problem: str, file: str | None = None) -> str:
    return f"{file or path(1)}: {problem}"


def story(name: str, *acs: str) -> rq.StoryAcs:
    return rq.StoryAcs(name, tuple(acs))


def checked(*files: tuple[str, str | None], stories: dict | None = None) -> rq.Checked:
    sources = tuple(rq.Source(f, t) for f, t in files)
    found = rq.Found(FOLDER, sources, stories if stories is not None else {})
    return rq.check(found)


# ---- parse: a clean file (AC1)


def test_clean_file_parses_to_a_requirement() -> None:
    got = parse(text(covers='["s1/AC1", "s94/A14c"]', body="\n  Body here.  \n"))
    assert got.problems == ()
    assert got.requirement == rq.Requirement(
        "REQ-001",
        "Title",
        rq.Status.ACTIVE,
        (rq.Ref("s1", "AC1"), rq.Ref("s94", "A14c")),
        "Body here.",
        path(1),
    )


def test_retired_status_and_empty_covers_are_clean() -> None:
    got = parse(text(status="retired", covers="[]"))
    assert got.problems == ()
    assert got.requirement.status is rq.Status.RETIRED
    assert got.requirement.covers == ()


def test_other_frontmatter_keys_are_ignored() -> None:
    assert parse(text().replace("title:", "owner: me\ntitle:")).problems == ()


def test_claimed_id_is_kept_even_when_the_file_has_problems() -> None:
    got = parse(text(title='""'))
    assert got.claimed == "REQ-001" and got.requirement is None


# ---- parse: one test per row


def test_row1_unreadable_gives_only_that_line() -> None:
    assert parse(None).problems == (line("cannot be read"),)


def test_row2_bad_name() -> None:
    got = parse(text(id="REQ-1"), path("REQ-1"))
    msg = "the file name must be REQ-NNN.md (REQ- and three or more digits)"
    assert got.problems == (line(msg, path("REQ-1")),)


@pytest.mark.parametrize("name", ["REQ-001.markdown", "req-001", "REQ-0a1", "XREQ-001"])
def test_row2_names_that_do_not_fullmatch(name: str) -> None:
    got = parse(text(id=name), f"{FOLDER}/{name}.md")
    assert any("the file name must be REQ-NNN.md" in p for p in got.problems)


def test_row2_four_digits_is_a_good_name() -> None:
    assert parse(text(id="REQ-1000"), path("REQ-1000")).problems == ()


def test_row3_no_frontmatter_gives_only_that_line() -> None:
    msg = "no YAML frontmatter; start the file with --- and the keys id, title, status and covers"
    assert parse("just words\n").problems == (line(msg),)


def test_row4_bad_yaml_gives_only_that_line() -> None:
    got = parse("---\nid: [\n---\nbody\n")
    assert len(got.problems) == 1
    assert got.problems[0].startswith(line("frontmatter does not parse: "))


def test_row4_frontmatter_that_is_not_a_mapping() -> None:
    got = parse("---\n- a\n- b\n---\nbody\n")
    assert len(got.problems) == 1
    assert got.problems[0].startswith(line("frontmatter does not parse: "))


def test_row5_wrong_id() -> None:
    got = parse(text(id="REQ-009"))
    assert got.problems == (line("id is 'REQ-009', not 'REQ-001' (the file name)"),)


def test_row5_missing_id_is_none() -> None:
    got = parse(text().replace("id: REQ-001\n", ""))
    assert got.problems == (line("id is None, not 'REQ-001' (the file name)"),)


@pytest.mark.parametrize("title", ['""', "[a]", "  "])
def test_row6_no_title(title: str) -> None:
    assert parse(text(title=title)).problems == (line("title must be a non-empty string"),)


def test_row7_bad_status() -> None:
    got = parse(text(status="draft"))
    assert got.problems == (line("status is 'draft'; use active or retired"),)


def test_row7_missing_status_is_none() -> None:
    got = parse(text().replace("status: active\n", ""))
    assert got.problems == (line("status is None; use active or retired"),)


@pytest.mark.parametrize("covers", ['"s1/AC1"', "{a: b}", "7"])
def test_row8_covers_not_a_list_skips_the_item_checks(covers: str) -> None:
    msg = 'covers must be a list of "sN/ACk" strings'
    assert parse(text(covers=covers)).problems == (line(msg),)


def test_row8_missing_covers() -> None:
    got = parse(text().replace('covers: ["s1/AC1"]\n', ""))
    assert got.problems == (line('covers must be a list of "sN/ACk" strings'),)


def test_row9_bad_ref_item_numbers_from_one() -> None:
    got = parse(text(covers='["s1/AC1", "S2/AC1", 5]'))
    assert got.problems == (
        line("covers item 2: 'S2/AC1' is not \"sN/ACk\""),
        line('covers item 3: 5 is not "sN/ACk"'),
    )


def test_row10_repeated_ref() -> None:
    got = parse(text(covers='["s1/AC1", "s1/AC2", "s1/AC1"]'))
    assert got.problems == (line("covers item 3: 's1/AC1' is listed twice"),)


@pytest.mark.parametrize("body", ["", "   \n\n"])
def test_row11_no_text(body: str) -> None:
    got = parse(text(body=body))
    assert got.problems == (line("the body is empty; state the requirement in plain words"),)


def test_several_problems_are_all_listed_in_table_order() -> None:
    got = parse(text(id="REQ-009", title='""', status="draft", body=""))
    assert [p.split(": ", 1)[1].split(" ")[0] for p in got.problems] == [
        "id",
        "title",
        "status",
        "the",
    ]
    assert got.requirement is None


def test_problem_texts_table_has_all_fifteen_rows() -> None:
    assert len(rq.Problem) == 15 and set(rq.PROBLEMS) == set(rq.Problem)


# ---- parse_ref


@pytest.mark.parametrize(
    ("value", "ref"),
    [
        ("s1/AC1", rq.Ref("s1", "AC1")),
        ("s94/A14c", rq.Ref("s94", "A14c")),
        ("s2/a-b_c", rq.Ref("s2", "a-b_c")),
    ],
)
def test_parse_ref_accepts(value: str, ref: rq.Ref) -> None:
    assert rq.parse_ref(value) == ref
    assert ref.text() == value


@pytest.mark.parametrize(
    "value", ["S1/AC1", "s1/", "s1AC1", "1/AC1", "s1/AC1 x", " s1/AC1", 7, None, ["s1/AC1"]]
)
def test_parse_ref_rejects(value: object) -> None:
    assert rq.parse_ref(value) is None


# ---- check across files (T4)


def test_duplicate_id_flags_both_files_and_the_wrong_id() -> None:
    got = checked((path(1), text()), (path(2), text(id="REQ-001")))
    first, second = got.files
    assert first.problems[0].startswith(f"{path(1)}: id 'REQ-001' is also used by ")
    assert path(2) in first.problems[0]
    assert second.problems[0] == line("id is 'REQ-001', not 'REQ-002' (the file name)", path(2))
    assert second.problems[1].startswith(f"{path(2)}: id 'REQ-001' is also used by ")
    assert path(1) in second.problems[1]


def test_duplicate_id_counts_a_file_with_other_problems() -> None:
    got = checked((path(1), text()), (path(2), text(id="REQ-001", title='""')))
    assert any("also used by" in p for p in got.files[0].problems)


def test_duplicate_id_names_every_other_file_in_order() -> None:
    files = [(path(n), text(id="REQ-001")) for n in (1, 2, 10)]
    got = checked(*files, stories={"s1": story("s1", "AC1")})
    assert got.files[0].problems == (
        f"{path(1)}: id 'REQ-001' is also used by {path(2)}, {path(10)}",
    )


def test_unique_ids_have_no_duplicate_problem() -> None:
    got = checked(
        (path(1), text()), (path(2), text(id="REQ-002")), stories={"s1": story("s1", "AC1")}
    )
    assert got.problems() == []


def test_ref_to_a_story_without_a_file() -> None:
    got = checked((path(1), text(covers='["s9/AC1"]')), stories={})
    assert got.problems() == [line("covers item 1: 's9/AC1': no story file for s9")]


def test_ref_to_a_story_file_with_problems_quotes_the_first() -> None:
    bad = rq.StoryAcs("s2", problems=("first line", "second line"))
    got = checked((path(1), text(covers='["s2/AC1"]')), stories={"s2": bad})
    msg = "covers item 1: 's2/AC1': the story file of s2 has problems (first line)"
    assert got.problems() == [line(msg)]


def test_ref_to_a_missing_ac_lists_the_acs() -> None:
    got = checked((path(1), text(covers='["s1/AC9"]')), stories={"s1": story("s1", "AC1", "AC2")})
    msg = "covers item 1: 's1/AC9': s1 has no AC AC9; its ACs are AC1, AC2"
    assert got.problems() == [line(msg)]


def test_cross_checks_skip_files_with_their_own_problems() -> None:
    got = checked((path(1), text(title='""', covers='["s9/AC1"]')), stories={})
    assert got.problems() == [line("title must be a non-empty string")]


def test_cross_check_lines_come_in_item_order_after_the_files_own() -> None:
    got = checked(
        (path(1), text(covers='["s8/AC1", "s9/AC1"]')),
        stories={},
    )
    assert got.problems() == [
        line("covers item 1: 's8/AC1': no story file for s8"),
        line("covers item 2: 's9/AC1': no story file for s9"),
    ]


def test_problems_follow_file_order() -> None:
    got = checked((path(1), text(status="x")), (path(2), text(id="REQ-002", status="y")))
    assert [p.split(":")[0] for p in got.problems()] == [path(1), path(2)]


# ---- coverage (T5)


STORIES = {"s1": story("s1", "AC1", "AC2"), "s2": story("s2", "AC1")}


def test_active_requirements_cover_their_acs() -> None:
    got = checked((path(1), text(covers='["s1/AC1"]')), stories=STORIES)
    assert got.covering(rq.Ref("s1", "AC1")) == ["REQ-001"]
    assert got.covering(rq.Ref("s1", "AC2")) == []
    assert [r.id for r in got.counting()] == ["REQ-001"]


def test_retired_and_broken_requirements_cover_nothing() -> None:
    got = checked(
        (path(1), text(status="retired")),
        (path(2), text(id="REQ-002", title='""')),
        stories=STORIES,
    )
    assert got.counting() == []
    assert got.covering(rq.Ref("s1", "AC1")) == []


def test_a_requirement_with_a_cross_file_problem_covers_nothing() -> None:
    got = checked((path(1), text(covers='["s1/AC1", "s1/AC9"]')), stories=STORIES)
    assert got.counting() == []


def test_two_requirements_cover_one_ac_in_natural_order() -> None:
    got = checked(
        (path(2), text(id="REQ-002")),
        (path(10), text(id="REQ-010")),
        stories=STORIES,
    )
    assert got.covering(rq.Ref("s1", "AC1")) == ["REQ-002", "REQ-010"]


def test_touching_matches_the_story_ref_in_raw_text_even_when_broken() -> None:
    broken = "---\nid: [\ncovers: s7/AC2\n---\nx"
    got = checked((path(1), broken), (path(2), text(id="REQ-002", covers='["s70/AC1"]')))
    assert [p.source.file for p in got.touching("s7")] == [path(1)]


# ---- coverage dict and report (T7)


def test_coverage_lists_every_readable_story_and_ac() -> None:
    got = checked((path(1), text(covers='["s1/AC2"]')), stories=STORIES)
    assert rq.coverage(got) == {"s1": {"AC1": [], "AC2": ["REQ-001"]}, "s2": {"AC1": []}}


def test_coverage_orders_stories_naturally_and_skips_unreadable() -> None:
    stories = {
        "s10": story("s10", "AC1"),
        "s2": story("s2", "AC1"),
        "s3": rq.StoryAcs("s3", problems=("p",)),
    }
    got = checked(stories=stories)
    assert list(rq.coverage(got)) == ["s2", "s10"]


def test_report_has_problems_coverage_and_unreadable_in_order() -> None:
    stories = {
        "s1": story("s1", "AC1"),
        "s100": rq.StoryAcs("s100", problems=("a: bad", "a: worse")),
    }
    got = checked((path(1), text(status="draft")), stories=stories)
    out = rq.report(got)
    assert list(out) == ["problems", "coverage", "unreadable"]
    assert out["problems"] == [line("status is 'draft'; use active or retired")]
    assert out["coverage"] == {"s1": {"AC1": []}}
    assert out["unreadable"] == {"s100": ["a: bad", "a: worse"]}


def test_report_of_nothing() -> None:
    assert rq.report(checked()) == {"problems": [], "coverage": {}, "unreadable": {}}


# ---- design reasons (T12)


HEAD = "s1's ACs must be traced to active requirements in docs/requirements/ before design passes:"
UNTRACED = (
    "s1/AC2 is covered by no active requirement; "
    "add it to an active REQ's covers or write a new REQ-NNN.md"
)


def test_no_reasons_when_every_ac_is_covered() -> None:
    got = checked((path(1), text(covers='["s1/AC1", "s1/AC2"]')), stories=STORIES)
    assert rq.design_reasons(got, "s1") == []


def test_an_untraced_ac_is_listed_under_the_head() -> None:
    got = checked((path(1), text()), stories=STORIES)
    assert rq.design_reasons(got, "s1") == [HEAD, f"- {UNTRACED}"]


def test_a_broken_file_that_touches_the_story_comes_first() -> None:
    got = checked((path(1), text(covers='["s1/AC1"]', status="draft")), stories=STORIES)
    reasons = rq.design_reasons(got, "s1")
    assert reasons[0] == HEAD
    assert reasons[1] == f"- {line('status is ' + repr('draft') + '; use active or retired')}"
    assert reasons[2:] == [f"- {UNTRACED}".replace("s1/AC2", "s1/AC1"), f"- {UNTRACED}"]


def test_a_broken_file_that_does_not_touch_the_story_is_no_reason() -> None:
    got = checked(
        (path(1), text(covers='["s1/AC1", "s1/AC2"]')),
        (path(2), text(id="REQ-002", covers='["s2/AC1"]', status="draft")),
        stories=STORIES,
    )
    assert rq.design_reasons(got, "s1") == []


def test_a_story_without_a_file_is_a_reason() -> None:
    got = checked((path(1), text()), stories={})
    reasons = rq.design_reasons(got, "s1")
    assert "- no story file for s1" in reasons


def test_a_story_file_with_problems_lists_each_line() -> None:
    bad = rq.StoryAcs("s1", problems=("f: one", "f: two"))
    got = checked(stories={"s1": bad})
    reasons = rq.design_reasons(got, "s1")
    assert reasons == [HEAD, "- f: one", "- f: two"]


# ---- next id and the briefs (T13)


def test_next_id_is_one_above_the_highest_number() -> None:
    got = checked((path(1), text()), (path(5), text(id="REQ-005")), (path(10), text(id="REQ-010")))
    assert rq.next_id(got) == "REQ-011"


def test_next_id_with_no_files() -> None:
    assert rq.next_id(checked()) == "REQ-001"


def test_next_id_pads_to_three_digits() -> None:
    assert rq.next_id(checked((path(8), text(id="REQ-008")))) == "REQ-009"


COVERAGE_HEAD = (
    "## Requirements\n\n"
    "The story's ACs and the active requirements that cover them (`docs/requirements/`). "
    "Cite these ids in your findings.\n\n"
)


def test_coverage_section() -> None:
    got = checked((path(1), text(title="Requirements are structured files")), stories=STORIES)
    want = COVERAGE_HEAD + "- AC1: REQ-001 (Requirements are structured files)\n- AC2: untraced"
    assert rq.coverage_section(got, "s1").rstrip("\n") == want


def test_coverage_section_with_two_requirements_lists_both() -> None:
    got = checked(
        (path(1), text(title="One")),
        (path(2), text(id="REQ-002", title="Two")),
        stories={"s1": story("s1", "AC1")},
    )
    section = rq.coverage_section(got, "s1")
    assert "REQ-001 (One)" in section and "REQ-002 (Two)" in section


def test_coverage_section_for_a_story_file_with_problems() -> None:
    got = checked(stories={"s1": rq.StoryAcs("s1", problems=("p",))})
    section = rq.coverage_section(got, "s1")
    assert "- the story file has problems; see the design gate" in section
    assert "AC1" not in section


def test_design_section_adds_the_index_and_the_next_id() -> None:
    got = checked(
        (path(1), text(title="Structured", covers='["s1/AC1", "s1/AC7"]')),
        (path(2), text(id="REQ-002", title="Gone", status="retired")),
        stories=STORIES,
    )
    section = rq.design_section(got, "s1")
    assert section.startswith(rq.coverage_section(got, "s1"))
    assert (
        "Active requirements (add the story's ACs to one's `covers`, "
        "or write REQ-003.md, the next free id):"
    ) in section
    assert "- REQ-001 Structured: s1/AC1, s1/AC7" in section
    assert "REQ-002 Gone" not in section


def test_briefs_table_names_the_three_roles() -> None:
    assert {
        "architect": rq.design_section,
        "code-reviewer": rq.coverage_section,
        "customer-proxy": rq.coverage_section,
    } == rq.BRIEFS
