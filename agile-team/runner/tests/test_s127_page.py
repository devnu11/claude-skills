"""s127 (AC2-AC4): static checks of the page's CSS and tables for the one-line tool boxes."""

from __future__ import annotations

import re

from .test_s118_page import PAGE, flow_text


def rule(selector: str) -> str:
    """The declarations of the first CSS rule whose selector list holds ``selector``."""
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", PAGE):
        if selector in [s.strip() for s in sel.split(",")]:
            return body
    raise AssertionError(selector)


def test_the_tool_description_text_kind_and_line_are_gone() -> None:
    assert "toolDesc" not in flow_text()
    assert "toolDesc" not in PAGE
    assert "fc-tooldesc" not in PAGE


def test_the_cell_width_comes_from_the_group_minimum() -> None:
    assert re.search(r"--cell-w:\s*calc\(var\(--group-min\) - 20px\)", PAGE)
    body = rule(".fc-cell")
    assert re.search(r"width:\s*var\(--cell-w\)", body)
    assert "min-width" not in body


def test_the_top_row_is_a_three_column_grid() -> None:
    assert re.search(r"grid-template-columns:\s*1fr auto 1fr", rule(".fc-top"))


def test_leadership_is_as_wide_as_its_content_and_centred() -> None:
    body = rule(".fc-lead")
    assert "width: max-content" in body
    assert "justify-self: center" in body
    assert "flex:" not in body


def test_the_people_pills_sit_in_their_own_group() -> None:
    assert "fc-people" in PAGE
    assert "justify-self: end" in rule(".fc-people")


def test_role_name_and_meta_lines_are_centred() -> None:
    assert "text-align: center" in rule(".fc-box > .fc-t-name")
    assert "text-align: center" in rule(".fc-box > .fc-t-meta")


def test_the_idle_tool_line_is_centred_and_does_not_wrap() -> None:
    body = rule(".fc-t-tool")
    assert "justify-content: center" in body
    assert "white-space: nowrap" in body


def test_the_label_is_cut_with_an_ellipsis_and_the_stats_stay() -> None:
    assert "text-overflow: ellipsis" in rule(".fc-toollabel")
    assert "flex: none" in rule(".f-toolstats")


def test_the_sparkline_captions_are_a_table() -> None:
    assert "NO_SPARK" in PAGE
    assert "too short for a sparkline" in PAGE
    assert "no rate yet" in PAGE


def test_the_tool_label_does_not_wrap() -> None:
    assert re.search(r"white-space:\s*nowrap", rule(".fc-toollabel"))


def test_bad_stage_labels_normalize_to_an_empty_object() -> None:
    line = next(ln for ln in PAGE.splitlines() if "out.stage_labels =" in ln)
    assert "typeof out.stage_labels === \"object\"" in line
    assert "!Array.isArray(out.stage_labels)" in line
    assert line.rstrip().endswith(": {};")


def test_a_label_falls_back_to_the_stage_name() -> None:
    assert re.search(r"typeof view\.stage_labels\?\.\[stage\] === \"string\"", PAGE)
    assert re.search(r"view\.stage_labels\[stage\] : stage\)", PAGE)
