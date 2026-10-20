"""s163 F5, F6, S1 to S4: the overlap hand-over, the continue refusal, and the stack drop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agile_team import handover, po_tools, switchover
from agile_team.boundary import StackEntry
from agile_team.events import EventKind
from agile_team.gates import OVERLAP_CONTINUE, StoryState, continue_refusal
from agile_team.git_ops import GitError
from agile_team.handover import Trigger
from agile_team.po_tools import Tools

HEAD_A, HEAD_B = "a" * 40, "b" * 40

OVERLAP = {
    "files": ["src/a.py", "src/b.py"],
    "with": [{"story": "s2", "files": ["src/b.py"], "overlap": ["src/b.py"]}],
}


def held_report() -> dict:
    gate = {"verdict": "hold", "reason": "overlap", "story_status": "active", "overlap": OVERLAP}
    return {"status": "done", "role": "architect", "gate": gate}


# ---------- the hand-over (F5) ----------


def test_an_overlap_hold_raises_overlap_and_not_gate_hold() -> None:
    assert handover.triggers(held_report()) == [Trigger.OVERLAP]


def test_the_overlap_line_names_the_files_the_other_story_and_the_way_out() -> None:
    [line] = handover.report_lines(held_report(), "s1")
    assert line.startswith("s1: held at design as overlap. It changes src/a.py, src/b.py.")
    assert "s2 changes src/b.py; both: src/b.py" in line
    assert "once s2 have landed" in line and "release_story" in line


def test_a_hold_without_an_overlap_is_still_a_gate_hold() -> None:
    report = held_report()
    del report["gate"]["overlap"]
    assert handover.triggers(report) == [Trigger.GATE_HOLD]


# ---------- continue_story on an overlap hold (F7) ----------


def overlapped(hold: str = "overlap") -> StoryState:
    story = StoryState("s1", "T", "design", hold=hold)
    story.overlap_with = ["s2", "s3"]
    return story


def test_continue_refuses_an_overlap_hold_naming_the_others() -> None:
    assert continue_refusal(overlapped()) == OVERLAP_CONTINUE.format(id="s1", ids="s2, s3")


def test_continue_refuses_an_overlap_that_shares_the_hold() -> None:
    assert continue_refusal(overlapped("po, overlap")) is not None


def test_continue_does_not_refuse_another_hold() -> None:
    assert continue_refusal(overlapped("po")) is None


def test_the_continue_tool_leaves_an_overlap_hold_in_place(make_runtime, fake) -> None:
    rt = make_runtime()
    rt.state.stories["s1"] = story = overlapped()
    out = asyncio.run(Tools(rt).continue_story({"story": "s1"}))
    assert "released" not in out["content"][0]["text"] and story.hold == "overlap"
    assert "held as overlap with s2, s3" in out["content"][0]["text"]


# ---------- find_merged (S1, S2) ----------


class FakeUpstream:
    """Answers ``missing`` and ``why_in_target`` from tables."""

    def __init__(self, missing: str = "", answers: dict | None = None) -> None:
        self.reason, self.answers = missing, answers or {}

    def missing(self) -> str:
        return self.reason

    def why_in_target(self, head: str) -> str | None:
        answer = self.answers[head]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_find_merged_keeps_the_heads_main_has_with_their_reason() -> None:
    up = FakeUpstream(answers={HEAD_A: "contained", HEAD_B: None})
    assert switchover.find_merged(up, [HEAD_A, HEAD_B]) == {HEAD_A: "contained"}


def test_find_merged_finds_nothing_when_the_target_cannot_be_read() -> None:
    up = FakeUpstream(missing="fetch failed", answers={HEAD_A: "contained"})
    assert switchover.find_merged(up, [HEAD_A]) == {}


def test_find_merged_keeps_an_entry_whose_check_raises_git_error() -> None:
    up = FakeUpstream(answers={HEAD_A: GitError("boom"), HEAD_B: "patch-equivalent"})
    assert switchover.find_merged(up, [HEAD_A, HEAD_B]) == {HEAD_B: "patch-equivalent"}


# ---------- drop_entries (S1, S4) ----------


def stacked(rt) -> list[StackEntry]:
    entries = [
        StackEntry(1, "team/sprint-1", "o" * 40, "o" * 40, head=HEAD_A, pr=7),
        StackEntry(2, "team/sprint-2", "o" * 40, "o" * 40, head=HEAD_B),
        StackEntry(3, "team/sprint-3", "o" * 40, "o" * 40, head=""),
    ]
    rt.state.upstream.stack = list(entries)
    return entries


def test_drop_entries_removes_each_merged_entry_and_logs_why(make_runtime, fake) -> None:
    rt = make_runtime()
    first, second, third = stacked(rt)
    gone = switchover.drop_entries(rt, {HEAD_A: "contained"})
    assert gone == [first] and rt.state.upstream.stack == [second, third]
    [event] = [e for e in rt.events.events() if e.kind == EventKind.STACK_DROPPED]
    assert event.role == "po" and event.story is None
    assert event.data == {
        "sprint": 1,
        "branch": "team/sprint-1",
        "head": HEAD_A,
        "pr": 7,
        "why": "contained",
    }


def test_drop_entries_with_nothing_merged_changes_and_logs_nothing(make_runtime, fake) -> None:
    rt = make_runtime()
    stacked(rt)
    assert switchover.drop_entries(rt, {}) == []
    assert [e for e in rt.events.events() if e.kind == EventKind.STACK_DROPPED] == []


# ---------- start_sprint drops before the switch check (S1) ----------


def direct(monkeypatch) -> None:
    async def in_thread(call, *args):
        return call(*args)

    monkeypatch.setattr(po_tools.system, "in_thread", in_thread)


def test_start_sprint_drops_a_merged_entry_so_the_switch_sees_no_stack_s1(
    make_runtime, fake, monkeypatch
) -> None:
    direct(monkeypatch)
    rt = make_runtime()
    rt.upstream = FakeUpstream(answers={HEAD_A: "patch-equivalent", HEAD_B: None})
    stacked(rt)
    asyncio.run(Tools(rt)._drop_merged_entries())
    assert [e.head for e in rt.state.upstream.stack] == [HEAD_B, ""]


def test_a_failed_fetch_drops_nothing_s2(make_runtime, fake, monkeypatch) -> None:
    direct(monkeypatch)
    rt = make_runtime()
    rt.upstream = FakeUpstream(missing="no remote", answers={HEAD_A: "contained"})
    stacked(rt)
    asyncio.run(Tools(rt)._drop_merged_entries())
    assert len(rt.state.upstream.stack) == 3


# ---------- the switch's ahead count (S3) ----------


def test_count_ahead_is_the_unpicked_count_of_head(make_runtime, fake) -> None:
    rt = make_runtime()
    rt.upstream = SimpleNamespace(count_unpicked=lambda ref: 2 if ref == "HEAD" else 0)
    assert switchover.count_ahead(rt) == 2


def test_count_ahead_is_zero_when_git_cannot_say(make_runtime, fake) -> None:
    def fail(ref: str) -> int:
        raise GitError("no target")

    rt = make_runtime()
    rt.upstream = SimpleNamespace(count_unpicked=fail)
    assert switchover.count_ahead(rt) == 0
