"""s101: static checks of the nested tool rows in the dashboard page (N1-N15, AC-R).

Behaviour checks need node (a process), so they live in the e2e suite.
"""

import re
from importlib import resources

from agile_team import system


def page() -> str:
    """Text of the dashboard page."""
    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_the_nested_tables_have_their_exact_values() -> None:
    text = page()
    assert (
        "const NEST = { LANE_H: 44, STRIP_H: 8, INDENT: 12, MIN_DETAIL_CHARS: 8, MISC_PAD: 8 };"
        in text
    )
    assert 'const TOOL_WAITING = new Set(["po.run_role"]);' in text
    assert 'const MODEL_LOOK = { outcome: "model", fill: "--s4" };' in text
    assert 'const NO_CALLS = "no tool calls";' in text
    assert 'const MISC_LOADING = "loading", MISC_FAILED = "failed";' in text
    assert (
        'const MISC_TITLE = "misc: gathered from across the step, not placed on the time axis";'
        in text
    )


def test_the_tool_looks_have_their_fills() -> None:
    text = page()
    for outcome, fill in (
        ("ok", "--s3"), ("error", "--critical"), ("timeout", "--critical"),
        ("unfinished", "--axis"), ("open", "--accent"), ("waiting", "--axis"),
    ):  # fmt: skip
        pattern = rf'{outcome}:\s*\{{ outcome: "{outcome}", fill: "{fill}"'
        assert re.search(pattern, text), outcome
    assert re.search(r'unfinished:\s*\{ outcome: "unfinished", fill: "--axis", hatch: true', text)


def test_the_new_text_kinds_are_at_least_12px_and_not_muted_beyond_ink_2() -> None:
    text = page()
    assert re.search(r'call:\s*\{ px: 13, ink: "--ink" \}', text)
    assert re.search(r'detail:\s*\{ px: 12, ink: "--ink-2" \}', text)
    assert re.search(r'misc:\s*\{ px: 12, ink: "--ink" \}', text)


def test_every_nested_function_in_the_design_exists() -> None:
    text = page()
    for name in (
        "barKey", "barMatch", "toolGroupOf", "openCallsOf", "toolState", "secondsText",
        "callTitle", "callBar", "callLanes", "modelPieces", "splitOf", "nestOf", "groupNests",
        "groupLines", "withNests", "toggledKeys", "miscText", "miscAsk", "toolsAsOf",
        "groupLayout", "callSvg", "callLines", "miscSvg", "miscListHtml", "stepMatch", "turnMatch",
    ):  # fmt: skip
        assert re.search(rf"(async )?function {name}\(", text), name
    assert "async function loadMisc(" in text
    assert "const BAR_MATCHES = { step: stepMatch, po: turnMatch };" in text


def test_the_markup_attributes_the_tests_read_are_in_the_source() -> None:
    text = page()
    for attribute in (
        "data-tl-keys", "data-open", "data-call", "data-lane", "data-outcome", "data-misc",
        "data-tl-misc", "data-misc-ask", "data-misc-list", "data-misc-call", "data-row-label",
    ):  # fmt: skip
        assert attribute in text, attribute
    assert "api/misc?" in text


def test_the_ui_state_has_the_open_sets_and_asof_has_tools() -> None:
    text = page()
    assert "tlOpen: new Set()" in text and "miscOpen: new Set()" in text
    assert "miscCalls: {}" in text
    assert "toolsAsOf(" in text and "tools: toolsAsOf(" in text


def test_svg_ids_carry_the_story_and_the_hatch_pattern_exists() -> None:
    text = page()
    assert "-unfinished" in text
    assert 'patternTransform="rotate(45)"' in text
    assert "model.story" in text and "story: story.id" in text


def test_the_story_group_has_a_doc_comment() -> None:
    text = page()
    index = text.index("function storyGroup(")
    assert text[:index].rstrip().endswith("*/")


def test_the_legend_adds_the_call_looks_and_model() -> None:
    text = page()
    start = text.index("function legendHtml(")
    body = text[start : start + 1500]
    assert "TOOL_LOOKS" in body and "MODEL_LOOK" in body
