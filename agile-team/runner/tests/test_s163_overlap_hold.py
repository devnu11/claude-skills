"""s163 AC2 (F3 to F8): the overlap screen, its hold, the lift and release_story."""

from __future__ import annotations

import asyncio

from agile_team.events import EventKind
from agile_team.gates import Outcome, StoryState, StoryStatus, Verdict, is_overlap_hold
from agile_team.loops import Author
from agile_team.overlaps import Overlaps
from agile_team.po_tools import Tools

from .fake_system import Done

OURS = "## Files\n- src/a.py\n- src/b.py\n"
THEIRS = "## Files\n- src/b.py\n"


def passing(author: Author = Author.ROLE) -> Outcome:
    return Outcome(Verdict.PASS, "ok", author=author)


def setup(make_runtime, fake, ours: str = OURS):
    rt = make_runtime()
    rt.state.sprint, rt.state.story_branches = 1, True
    me = StoryState("s1", "T", "design", sprint=1, branch="team/story-s1", base_sha="b" * 40)
    other = StoryState("s2", "T", "implement", sprint=1, branch="team/story-s2", base_sha="c" * 40)
    rt.state.stories = {"s1": me, "s2": other}
    rt.pipeline.checks.read = lambda path: ours
    fake.reply(("show",), Done(0, THEIRS))
    fake.reply(("diff", "--name-only"), Done(0, ""))
    return rt, me, other


def screened(rt, story, outcome: Outcome | None = None) -> Outcome:
    return Overlaps(rt).screen(story, outcome or passing())


def held(rt, me, other) -> None:
    me.hold, me.overlap_with = "overlap", [other.id]
    rt.state.stories["s1"] = me


# ---------- the screen ----------


def test_an_overlap_holds_the_design_and_names_both_stories_f3(make_runtime, fake) -> None:
    rt, me, _ = setup(make_runtime, fake)
    out = screened(rt, me)
    assert out.verdict is Verdict.HOLD and "s2" in out.reason and "src/b.py" in out.reason
    assert out.overlap == {
        "files": ["src/a.py", "src/b.py"],
        "with": [{"story": "s2", "files": ["src/b.py"], "overlap": ["src/b.py"]}],
    }
    assert me.overlap_with == ["s2"]


def test_no_overlap_leaves_the_outcome_alone_f3(make_runtime, fake) -> None:
    rt, me, _ = setup(make_runtime, fake, ours="## Files\n- src/z.py\n")
    outcome = passing()
    assert screened(rt, me, outcome) is outcome and me.overlap_with == []


def test_a_bounce_is_not_screened_f3(make_runtime, fake) -> None:
    rt, me, _ = setup(make_runtime, fake)
    outcome = Outcome(Verdict.BOUNCE, "no", author=Author.ROLE)
    assert screened(rt, me, outcome) is outcome


def test_a_runner_made_pass_is_not_screened_f3(make_runtime, fake) -> None:
    rt, me, _ = setup(make_runtime, fake)
    outcome = passing(Author.RUNNER)
    assert screened(rt, me, outcome) is outcome


def test_a_story_past_design_is_not_screened_f3(make_runtime, fake) -> None:
    rt, me, _ = setup(make_runtime, fake)
    me.step = "implement"
    outcome = passing()
    assert screened(rt, me, outcome) is outcome


def test_nothing_is_screened_before_story_branches_f3(make_runtime, fake) -> None:
    rt, me, _ = setup(make_runtime, fake)
    rt.state.story_branches = False
    outcome = passing()
    assert screened(rt, me, outcome) is outcome


def test_only_open_stories_past_design_in_this_sprint_count_f3(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake)
    other.status = StoryStatus.DONE
    assert screened(rt, me).verdict is Verdict.PASS
    other.status, other.step = StoryStatus.ACTIVE, "design"
    assert screened(rt, me).verdict is Verdict.PASS
    other.step, other.sprint = "implement", 2
    assert screened(rt, me).verdict is Verdict.PASS


def test_ignored_areas_never_overlap_f4(make_runtime, fake) -> None:
    both = "## Files\n- .team/x.md\n"
    rt, me, _ = setup(make_runtime, fake, ours=both)
    fake.reply(("show",), Done(0, both))
    assert screened(rt, me).verdict is Verdict.PASS


def test_the_other_stories_changed_files_count_f3(make_runtime, fake) -> None:
    rt, me, _ = setup(make_runtime, fake, ours="## Files\n- src/c.py\n")
    fake.reply(("diff", "--name-only", f"{'c' * 40}..team/story-s2"), Done(0, "src/c.py\n"))
    assert screened(rt, me).verdict is Verdict.HOLD


def test_a_failed_diff_error_is_not_read_as_paths_d3(make_runtime, fake) -> None:
    rt, me, _ = setup(make_runtime, fake, ours="## Files\n- fatal\n")
    fake.reply(("show",), Done(1, "fatal: bad"))
    fake.reply(("diff", "--name-only"), Done(128, "fatal: bad revision"))
    assert screened(rt, me).verdict is Verdict.PASS


def test_a_failed_show_means_no_listed_files_f3(make_runtime, fake) -> None:
    rt, me, _ = setup(make_runtime, fake)
    fake.reply(("show",), Done(1, "fatal"))
    assert screened(rt, me).verdict is Verdict.PASS


def test_a_story_with_no_branch_has_no_changed_files_d3(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake, ours="## Files\n- src/c.py\n")
    other.branch = ""
    fake.reply(("show",), Done(1, ""))
    fake.reply(("diff", "--name-only"), Done(0, "src/c.py\n"))
    assert screened(rt, me).verdict is Verdict.PASS
    assert [c for c in fake.commands if "--name-only" in c.argv] == []


# ---------- the lift ----------


def test_the_runner_lifts_when_every_other_story_is_done_f6(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake)
    held(rt, me, other)
    other.status = StoryStatus.DONE
    Overlaps(rt).lift_due()
    assert not is_overlap_hold(me) and me.overlap_with == [] and me.step != "design"
    [event] = [e for e in rt.events.events() if e.kind == EventKind.OVERLAP_LIFTED]
    assert event.data["by"] == "runner" and event.data["with"] == ["s2"]


def test_a_cancelled_or_departed_story_clears_the_hold_f6(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake)
    held(rt, me, other)
    other.status = StoryStatus.CANCELLED
    assert Overlaps(rt)._is_clear(me)
    other.status, other.sprint = StoryStatus.ACTIVE, 2
    assert Overlaps(rt)._is_clear(me)
    me.overlap_with = ["s9"]
    assert Overlaps(rt)._is_clear(me)


def test_an_open_overlapping_story_keeps_the_hold_f6(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake)
    held(rt, me, other)
    Overlaps(rt).lift_due()
    assert is_overlap_hold(me) and me.step == "design"


def test_a_hold_of_another_kind_is_not_lifted_f6(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake)
    me.hold = "question"
    other.status = StoryStatus.DONE
    Overlaps(rt).lift_due()
    assert me.hold == "question"


# ---------- release_story ----------


def test_release_needs_a_reason_f7(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake)
    held(rt, me, other)
    out = Overlaps(rt).release(me, "  ")
    assert out["status"] == "refused" and is_overlap_hold(me)


def test_release_lifts_early_and_records_the_reason_f7(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake)
    held(rt, me, other)
    out = Overlaps(rt).release(me, "they touch different functions")
    assert out["status"] == "released" and not is_overlap_hold(me)
    [event] = [e for e in rt.events.events() if e.kind == EventKind.OVERLAP_LIFTED]
    assert event.data["by"] == "po" and event.data["reason"] == "they touch different functions"


def test_the_release_tool_routes_an_overlap_hold_to_overlaps_f7(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake)
    held(rt, me, other)
    out = asyncio.run(Tools(rt).release_story({"story": "s1", "reason": "fine"}))
    assert "released" in out["content"][0]["text"] and not is_overlap_hold(me)


def test_the_release_tool_without_a_reason_refuses_an_overlap_hold_f7(make_runtime, fake) -> None:
    rt, me, other = setup(make_runtime, fake)
    held(rt, me, other)
    out = asyncio.run(Tools(rt).release_story({"story": "s1"}))
    assert "reason is required" in out["content"][0]["text"] and is_overlap_hold(me)
