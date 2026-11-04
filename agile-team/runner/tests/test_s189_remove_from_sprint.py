"""s189: ``remove_from_sprint`` takes a not-started story out of the running sprint."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from agile_team import po_tools, revert_log, sprint_end, sprint_leave, story_admin, system
from agile_team.boundary import Boundary, Edge
from agile_team.cli import status_report
from agile_team.events import Event
from agile_team.gates import StoryState, StoryStatus
from agile_team.holds import HoldKind, PoHold
from agile_team.po_tools import SCHEMAS, Tools
from agile_team.sprint_add import boundary_text
from agile_team.state import RunState
from agile_team.story_branches import Landed

from .conftest import write_story
from .fake_system import Done, FakeSystem
from .pipeline_helpers import add_story
from .test_po_tools import call, snapshot

CRASH = "error: crashed: GitError: git branch team/story-s1 failed"
REASON = "wait for s2"


@pytest.fixture(autouse=True)
def tracked(configured, fake: FakeSystem) -> None:
    """A modelled working tree and no remote."""
    fake.track()
    fake.reply(("git", "remote", "get-url"), Done(2))


def setup(make_runtime, *, steps: tuple[str, ...] = ("s1", "s2")):
    """Sprint 1 with ``steps`` stories at design, none started; s1 crashed before a commit."""
    rt = make_runtime()
    for sid in steps:
        write_story(rt.config, sid, "cli")
        add_story(rt, sid, "design")
    rt.state.stories["s1"].hold = CRASH
    rt.state.order = list(steps)
    rt.state.pulled = ["s1"]
    rt.state.goal = "the goal"
    rt.save()
    rt.settle_po()
    rt.record_checkout()
    return rt, Tools(rt)


def leave(t: Tools, story: str = "s1", reason: str = REASON) -> dict:
    return call(t.remove_from_sprint({"story": story, "reason": reason}))


def events_of(rt, kind: str) -> list[Event]:
    return [e for e in rt.events.events() if e.kind == kind]


def noted(t: Tools, reason: str = REASON) -> dict:
    """The call as the PO's turn makes it: through ``noted``, which applies STUCK_RESETS."""
    return call(t.noted("remove_from_sprint")({"story": "s1", "reason": reason}))


def file_text(rt, story: str = "s1") -> str:
    return system.read_text(rt.config.stories_dir / f"{story}.md")


def refused(rt, t: Tools, expected: str, **kw) -> None:
    """The call is refused with ``expected`` and nothing changes."""
    rt.save()
    before, head, notes = snapshot(rt), rt.git.head(), len(rt.relay.messages())
    text = file_text(rt)
    assert leave(t, **kw) == {"status": "refused", "reason": expected}
    assert snapshot(rt) == before and rt.git.head() == head and file_text(rt) == text
    assert len(rt.relay.messages()) == notes


# ----- AC1: the move -----------------------------------------------------------------


def test_the_story_leaves_and_keeps_step_and_order(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].po_hold = PoHold(HoldKind.HOLD, "hold it")
    out = leave(t)
    s = rt.state.stories["s1"]
    assert out["status"] == "removed" and out["story"] == "s1" and out["step"] == "design"
    assert out["sprint"] == 1
    assert s.sprint is None and s.step == "design" and s.status is StoryStatus.ACTIVE
    assert rt.state.sprint == 1 and rt.state.goal == "the goal"
    assert rt.state.order == ["s1", "s2"] and rt.state.pulled == ["s1"]
    assert rt.state.stories["s2"].sprint == 1


def test_status_and_snapshot_show_it_in_the_product_backlog(make_runtime) -> None:
    rt, t = setup(make_runtime)
    leave(t)
    assert status_report(rt.config)["stories"]["s1"]["sprint"] is None
    assert status_report(rt.config)["stories"]["s2"]["sprint"] == 1


def test_nothing_is_queued_for_the_move(make_runtime) -> None:
    rt, t = setup(make_runtime)
    leave(t)
    assert rt.state.boundary is None and events_of(rt, "priority") == []


def test_holds_are_cleared_a_blocked_status_is_kept(make_runtime) -> None:
    rt, t = setup(make_runtime)
    s = rt.state.stories["s1"]
    s.po_hold, s.overlap_with, s.status = PoHold(HoldKind.HOLD, "h"), ["s2"], StoryStatus.BLOCKED
    leave(t)
    assert s.hold is None and s.po_hold is None and s.overlap_with == []
    assert s.status is StoryStatus.BLOCKED


def test_the_story_file_records_the_move(make_runtime, fake: FakeSystem) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].po_hold = PoHold(HoldKind.HOLD, "hold it")
    commits = len(fake.tree.commits)
    out = leave(t)
    text = file_text(rt)
    assert text.count("\n## Left the sprint\n") == 1 and text.endswith("\n")
    line = text.rstrip().splitlines()[-1]
    pattern = rf"- \d{{4}}-\d{{2}}-\d{{2}}, sprint 1: {REASON} Cleared hold: runner hold: "
    assert re.fullmatch(pattern + re.escape(f"{CRASH}; PO hold: hold it."), line)
    assert len(fake.tree.commits) == commits + 1
    assert fake.tree.commits[-1].subject() == sprint_leave.RECORD_SUBJECT.format(story="s1")
    assert out["record"] == rt.git.head() and rt.state.checkout.head == rt.git.head()


def test_a_second_removal_adds_a_line_under_the_same_heading(make_runtime) -> None:
    rt, t = setup(make_runtime)
    leave(t)
    s = rt.state.stories["s1"]
    s.sprint, s.hold = 1, None
    rt.save()
    rt.record_checkout()
    leave(t, reason="again")
    text = file_text(rt)
    assert text.count("## Left the sprint") == 1
    assert text.rstrip().splitlines()[-1].endswith("Cleared hold: none.")
    assert "again" in text.rstrip().splitlines()[-1]


def test_no_story_file_means_no_record_and_no_commit(make_runtime, fake: FakeSystem) -> None:
    rt, t = setup(make_runtime)
    add_story(rt, "s3", "design")  # no story file written
    rt.save()
    commits = len(fake.tree.commits)
    out = leave(t, story="s3")
    assert out["status"] == "removed" and out["record"] == ""
    assert len(fake.tree.commits) == commits


def test_one_story_admin_event(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].po_hold = PoHold(HoldKind.HOLD, "hold it")
    out = leave(t)
    (e,) = [e for e in events_of(rt, "story-admin") if e.data.get("tool") == "remove_from_sprint"]
    assert (e.role, e.story) == ("product-owner", "s1")
    assert e.data["reason"] == REASON and e.data["question"] is None and e.data["sprint"] == 1
    assert e.data["cleared"] == {"hold": CRASH, "po_hold": "hold it"}
    assert e.data["record"] == out["record"] and out["cleared"] == e.data["cleared"]
    assert e.data["before"]["sprint"] == 1 and e.data["after"]["sprint"] is None
    assert e.data["before"]["hold"] == CRASH and e.data["after"]["hold"] is None


def test_one_update_note(make_runtime) -> None:
    rt, t = setup(make_runtime)
    leave(t)
    (msg,) = [m for m in rt.relay.messages() if m.kind == "update"]
    assert msg.stories == ["s1"]
    want = sprint_leave.NOTICE.format(
        story="s1",
        title="Title s1",
        sprint=1,
        reason=REASON,
        cleared=f"runner hold: {CRASH}",
    )
    assert msg.text == want


def test_cleared_text_names_both_holds_or_none() -> None:
    assert sprint_leave.Cleared(None, None).text == "none"
    assert sprint_leave.Cleared("h", None).text == "runner hold: h"
    assert sprint_leave.Cleared(None, "p").text == "PO hold: p"
    assert sprint_leave.Cleared("h", "p").text == "runner hold: h; PO hold: p"


def test_read_cleared_takes_only_a_plain_po_hold() -> None:
    plain = StoryState("s1", "t", "design", hold="h", po_hold=PoHold(HoldKind.HOLD, "p"))
    assert sprint_leave.read_cleared(plain) == sprint_leave.Cleared("h", "p")
    asked = StoryState("s1", "t", "design", po_hold=PoHold(HoldKind.CANCEL, "p", "m1"))
    assert sprint_leave.read_cleared(asked) == sprint_leave.Cleared(None, None)


def test_the_worktree_goes_and_the_branch_stays(make_runtime, monkeypatch) -> None:
    removed: list[str] = []
    monkeypatch.setattr(sprint_leave.Workspaces, "remove", lambda self, sid: removed.append(sid))
    rt, t = setup(make_runtime)
    s = rt.state.stories["s1"]
    s.branch, s.base_sha, s.worktree_head, s.replays = "team/story-s1", "a" * 40, "b" * 40, 2
    leave(t)
    assert removed == ["s1"] and s.worktree_head == ""
    assert s.branch == "team/story-s1" and s.base_sha == "a" * 40
    (e,) = events_of(rt, "story-branch")
    assert e.role == "product-owner" and e.story == "s1"
    assert e.data == {
        "action": "removed",
        "branch": "team/story-s1",
        "base_sha": "a" * 40,
        "replays": 2,
    }


def test_no_worktree_means_no_branch_event(make_runtime) -> None:
    rt, t = setup(make_runtime)
    leave(t)
    assert events_of(rt, "story-branch") == []


def test_not_refused_resets_stuck_asks(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stuck_asks = 2
    noted(t)
    assert rt.state.stuck_asks == 0


def test_a_refused_call_keeps_stuck_asks(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stuck_asks = 2
    noted(t, reason="")
    assert rt.state.stuck_asks == 2


# ----- AC2: the sprint can end ---------------------------------------------------------


def test_the_sprint_can_end_without_it(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s2"].status = StoryStatus.DONE
    rt.save()
    assert sprint_end.end_refusal(rt.state) is not None
    assert notify_end(t)["status"] == "refused"
    leave(t)
    assert sprint_end.end_refusal(rt.state) is None
    assert rt.state.sprint_complete() is True
    assert notify_end(t).get("status") != "refused"


def notify_end(t: Tools) -> dict:
    return call(t.notify_user({"kind": "sprint-end", "text": "done"}))


def test_until_blocker_no_longer_names_it(make_runtime) -> None:
    rt, t = setup(make_runtime, steps=("s1", "s2"))
    rt.state.cadence = sprint_end.UNTIL_BLOCKER
    rt.state.stories["s1"].hold, rt.state.stories["s2"].hold = None, "held"
    assert "s1" in sprint_end.keep_going_refusal(rt.state, set())
    leave(t)
    assert sprint_end.keep_going_refusal(rt.state, set()) is None


def test_texts_name_the_tool() -> None:
    assert "remove_from_sprint" in sprint_end.END_REFUSED
    assert "remove_from_sprint" in sprint_end.SPRINT_STUCK_ADVICE
    assert "revert_story" in sprint_end.END_REFUSED
    sprint_end.END_REFUSED.format(sprint=1, stories="s1 at design")
    sprint_end.SPRINT_STUCK_ADVICE.format(count=1, cap=3)


# ----- AC3: work is refused and pointed at revert_story ------------------------------


def work_refused(make_runtime, mutate, template: str) -> None:
    rt, t = setup(make_runtime)
    mutate(rt)
    text = template.format(story="s1")
    assert "revert_story" in text
    refused(rt, t, text)


def test_commit_is_work(make_runtime) -> None:
    def mutate(rt) -> None:
        rt.state.stories["s1"].commit = "1" * 40

    work_refused(make_runtime, mutate, sprint_leave.HAS_COMMITS)


def test_code_commits_are_work(make_runtime) -> None:
    def mutate(rt) -> None:
        rt.state.stories["s1"].code_commits = ["1" * 40]

    work_refused(make_runtime, mutate, sprint_leave.HAS_COMMITS)


def test_a_landing_is_work(make_runtime) -> None:
    def mutate(rt) -> None:
        rt.state.stories["s1"].landed = Landed("m" * 40)

    work_refused(make_runtime, mutate, sprint_leave.LANDED)


@pytest.mark.parametrize("how", ["step", "state", "queue"])
def test_an_open_landing_is_work(make_runtime, how) -> None:
    def mutate(rt) -> None:
        if how == "step":
            rt.state.stories["s1"].step = "land"
        elif how == "state":
            rt.state.landing = "s1"
        else:
            rt.revert_queue.append(SimpleNamespace(story_id="s1"))

    work_refused(make_runtime, mutate, sprint_leave.OPEN_LANDING)


def test_a_branch_with_no_commits_is_not_work(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].branch = "team/story-s1"
    assert leave(t)["status"] == "removed"


# ----- AC3: the other refusals ---------------------------------------------------------


def test_refused_while_a_boundary_is_pending(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.boundary = Boundary(Edge.END, 1)
    refused(rt, t, boundary_text(rt.state.boundary))


def test_refused_for_an_unknown_story(make_runtime) -> None:
    rt, t = setup(make_runtime)
    refused(rt, t, story_admin.UNKNOWN.format(story="s9"), story="s9")


def test_refused_for_a_blank_reason(make_runtime) -> None:
    rt, t = setup(make_runtime)
    refused(rt, t, story_admin.NO_REASON, reason="  ")


def test_unknown_comes_before_the_reason(make_runtime) -> None:
    rt, t = setup(make_runtime)
    refused(rt, t, story_admin.UNKNOWN.format(story="s9"), story="s9", reason="")


@pytest.mark.parametrize("status", [StoryStatus.DONE, StoryStatus.CANCELLED])
def test_refused_for_a_finished_story(make_runtime, status) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].status = status
    text = story_admin.FINISHED_TEXT.format(story="s1", status=status, verb=sprint_leave.VERB)
    refused(rt, t, text)


def test_refused_for_a_story_not_in_the_sprint(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].sprint = None
    refused(rt, t, sprint_leave.NOT_IN_SPRINT.format(story="s1", sprint=1))


def test_refused_with_no_open_sprint(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.sprint = 0
    refused(rt, t, sprint_leave.NOT_IN_SPRINT.format(story="s1", sprint=0))


@pytest.mark.parametrize("kind", [HoldKind.CANCEL, HoldKind.REVERT])
def test_refused_while_a_question_waits(make_runtime, kind) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].po_hold = PoHold(kind, "r", "m1")
    refused(rt, t, story_admin.asked_text(rt.state.stories["s1"]))


def test_refused_while_a_step_runs(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.flags.running.add("s1")
    refused(rt, t, sprint_leave.STEP_RUNNING.format(story="s1", step="design"))


def test_refused_when_a_sprint_story_depends_on_it(make_runtime) -> None:
    rt, t = setup(make_runtime, steps=("s1", "s2", "s3"))
    rt.state.stories["s2"].depends_on = ["s1"]
    rt.state.stories["s3"].depends_on = ["s1"]
    refused(rt, t, sprint_leave.DEPENDED_ON_IN_SPRINT.format(story="s1", ids="s2, s3"))


def test_a_finished_dependent_does_not_count(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s2"].depends_on = ["s1"]
    rt.state.stories["s2"].status = StoryStatus.DONE
    assert leave(t)["status"] == "removed"


def test_list_sprint_dependents_in_state_order() -> None:
    st = RunState()
    st.sprint = 1
    st.stories["s1"] = StoryState("s1", "t", "design", sprint=1)
    st.stories["s3"] = StoryState("s3", "t", "design", sprint=1, depends_on=["s1"])
    st.stories["s2"] = StoryState("s2", "t", "design", sprint=1, depends_on=["s1"])
    st.stories["s4"] = StoryState("s4", "t", "design", sprint=None, depends_on=["s1"])
    assert sprint_leave.list_sprint_dependents(st, "s1") == ["s3", "s2"]


def test_refused_when_the_checkout_moved(make_runtime) -> None:
    from agile_team.state import CheckoutRecord

    rt, t = setup(make_runtime)
    rt.state.checkout = CheckoutRecord("main", "d" * 40)
    out = leave(t)
    assert out["status"] == "halted" and out["role"] == "product-owner"
    assert rt.state.stories["s1"].sprint == 1


def test_an_answered_cancel_question_is_settled_first(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.relay.post(story_admin.Note("question", "cancel s1?", ["s1"]))
    rt.state.stories["s1"].po_hold = PoHold(HoldKind.CANCEL, "r", "m1")
    rt.relay.answer("m1", "cancel")
    out = leave(t)
    assert out["status"] == "refused"
    assert out["reason"].startswith("story s1 is cancelled")
    assert rt.state.stories["s1"].status is StoryStatus.CANCELLED


# ----- revert_log.append_under ---------------------------------------------------------


def test_append_under_adds_the_heading_once() -> None:
    section = revert_log.FileSection("## Left", "- one")
    first = revert_log.append_under("body", section)
    assert first == "body\n\n## Left\n\n- one\n"
    second = revert_log.append_under(first, revert_log.FileSection("## Left", "- two"))
    assert second == "body\n\n## Left\n\n- one\n- two\n"


def test_append_under_keeps_an_existing_trailing_newline() -> None:
    out = revert_log.append_under("body\n", revert_log.FileSection("## H", "- x"))
    assert out == "body\n\n## H\n\n- x\n"


# ----- schema --------------------------------------------------------------------------


def test_schema_and_stuck_reset() -> None:
    assert SCHEMAS["remove_from_sprint"][1] == {"story": str, "reason": str}
    assert "remove_from_sprint" in po_tools.STUCK_RESETS
    assert "mcp__team__remove_from_sprint" in po_tools.tool_names()
