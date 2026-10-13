"""Tool calls as spans: labels, details, masking, status, the time split (s98, TC1-TC12)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from agile_team import tool_calls as tc
from agile_team.dashboard.step_times import Mark, Platform
from claude_agent_sdk import ToolResultBlock, ToolUseBlock

WHERE = tc.Where("developer", "s1", "implement", 100.0)
PO_WHERE = tc.Where("product-owner", None, "po-session", 100.0)
SPAN_KEYS = [
    "role", "story", "step", "opened_at", "tool", "tool_use_id", "label",
    "detail", "at", "mono", "slept", "seconds", "ended_at", "status",
]  # fmt: skip


def mark(t: float) -> Mark:
    return Mark(t, t, 0.0)


def use(uid: str, name: str = "Read", **tool_input: Any) -> ToolUseBlock:
    return ToolUseBlock(id=uid, name=name, input=tool_input)


def result(uid: str, content: Any = "ok", is_error: bool | None = False) -> ToolResultBlock:
    return ToolResultBlock(tool_use_id=uid, content=content, is_error=is_error)


def calls(where: tc.Where = WHERE, platform: Platform = Platform.POSIX) -> tc.Calls:
    return tc.Calls(where, platform)


def test_a_call_to_its_result_is_one_ok_span_with_the_keys_in_order() -> None:
    c = calls()
    c.start([use("u1", "Bash", command="ls", description="list")], mark(10.0))
    assert c.spans == []
    c.finish([result("u1")], mark(12.5))
    (span,) = c.spans
    assert span.status == tc.Status.OK and span.seconds == 2.5
    data = json.loads(span.line())
    assert list(data) == SPAN_KEYS
    assert data["tool"] == "Bash" and data["tool_use_id"] == "u1"
    assert data["label"] == "Dev: list" and data["detail"] == "ls"
    assert (data["at"], data["mono"], data["slept"], data["ended_at"]) == (10.0, 10.0, 0.0, 12.5)
    assert (data["role"], data["story"], data["step"], data["opened_at"]) == (
        "developer", "s1", "implement", 100.0,
    )  # fmt: skip


def test_a_repeated_use_id_does_not_reopen_and_an_unknown_result_is_ignored() -> None:
    c = calls()
    c.start([use("u1")], mark(1.0))
    c.start([use("u1")], mark(5.0))
    c.finish([result("zz")], mark(6.0))
    assert c.spans == []
    c.finish([result("u1")], mark(7.0))
    assert c.spans[0].seconds == 6.0


def test_a_finished_call_is_not_closed_twice() -> None:
    c = calls()
    c.start([use("u1")], mark(1.0))
    c.finish([result("u1")], mark(2.0))
    c.finish([result("u1")], mark(3.0))
    assert len(c.spans) == 1


@pytest.mark.parametrize(
    ("content", "status"),
    [
        ("Command timed out after 2m", tc.Status.TIMEOUT),
        ("boom", tc.Status.ERROR),
        ([{"type": "text", "text": "x"}, {"type": "text", "text": "Timed Out"}], tc.Status.TIMEOUT),
        ([{"type": "text", "text": "bad"}, {"type": "image"}], tc.Status.ERROR),
        (None, tc.Status.ERROR),
        ("x" * 300 + " timed out", tc.Status.ERROR),
    ],
)
def test_an_error_result_is_a_timeout_only_when_the_text_says_so(
    content: Any, status: tc.Status
) -> None:
    assert tc.status_of(result("u", content, is_error=True)) == status


@pytest.mark.parametrize("flag", [False, None])
def test_a_result_without_the_error_flag_is_ok(flag: bool | None) -> None:
    assert tc.status_of(result("u", "timed out", is_error=flag)) == tc.Status.OK


def test_result_text_joins_text_items_and_none_is_empty() -> None:
    assert tc.result_text(result("u", None)) == ""
    assert tc.result_text(result("u", "plain")) == "plain"
    items = [{"type": "text", "text": "a"}, {"type": "other"}, {"type": "text", "text": "b"}]
    assert tc.result_text(result("u", items)) == "a\nb"


def test_parallel_calls_are_separate_spans_and_tool_s_is_the_union() -> None:
    c = calls()
    c.start([use("a"), use("b")], mark(10.0))
    c.finish([result("a")], mark(14.0))
    c.finish([result("b")], mark(16.0))
    assert [s.seconds for s in c.spans] == [4.0, 6.0]
    split = c.split(mark(10.0), mark(20.0))
    assert split.tool_s == 6.0 and split.model_s == 4.0 and split.waiting_s == 0.0


def test_an_unfinished_call_closes_at_the_mark_and_counts_in_tool_s() -> None:
    c = calls()
    c.start([use("a")], mark(10.0))
    c.abandon(mark(15.0))
    (span,) = c.spans
    assert span.status == tc.Status.UNFINISHED and span.seconds == 5.0
    assert span.end == mark(15.0)
    c.abandon(mark(99.0))
    assert len(c.spans) == 1
    assert c.split(mark(10.0), mark(15.0)).tool_s == 5.0


def test_take_fresh_returns_each_span_once() -> None:
    c = calls()
    c.start([use("a")], mark(1.0))
    c.finish([result("a")], mark(2.0))
    assert len(c.take_fresh()) == 1
    assert c.take_fresh() == []
    assert len(c.spans) == 1


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        (use("u", "mcp__team__run_role"), "po.run_role"),
        (use("u", "mcp__team__open_story"), "po.open_story"),
        (use("u", "mcp__runner__run_tests"), "runner-tool.run_tests"),
        (use("u", "Bash", description="run the tests", command="pytest"), "Dev: run the tests"),
        (use("u", "Bash", description="  ", command="pytest"), "Dev: Bash"),
        (use("u", "Bash", description=5), "Dev: Bash"),
        (use("u", "Bash"), "Dev: Bash"),
        (use("u", "Read", file_path="/a"), "Dev: Read"),
        (use("u", "mcp__other__x"), "Dev: mcp__other__x"),
        (use("u", "Read", description="not a reason key"), "Dev: Read"),
    ],
)
def test_labels_name_the_tool_or_say_dev(block: ToolUseBlock, expected: str) -> None:
    assert tc.label(block) == expected


def test_named_returns_none_for_other_tools() -> None:
    assert tc.named("Bash") is None
    assert tc.named("mcp__other__x") is None
    assert tc.named("mcp__team__run_role") == "po.run_role"


def test_a_bash_reason_is_masked_and_cut() -> None:
    block = use("u", "Bash", description="GH_TOKEN=abc " + "y" * 100)
    assert tc.label(block) == "Dev: GH_TOKEN=*** " + "y" * (80 - len("GH_TOKEN=*** "))


@pytest.mark.parametrize(
    ("tool_input", "expected"),
    [
        ({"command": "ls -l"}, "ls -l"),
        ({"file_path": "/a/b.py"}, "/a/b.py"),
        ({"pattern": "foo.*"}, "foo.*"),
        ({"role": "developer"}, "developer"),
        ({"story": "s7"}, "s7"),
        ({"query": "q", "url": "u"}, "u"),
        ({"command": "  ", "file_path": "/x"}, "/x"),
        ({"command": 5, "path": "/p"}, "/p"),
        ({}, ""),
        ({"other": "thing"}, ""),
        ({"command": "  \n "}, ""),
    ],
)
def test_detail_is_the_first_usable_value(tool_input: dict[str, Any], expected: str) -> None:
    assert tc.detail(tool_input) == expected


def test_detail_is_cut_to_80_and_whitespace_is_collapsed() -> None:
    assert tc.detail({"command": "x" * 200}) == "x" * 80
    assert tc.detail({"command": "x" * 80}) == "x" * 80
    assert tc.detail({"command": "a\n\n  b\tc  "}) == "a b c"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("GH_TOKEN=abc gh pr list", "GH_TOKEN=*** gh pr list"),
        ("api_key='x y' run", "api_key=*** run"),
        ('export MY_SECRET="s" && go', "export MY_SECRET=*** && go"),
        ("AWS_SECRET_ACCESS_KEY=zzz/yyy cmd", "AWS_SECRET_ACCESS_KEY=*** cmd"),
        ('export API_KEY="a b"', "export API_KEY=***"),
        ("A_TOKEN=1;B_KEY=2", "A_TOKEN=***;B_KEY=***"),
        ("PATH=/bin ls", "PATH=/bin ls"),
        ("--token abc", "--token abc"),
        ("", ""),
    ],
)
def test_masking_hides_the_value_of_secret_variables(text: str, expected: str) -> None:
    assert tc.masked(text) == expected


def test_a_secret_straddling_character_80_never_shows_a_prefix() -> None:
    text = "x" * 60 + " GH_TOKEN=abcdefghijklmnopqrstuvwxyz"
    shown = tc.shown(text)
    assert "abc" not in shown and len(shown) <= tc.LIMIT
    assert shown.endswith("GH_TOKEN=***")
    assert "SECRET_ABC" not in tc.shown("MY_SECRET=" + "q" * 200)


def test_the_detail_in_a_span_line_is_masked() -> None:
    c = calls()
    c.start([use("u", "Bash", command="GH_TOKEN=abc gh pr list")], mark(1.0))
    c.finish([result("u")], mark(2.0))
    assert json.loads(c.spans[0].line())["detail"] == "GH_TOKEN=*** gh pr list"


def test_a_po_waiting_call_is_waiting_not_tool_time() -> None:
    c = calls(PO_WHERE)
    c.start([use("w", "mcp__team__run_role", role="developer")], mark(10.0))
    c.finish([result("w")], mark(40.0))
    c.start([use("t", "Read", file_path="/a")], mark(45.0))
    c.finish([result("t")], mark(50.0))
    split = c.split(mark(0.0), mark(60.0))
    assert (split.waiting_s, split.tool_s, split.model_s) == (30.0, 5.0, 25.0)
    assert split.as_dict() == {"tool_s": 5.0, "model_s": 25.0, "waiting_s": 30.0}


def test_a_role_reading_has_zero_waiting() -> None:
    c = calls()
    c.start([use("t")], mark(1.0))
    c.finish([result("t")], mark(3.0))
    assert c.split(mark(0.0), mark(5.0)).waiting_s == 0.0
    assert calls().split(mark(0.0), mark(5.0)).as_dict() == {
        "tool_s": 0.0, "model_s": 5.0, "waiting_s": 0.0,
    }  # fmt: skip


def test_waiting_overlapping_a_tool_call_is_not_counted_twice() -> None:
    c = calls(PO_WHERE)
    c.start([use("w", "mcp__team__run_role"), use("t")], mark(0.0))
    c.finish([result("t")], mark(10.0))
    c.finish([result("w")], mark(10.0))
    split = c.split(mark(0.0), mark(10.0))
    assert split.waiting_s == 10.0 and split.tool_s == 0.0 and split.model_s == 0.0


def test_a_clamp_keeps_model_time_from_going_negative() -> None:
    c = calls()
    c.start([use("t")], mark(0.0))
    c.finish([result("t")], mark(10.0))
    assert c.split(mark(0.0), mark(4.0)).model_s == 0.0


@pytest.mark.parametrize(
    ("intervals", "total"),
    [
        ([], 0.0),
        ([(0.0, 10.0), (2.0, 5.0)], 10.0),
        ([(0.0, 5.0), (5.0, 8.0)], 8.0),
        ([(0.0, 2.0), (5.0, 8.0)], 5.0),
        ([(5.0, 8.0), (0.0, 6.0)], 8.0),
    ],
)
def test_union_measures_the_covered_time(
    intervals: list[tuple[float, float]], total: float
) -> None:
    assert tc.union(intervals) == total


def test_windows_positions_subtract_the_sleep_counter() -> None:
    assert tc.POSITIONS[Platform.WINDOWS](Mark(100.0, 5.0, 30.0)) == 70.0
    assert tc.POSITIONS[Platform.WINDOWS](Mark(100.0, 5.0, None)) == 100.0


def test_posix_positions_use_mono_else_wall() -> None:
    assert tc.POSITIONS[Platform.POSIX](Mark(100.0, 5.0, 30.0)) == 5.0
    assert tc.POSITIONS[Platform.POSIX](Mark(100.0)) == 100.0


def test_a_windows_span_is_awake_across_a_counted_sleep() -> None:
    c = calls(platform=Platform.WINDOWS)
    c.start([use("a")], Mark(10.0, None, 0.0))
    c.finish([result("a")], Mark(612.0, None, 600.0))
    assert c.spans[0].seconds == 2.0


def test_a_clock_going_backwards_is_zero_seconds_and_seconds_round_to_3() -> None:
    c = calls()
    c.start([use("a"), use("b")], mark(10.0))
    c.finish([result("a")], mark(9.0))
    c.finish([result("b")], mark(10.12345))
    assert [s.seconds for s in c.spans] == [0.0, 0.123]


def test_step_of_role_defaults_the_po_step() -> None:
    assert tc.STEP_OF_ROLE["product-owner"] == "po-session"
    assert tc.TOOLS == "tools.jsonl"
