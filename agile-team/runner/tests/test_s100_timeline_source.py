"""s100: static checks of the dashboard page's timeline source (TL1, TL17-TL18, TR1-TR5).

Behaviour checks need node (a process), so they live in the e2e suite.
"""

import re
from importlib import resources

from agile_team import system


def page() -> str:
    """Text of the dashboard page."""
    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_the_timeline_tables_have_their_exact_values() -> None:
    text = page()
    assert "const TL_WIDTH = TL.LABEL_W + TL.PLOT_W;" in text
    assert "LABEL_W: 150, PLOT_W: 810" in text
    assert "MIN_SPAN_S: 60" in text and "CHAR_EM: 0.6" in text
    assert 'const TL_SCOPES = [["story", "Story"], ["sprint", "Sprint"]];' in text


def test_every_timeline_function_in_the_design_exists() -> None:
    text = page()
    for name in (
        "roleRank", "tlNow", "tlUnion", "tlMeasure", "tlClip", "tlComplement", "storyRange",
        "verdictOf", "stepBars", "stageBars", "poTurns", "touches", "poBars", "rulingMarks",
        "bounceArrows", "groupRows", "sleepWaits", "questionWaits", "holdWaits", "otherWaits",
        "gapSegments", "storyGroup", "sprintGroup", "groupTotals", "modelTotals",
        "timelineModel", "tlState", "tlWindow", "zoomed", "pannedBy", "tlTicks", "tlText",
        "tlSpan", "tlButton", "timelineSvg", "totalsHtml", "legendHtml", "timelineHtml",
        "setTlScope", "onTlWheel", "doneStories", "doneHtml", "openTimeline",
        "keepTimelineScroll",
    ):  # fmt: skip
        assert f"function {name}(" in text, name


def test_every_text_size_is_at_least_12_and_ink_is_never_muted() -> None:
    body = page().split("const TL_TEXT = {")[1].split("};")[0]
    sizes = [int(n) for n in re.findall(r"px:\s*(\d+)", body)]
    inks = re.findall(r'ink:\s*"([^"]+)"', body)
    assert len(sizes) == len(inks) == 12
    assert min(sizes) >= 12
    assert set(inks) <= {"--ink", "--ink-2"}


def test_the_story_details_show_the_timeline_and_the_board_links_to_it() -> None:
    text = page()
    assert "timelineHtml(view, story)" in text
    assert "data-timeline=" in text and 'class="tl-link"' in text
    assert "data-show-done" in text and "showDone" in text


def test_timeline_clicks_use_their_own_data_attributes() -> None:
    text = page()
    for attr in ("data-tl-scope", "data-tl-zoom", "data-tl-pan", "data-tl-follow"):
        assert attr in text
    assert 'addEventListener("wheel", onTlWheel, { passive: false })' in text


def test_the_timeline_svg_is_drawn_at_scale_one() -> None:
    text = page()
    assert ".tl [data-tl-plot] { overflow-x: auto; }" in text
    assert ".tl svg { display: block; max-width: none; }" in text


def test_the_flow_chart_stays_natural_size_and_idle_text_is_not_muted() -> None:
    text = page()
    assert "useMaxWidth: false" in text
    body = text.split("function idleClassDef()")[1].split("`;")[0]
    assert 'color:${cssVar("--ink-2")}' in body
    assert "--muted" not in body
    assert re.search(r"#flow\s*\{[^}]*overflow-x:\s*auto", text)
