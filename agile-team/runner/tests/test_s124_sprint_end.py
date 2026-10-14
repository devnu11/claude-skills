"""s124: a sprint ends only when its stories are finished; revert_story; the ready backlog.

The real git behaviour of ``revert_all`` (one commit from many, conflicts) is the e2e tests'.
Here the git seam is a ``Git`` whose new methods are scripted; commits of the record
go through the fake working tree.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest
from agile_team import boundary as bd
from agile_team import gates, po_tools, revert_log, reverts, sprint_end, story_admin, story_spec
from agile_team.boundary import Edge
from agile_team.boundary_runner import BoundaryRunner
from agile_team.dispatch import StepRequest
from agile_team.events import Event, EventKind
from agile_team.gates import StoryState, StoryStatus
from agile_team.git_ops import Git, GitError
from agile_team.handover import Trigger
from agile_team.holds import HoldKind, PoHold
from agile_team.po_tools import SCHEMAS, Tools
from agile_team.relay import Note
from agile_team.reverts import Reverter
from agile_team.router import Router
from agile_team.state import CheckoutRecord, RunState
from agile_team.waits import WAITS, WaitReason

from .conftest import write_story
from .fake_system import Done, FakeSystem
from .pipeline_helpers import add_story
from .test_po_tools import call, snapshot

REVERT_SHA = "b" * 40
FIRST, FIXUP, OTHER = "1" * 40, "2" * 40, "3" * 40
SUBJECT = "feat(s1): Title s1"


@dataclass
class ScriptGit(Git):
    """The real ``Git`` with the revert methods scripted (the fake tree has no multi-revert)."""

    ancestor: bool = True
    log: list[tuple[str, str]] = field(
        default_factory=lambda: [
            (FIRST, SUBJECT),
            (OTHER, "feat(s2): other"),
            (FIXUP, f"fixup! {SUBJECT}"),
        ]
    )
    conflict: str | None = None
    reverted: list[tuple[list[str], str]] = field(default_factory=list)

    def is_ancestor(self, sha: str) -> bool:
        return self.ancestor

    def log_from(self, first: str) -> list[tuple[str, str]]:
        return self.log

    def subject(self, sha: str) -> str:
        return SUBJECT

    def revert_all(self, shas, message: str) -> str:
        if self.conflict:
            raise GitError(self.conflict)
        self.reverted.append((list(shas), message))
        return REVERT_SHA


@pytest.fixture(autouse=True)
def tracked(configured, fake: FakeSystem) -> None:
    """A modelled working tree and no remote."""
    fake.track()
    fake.reply(("git", "remote", "get-url"), Done(2))


def setup(make_runtime, *, steps: tuple[str, ...] = ("s1",)):
    """Sprint 1 with ``steps`` stories at implement; s1 is started (has a first commit)."""
    rt = make_runtime()
    rt.git = ScriptGit(rt.git.repo)
    for sid in steps:
        write_story(rt.config, sid, "cli")
        add_story(rt, sid, "implement")
    rt.state.stories["s1"].commit = FIRST
    rt.state.stories["s1"].code_commits = [FIRST, FIXUP]
    rt.state.stories["s1"].rounds = 2
    rt.state.pulled = ["s1"]
    rt.state.order = list(steps)
    rt.save()
    rt.record_checkout()
    return rt, Tools(rt)


def revert(t: Tools, story: str = "s1", reason: str = "went the wrong way") -> dict:
    return call(t.revert_story({"story": story, "reason": reason}))


def kinds(rt) -> list[str]:
    return [e.kind for e in rt.events.events()]


def events_of(rt, kind: str) -> list[Event]:
    return [e for e in rt.events.events() if e.kind == kind]


# ----- E1-E3: the end rule ---------------------------------------------------------


def test_sprint_complete(make_runtime) -> None:
    st = RunState()
    st.sprint = 1
    assert st.sprint_complete() is False  # an empty sprint
    st.stories["s1"] = StoryState("s1", "t", "design", sprint=1, status=StoryStatus.DONE)
    assert st.sprint_complete() is True
    st.stories["s2"] = StoryState("s2", "t", "design", sprint=None)  # reverted/cancelled leave
    assert st.sprint_complete() is True
    st.stories["s3"] = StoryState("s3", "t", "implement", sprint=1)
    assert st.sprint_complete() is False


def test_notify_sprint_end_is_refused_naming_unfinished_stories(make_runtime) -> None:
    rt, t = setup(make_runtime, steps=("s1", "s2"))
    rt.state.stories["s1"].status = StoryStatus.DONE
    rt.save()
    before = snapshot(rt)
    messages = len(rt.relay.messages())
    out = call(t.notify_user({"kind": "sprint-end", "text": "done"}))
    want = sprint_end.END_REFUSED.format(sprint=1, stories="s2 at implement")
    assert out == {"status": "refused", "reason": want}
    assert "s2 at implement" in want
    assert len(rt.relay.messages()) == messages and snapshot(rt) == before


def test_refusal_lists_every_story_in_sprint_order(make_runtime) -> None:
    rt, _ = setup(make_runtime, steps=("s1", "s2"))
    rt.state.stories["s2"].step = "design"
    assert sprint_end.end_refusal(rt.state) == sprint_end.END_REFUSED.format(
        sprint=1, stories="s1 at implement, s2 at design"
    )


def test_other_kinds_are_unchanged_while_unfinished(make_runtime) -> None:
    _, t = setup(make_runtime)
    assert "id" in call(t.notify_user({"kind": "update", "text": "hi"}))
    assert "id" in call(t.notify_user({"kind": "blocked", "text": "stuck"}))


def test_sprint_end_is_allowed_when_done_or_cancelled(make_runtime) -> None:
    rt, t = setup(make_runtime, steps=("s1", "s2"))
    rt.state.stories["s1"].status = StoryStatus.DONE
    rt.state.stories["s2"].status = StoryStatus.CANCELLED
    rt.state.stories["s2"].sprint = None
    assert sprint_end.end_refusal(rt.state) is None
    out = call(t.notify_user({"kind": "sprint-end", "text": "all done"}))
    assert "id" in out and rt.state.status == "sprint-end"


def test_end_refusal_is_none_with_no_unfinished(make_runtime) -> None:
    assert sprint_end.end_refusal(RunState()) is None


def test_open_end_needs_a_finished_sprint(make_runtime) -> None:
    rt, _ = setup(make_runtime, steps=("s1", "s2"))
    runner = BoundaryRunner(rt)
    rt.state.stories["s1"].status = StoryStatus.DONE
    assert runner.open_end() is False and rt.state.boundary is None
    rt.state.stories["s2"].sprint = None  # reverted
    assert runner.open_end() is True
    assert rt.state.boundary == bd.Boundary(Edge.END, 1)


def test_idle_hands_over_sprint_end_only_when_complete(make_runtime) -> None:
    rt, _ = setup(make_runtime, steps=("s1", "s2"))
    rt.state.stories["s1"].status = StoryStatus.DONE
    rt.state.stories["s2"].hold = "stopped"
    assert Router(rt)._idle().kinds != [Trigger.SPRINT_END]
    rt.state.stories["s2"].sprint = None
    assert Router(rt)._idle().kinds == [Trigger.SPRINT_END]


# ----- R4-R7, R10: a revert ----------------------------------------------------------


def test_revert_makes_one_commit_of_the_story_only(make_runtime, fake: FakeSystem) -> None:
    rt, t = setup(make_runtime, steps=("s1", "s2"))
    out = revert(t)
    (shas, message) = rt.git.reverted[0]
    assert shas == [FIXUP, FIRST]  # newest first; the other story's commit stays
    assert message.splitlines()[0] == "revert(s1): Title s1"
    assert f"Reverts {FIRST[:12]}, {FIXUP[:12]}." in message
    assert "Reason: went the wrong way" in message
    assert fake.tree.commits[-1].subject() == reverts.RECORD_SUBJECT.format(story="s1")
    assert out["status"] == "reverted" and out["story"] == "s1" and out["count"] == 1
    assert out["commits"] == [FIRST, FIXUP] and out["revert"] == REVERT_SHA
    assert out["record"] == rt.git.head() and out["step"] == "design"


def test_story_file_gets_the_entry(make_runtime, fake: FakeSystem) -> None:
    rt, t = setup(make_runtime)
    revert(t)
    text = system_text(rt, "s1")
    assert text.rstrip().splitlines()[-2] == ""
    assert text.count("\n## Reverted\n") == 1 and text.endswith("\n")
    line = text.rstrip().splitlines()[-1]
    date = rt.state.stories["s1"].reverted[0].date
    assert line == (
        f"- {date}, sprint 1: went the wrong way Reverted commits: {FIRST[:12]}, {FIXUP[:12]}. "
        f"Revert commit: {REVERT_SHA[:12]}."
    )
    assert story_spec.read(rt.config, "s1") is not None


def system_text(rt, story: str) -> str:
    from agile_team import system

    return system.read_text(rt.config.stories_dir / f"{story}.md")


def test_state_after_a_revert(make_runtime) -> None:
    rt, t = setup(make_runtime, steps=("s1", "s2"))
    rt.state.stories["s1"].developer = "developer-cli"
    revert(t)
    s = rt.state.stories["s1"]
    assert s.step == "design" and s.sprint is None and s.commit is None
    assert s.code_commits == [] and s.rounds == 0 and s.hold is None and s.po_hold is None
    assert s.developer == "developer-cli" and s.title == "Title s1"
    assert len(s.reverted) == 1 and s.reverted[0].record == rt.git.head()
    assert s.reverted[0].commits == [FIRST, FIXUP] and s.reverted[0].revert == REVERT_SHA
    assert "s1" not in rt.state.pulled and rt.state.order == ["s1", "s2"]
    assert rt.state.checkout == CheckoutRecord("main", rt.git.head())
    assert RunState.from_json(rt.state.to_json()).stories["s1"].reverted == s.reverted


def test_step_is_kept_when_before_tests(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].step = "design"
    revert(t)
    assert rt.state.stories["s1"].step == "design"


def test_back_at_the_step_before_tests(make_runtime) -> None:
    rt, t = setup(make_runtime)
    steps = rt.pipeline.steps
    assert revert(t)["step"] == steps[steps.index("tests") - 1]


def test_one_story_reverted_event(make_runtime) -> None:
    rt, t = setup(make_runtime)
    for role in ("architect", "unit-tester", "architect"):
        rt.events.emit(Event(EventKind.STEP_END, role, "s1", {}))
    revert(t)
    (e,) = events_of(rt, "story-reverted")
    assert (e.role, e.story) == ("product-owner", "s1")
    assert e.data == {
        "sprint": 1,
        "reason": "went the wrong way",
        "commits": [FIRST, FIXUP],
        "revert": REVERT_SHA,
        "record": rt.git.head(),
        "count": 1,
        "from_step": "implement",
        "step": "design",
        "roles": ["architect", "unit-tester"],
        "question": None,
    }


def test_one_update_notice(make_runtime) -> None:
    rt, t = setup(make_runtime)
    revert(t)
    (msg,) = [m for m in rt.relay.messages() if m.kind == "update"]
    assert msg.stories == ["s1"]
    assert msg.text == reverts.NOTICE.format(
        story="s1",
        title="Title s1",
        sprint=1,
        reason="went the wrong way",
        commits=f"{FIRST[:12]}, {FIXUP[:12]}",
        revert=REVERT_SHA[:12],
        step="design",
    )


# ----- R1: refusals --------------------------------------------------------------------


def refused(rt, t: Tools, expected: str, **kw) -> None:
    rt.save()
    before, head, n = snapshot(rt), rt.git.head(), len(rt.relay.messages())
    out = revert(t, **kw)
    assert out == {"status": "refused", "reason": expected}
    assert snapshot(rt) == before and rt.git.head() == head and rt.git.reverted == []
    assert len(rt.relay.messages()) == n


def test_refused_while_a_boundary_is_pending(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.boundary = bd.Boundary(Edge.END, 1)
    text = po_tools.SPRINT_REFUSAL_BOUNDARY.format(
        sprint=1, edge=Edge.END, stage=rt.state.boundary.stage, held=""
    )
    refused(rt, t, text)


def test_refused_for_an_unknown_story(make_runtime) -> None:
    rt, t = setup(make_runtime)
    refused(rt, t, story_admin.UNKNOWN.format(story="s9"), story="s9")


def test_refused_for_a_blank_reason(make_runtime) -> None:
    rt, t = setup(make_runtime)
    refused(rt, t, story_admin.NO_REASON, reason="  ")


@pytest.mark.parametrize("status", [StoryStatus.DONE, StoryStatus.CANCELLED])
def test_refused_for_a_finished_story(make_runtime, status) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].status = status
    refused(rt, t, story_admin.FINISHED_TEXT.format(story="s1", status=status, verb="revert"))


def test_refused_while_a_cancel_question_waits(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].po_hold = PoHold(HoldKind.CANCEL, "r", "m1")
    refused(rt, t, story_admin.asked_text(rt.state.stories["s1"]))
    assert story_admin.asked_text(rt.state.stories["s1"]) == story_admin.CANCEL_PENDING.format(
        story="s1", question="m1"
    )


def test_refused_while_a_revert_question_waits(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].po_hold = PoHold(HoldKind.REVERT, "r", "m1")
    text = story_admin.REVERT_PENDING.format(story="s1", question="m1")
    assert story_admin.asked_text(rt.state.stories["s1"]) == text
    refused(rt, t, text)


def test_refused_with_no_commits(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].commit = None
    refused(rt, t, reverts.NOTHING_TO_REVERT.format(story="s1"))


def test_refused_when_a_started_story_depends_on_it(make_runtime) -> None:
    rt, t = setup(make_runtime, steps=("s1", "s2", "s3"))
    rt.state.stories["s2"].depends_on = ["s1"]
    rt.state.stories["s2"].commit = OTHER
    rt.state.stories["s3"].depends_on = ["s1"]  # not started: does not count
    refused(rt, t, reverts.DEPENDED_ON.format(story="s1", ids="s2"))


def test_refused_when_the_first_commit_is_off_the_branch(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.git.ancestor = False
    refused(rt, t, reverts.NOT_ON_BRANCH.format(story="s1", sha=FIRST[:12]))


def test_a_conflict_changes_nothing(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.git.conflict = "conflicts in a.py"
    rt.settle_po()  # R4 (a) commits the story files first; the conflict leaves it as it is
    rt.record_checkout()
    refused(rt, t, reverts.REVERT_CONFLICT.format(story="s1", why="conflicts in a.py"))
    assert "story-reverted" not in kinds(rt)


def test_refused_when_the_checkout_moved(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.checkout = CheckoutRecord("main", "d" * 40)
    out = revert(t)
    assert out["status"] == "halted" and out["role"] == "product-owner"
    assert rt.git.reverted == [] and "story-reverted" not in kinds(rt)


def test_refusal_order_unknown_before_reason(make_runtime) -> None:
    rt, t = setup(make_runtime)
    refused(rt, t, story_admin.UNKNOWN.format(story="s9"), story="s9", reason="")


# ----- R2-R3: the second revert asks ------------------------------------------------


def reverted_once(make_runtime):
    rt, t = setup(make_runtime)
    revert(t)
    s = rt.state.stories["s1"]
    s.commit, s.code_commits, s.sprint, s.step = FIRST, [FIRST], 1, "implement"
    rt.git.reverted.clear()
    rt.save()
    return rt, t


def ask(make_runtime):
    rt, t = reverted_once(make_runtime)
    return rt, t, revert(t, reason="still wrong")


def test_a_second_revert_asks_the_human(make_runtime, fake: FakeSystem) -> None:
    rt, t = reverted_once(make_runtime)
    commits = len(fake.tree.commits)
    out = revert(t, reason="still wrong")
    assert out["status"] == "revert requested" and out["story"] == "s1"
    assert rt.git.reverted == [] and len(fake.tree.commits) == commits
    q = rt.relay.messages()[-1]
    assert q.kind == "question" and q.stories == ["s1"] and out["question"] == q.id
    assert 'Revert story s1 ("Title s1") again?' in q.text and "still wrong" in q.text
    assert "reverted 1× already" in q.text  # noqa: RUF001
    hold = rt.state.stories["s1"].po_hold
    assert hold == PoHold(HoldKind.REVERT, "still wrong", q.id)
    (e,) = [e for e in events_of(rt, "story-admin") if e.data.get("tool") == "revert_story"]
    assert e.story == "s1"
    assert len(events_of(rt, "story-reverted")) == 1


def test_the_wait_shows_a_revert_request() -> None:
    assert WaitReason.REVERT_REQUESTED == "revert requested"
    assert HoldKind.REVERT == "revert requested"
    assert len(WAITS) > 0


def test_answer_revert_reverts_again_at_the_next_settle(make_runtime) -> None:
    rt, _, out = ask(make_runtime)
    rt.relay.answer(out["question"], " Revert. ")
    assert Reverter(rt).settle() == ["s1"]
    s = rt.state.stories["s1"]
    assert len(s.reverted) == 2 and s.po_hold is None and s.sprint is None
    assert rt.git.reverted and s.reverted[1].reason == "still wrong"
    last = events_of(rt, "story-reverted")[-1]
    assert last.data["count"] == 2 and last.data["question"] == out["question"]
    (adm,) = [e for e in events_of(rt, "story-admin") if e.data.get("tool") == "answer"]
    assert adm.role is None and adm.data["decision"] == "revert"
    assert adm.data["answer"] == " Revert. " and adm.data["question"] == out["question"]
    assert Reverter(rt).settle() == []


def test_answer_keep_clears_the_hold_and_reverts_nothing(make_runtime) -> None:
    rt, _, out = ask(make_runtime)
    rt.relay.answer(out["question"], "keep")
    Reverter(rt).settle()
    s = rt.state.stories["s1"]
    assert s.po_hold is None and len(s.reverted) == 1 and rt.git.reverted == []
    (adm,) = [e for e in events_of(rt, "story-admin") if e.data.get("tool") == "answer"]
    assert adm.data["decision"] == "keep"


def test_an_unclear_answer_holds_the_story(make_runtime) -> None:
    rt, _, out = ask(make_runtime)
    rt.relay.answer(out["question"], "maybe")
    Reverter(rt).settle()
    s = rt.state.stories["s1"]
    assert s.po_hold == PoHold(
        HoldKind.HOLD, reverts.UNCLEAR_REVERT.format(question=out["question"], answer="maybe")
    )
    assert rt.git.reverted == []


def test_a_failed_revert_after_the_human_said_revert_holds_the_story(make_runtime) -> None:
    rt, _, out = ask(make_runtime)
    rt.git.conflict = "conflicts in a.py"
    rt.relay.answer(out["question"], "revert")
    Reverter(rt).settle()
    s = rt.state.stories["s1"]
    why = reverts.REVERT_CONFLICT.format(story="s1", why="conflicts in a.py")
    assert s.po_hold == PoHold(
        HoldKind.HOLD, reverts.REVERT_FAILED.format(question=out["question"], why=why)
    )
    (adm,) = [e for e in events_of(rt, "story-admin") if e.data.get("tool") == "answer"]
    assert adm.data["failed"] == why and len(s.reverted) == 1


def test_the_router_settles_at_the_start_of_a_tick(make_runtime) -> None:
    rt, _, out = ask(make_runtime)
    rt.relay.answer(out["question"], "keep")
    asyncio.run(Router(rt).advance())
    assert rt.state.stories["s1"].po_hold is None


def test_wait_for_answers_settles_a_revert_answer(make_runtime) -> None:
    rt, t, out = ask(make_runtime)
    rt.relay.answer(out["question"], "keep")
    call(t.wait_for_answers({"ids": [out["question"]], "timeout_s": 1}))
    assert rt.state.stories["s1"].po_hold is None


def test_hold_and_cancel_are_refused_while_a_revert_question_waits(make_runtime) -> None:
    _, t, out = ask(make_runtime)
    text = story_admin.REVERT_PENDING.format(story="s1", question=out["question"])
    assert call(t.hold_story({"story": "s1", "reason": "x"})) == {
        "status": "refused",
        "reason": text,
    }
    assert call(t.request_cancel({"story": "s1", "reason": "x"}))["reason"] == text


# ----- R8-R9: briefs and the design gate -----------------------------------------------


def prompt(rt, role: str, sid: str = "s1") -> str:
    return rt.user_prompt(rt.plan(StepRequest(role, "go", sid)))


def test_owed_roles_get_the_note_once(make_runtime) -> None:
    rt, t = setup(make_runtime)
    for role in ("architect", "unit-tester"):
        rt.events.emit(Event(EventKind.STEP_END, role, "s1", {}))
    revert(t)
    s = rt.state.stories["s1"]
    assert s.revert_owed == ["architect", "unit-tester"]
    text = prompt(rt, "architect")
    assert "## Reverted" in text and "went the wrong way" in text
    assert revert_log.REDESIGN_LINE.format(count=1) in text
    assert s.revert_owed == ["unit-tester"]
    again = prompt(rt, "architect")
    assert "went the wrong way" in again  # design step: the redesign section stays
    assert "## Reverted\n\nThis story was reverted" in again
    assert "developer-cli" not in s.revert_owed


def test_a_role_never_on_the_story_gets_no_note(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.events.emit(Event(EventKind.STEP_END, "architect", "s1", {}))
    revert(t)
    s = rt.state.stories["s1"]
    s.step = "tests"
    assert "This story was reverted" not in prompt(rt, "unit-tester")
    assert s.revert_owed == ["architect"]


def test_after_the_note_a_later_step_has_none(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.events.emit(Event(EventKind.STEP_END, "unit-tester", "s1", {}))
    revert(t)
    s = rt.state.stories["s1"]
    s.step = "tests"
    assert "This story was reverted 1×" in prompt(rt, "unit-tester")  # noqa: RUF001
    assert "This story was reverted" not in prompt(rt, "unit-tester")


def test_design_gate_needs_the_after_revert_section(make_runtime) -> None:
    from agile_team.roles import Handoff

    rt, _ = setup(make_runtime)
    s = rt.state.stories["s1"]
    s.step = "design"
    s.reverted = [revert_log.RevertEntry("2026-01-01", 1, "r", [FIRST], REVERT_SHA)]
    rt.pipeline.checks.design_file = lambda sid: f"docs/design/{sid}.md"
    rt.pipeline.checks.read = lambda path: "# s1\n\nnothing\n"
    out = rt.pipeline.evaluate(s, Handoff("done"))
    assert out.verdict is gates.Verdict.BOUNCE and out.bounce_to == "design"
    assert out.reason == gates.REDESIGN_MISSING.format(id="s1", count=1, file="docs/design/s1.md")
    assert out.author is gates.Author.ROLE
    rt.pipeline.checks.read = lambda path: "# s1\n\n## After revert 1\n\nchanges\n"
    assert rt.pipeline.evaluate(s, Handoff("done")).verdict is gates.Verdict.PASS


def test_design_gate_ignores_a_story_never_reverted(make_runtime) -> None:
    from agile_team.roles import Handoff

    rt, _ = setup(make_runtime)
    s = rt.state.stories["s1"]
    s.step = "design"
    rt.pipeline.checks.read = lambda path: "# s1\n"
    assert rt.pipeline.evaluate(s, Handoff("done")).verdict is gates.Verdict.PASS


# ----- R12: the review PR ----------------------------------------------------------------


def test_the_pr_lists_reverted_stories(make_runtime) -> None:
    rt, _ = setup(make_runtime, steps=("s1", "s2"))
    runner = BoundaryRunner(rt)
    b = bd.Boundary(Edge.END, 1)
    entry = runner._entry(b, "a" * 40)
    assert entry.reverted == []
    plain = runner._body(entry, "")
    assert "Reverted:" not in plain
    rt.state.stories["s1"].reverted = [
        revert_log.RevertEntry("2026-01-01", 1, "why", [FIRST, FIXUP], REVERT_SHA)
    ]
    rt.state.stories["s1"].sprint = None
    rt.state.stories["s2"].status = StoryStatus.DONE
    entry = runner._entry(b, "a" * 40)
    assert entry.reverted == ["s1"] and entry.stories == ["s2"]
    body = runner._body(entry, "")
    assert "Reverted:\n" in body
    assert (
        f"- s1: Title s1: why (reverted {FIRST[:12]}, {FIXUP[:12]}; revert {REVERT_SHA[:12]})"
        in body
    )


# ----- K1-K3: the ready backlog --------------------------------------------------------------


def backlog(rt, sid: str, **kw) -> None:
    rt.state.stories[sid] = StoryState(sid, f"Title {sid}", "design", sprint=None, **kw)
    rt.state.order.append(sid)


def stalled_sprint(make_runtime):
    rt, _ = setup(make_runtime, steps=("s1", "s2"))
    rt.state.stories["s1"].status = StoryStatus.DONE
    rt.state.stories["s2"].po_hold = PoHold(HoldKind.HOLD, "r")
    return rt


def test_ready_backlog_selects_in_queue_order(make_runtime) -> None:
    rt = stalled_sprint(make_runtime)
    backlog(rt, "s3")
    backlog(rt, "s4", depends_on=["s9"])  # unmet dependency
    backlog(rt, "s5", hold="stopped")
    backlog(rt, "s6", po_hold=PoHold(HoldKind.HOLD, "r"))
    backlog(rt, "s7", status=StoryStatus.CANCELLED)
    queue = rt.priority().queue(rt.state.stories.values())
    assert sprint_end.ready_backlog(rt.state.stories, queue) == ["s3"]


def test_the_offer_is_made_once_while_a_question_is_open(make_runtime) -> None:
    rt = stalled_sprint(make_runtime)
    backlog(rt, "s3")
    backlog(rt, "s4", depends_on=["s9"])
    rt.relay.post(Note("question", "which?"))
    first = Router(rt)._idle()
    assert first.kinds == [Trigger.READY_BACKLOG] and first.stories == []
    assert not first.quiet()
    assert first.lines[0] == "Nothing in sprint 1 can move."
    assert sprint_end.READY_HEAD in first.lines and "- s3: Title s3" in first.lines
    assert not any("s4:" in line for line in first.lines if line.startswith("- "))
    assert first.lines[-1] == sprint_end.READY_ADVICE
    assert rt.state.offered == ["s2", "s3"]
    assert Router(rt)._idle() is None  # the same key: wait on the question
    backlog(rt, "s8")
    again = Router(rt)._idle()
    assert again.kinds == [Trigger.READY_BACKLOG] and rt.state.offered == ["s2", "s3", "s8"]


def test_the_offer_state_is_saved(make_runtime) -> None:
    rt = stalled_sprint(make_runtime)
    backlog(rt, "s3")
    Router(rt)._idle()
    saved = json.loads(rt.state.to_json())
    assert saved["offered"] == ["s2", "s3"]
    assert RunState.from_json(rt.state.to_json()).offered == ["s2", "s3"]


def test_without_ready_stories_it_stalls_as_before(make_runtime) -> None:
    rt = stalled_sprint(make_runtime)
    backlog(rt, "s4", depends_on=["s9"])
    assert Router(rt)._idle().kinds == [Trigger.STALLED]
    rt.relay.post(Note("question", "which?"))
    assert Router(rt)._idle() is None


def test_no_offer_while_a_boundary_is_pending(make_runtime) -> None:
    rt = stalled_sprint(make_runtime)
    backlog(rt, "s3")
    rt.state.boundary = bd.Boundary(Edge.END, 1)
    assert Router(rt)._idle().kinds != [Trigger.READY_BACKLOG]


def test_six_ready_stories_show_five_and_a_count(make_runtime) -> None:
    rt = stalled_sprint(make_runtime)
    for n in range(3, 9):
        backlog(rt, f"s{n}")
    lines = Router(rt)._idle().lines
    shown = [x for x in lines if x.startswith("- s")]
    assert len(shown) == 5 and sprint_end.READY_MORE.format(count=1) in lines


def test_the_offer_trigger_is_not_quiet_after_the_po() -> None:
    assert Trigger.READY_BACKLOG == "ready_backlog"
    assert Trigger.READY_BACKLOG not in __import__("agile_team.handover").handover.QUIET_AFTER_PO


# ----- schema ---------------------------------------------------------------------------------


def test_revert_story_schema() -> None:
    text, params = SCHEMAS["revert_story"]
    assert params == {"story": str, "reason": str}
    assert "revert" in text and "sprint-end is refused" in SCHEMAS["notify_user"][0]
