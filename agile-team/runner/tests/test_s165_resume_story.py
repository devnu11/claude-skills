"""s165: a resume after a cut-off story step (I2): stopped step-end, kept session, kept
worktree, and an ``interrupted`` record whose fields are in order."""

from __future__ import annotations

from agile_team import cli, salvage, state, system
from agile_team.dispatch import StepRequest
from agile_team.events import Event, EventKind
from agile_team.gates import StoryState
from agile_team.halt import HaltKind
from agile_team.po_tools import Start, StartMode
from agile_team.salvage import Cause, InFlight, Interruption

from .conftest import write_story

ROLE = "developer-cli"
BRIEF = "build it\nsecond line"
SESSION = "sess-1"
EDIT = "src/edit.py"


def in_flight(make_runtime):
    """A run that stopped while ``ROLE`` was at implement in s1's worktree, not yet resumed."""
    rt = make_runtime()
    rt.state.story_branches = True
    story = StoryState("s1", "T", "implement", sprint=1, worktree_head="a" * 40)
    story.branch, story.in_flight = "team/story-s1", InFlight(ROLE, "s1", BRIEF, session=SESSION)
    rt.state.stories = {"s1": story, "s2": StoryState("s2", "Idle", "design", sprint=1)}
    rt.events.emit(Event(EventKind.STEP_START, ROLE, "s1", {"brief": BRIEF}))
    worktree = rt.config.run_dir / "worktrees" / "s1"
    system.make_dirs(worktree / "src")
    system.write_text(worktree / EDIT, "x = 1\n")
    return rt, story, worktree


def cut_off(make_runtime, cause: Cause = Cause.CRASH):
    """``in_flight``, then resumed through ``Runtime.recover_stories``."""
    rt, story, worktree = in_flight(make_runtime)
    rt.recover_stories(cause)
    return rt, story, worktree


def test_the_cut_off_step_ends_as_stopped_with_its_cause(make_runtime) -> None:
    rt, _, _ = cut_off(make_runtime)
    last = rt.events.events()[-1]
    assert (last.kind, last.role, last.story) == (EventKind.STEP_END, ROLE, "s1")
    assert last.data == {"status": "stopped", "interrupted": "crash"}


def test_the_interrupted_record_names_role_story_brief_and_cause(make_runtime) -> None:
    rt, story, _ = cut_off(make_runtime, Cause.SIGTERM)
    assert story.interrupted == Interruption(ROLE, "s1", BRIEF, Cause.SIGTERM, None)
    assert story.interrupted.cause is Cause.SIGTERM and story.interrupted.brief == BRIEF
    assert story.in_flight is None
    assert rt.state.stories["s2"].interrupted is None  # a story with nothing in flight


def test_the_session_and_the_worktree_with_its_edits_are_kept(make_runtime) -> None:
    _, story, worktree = cut_off(make_runtime)
    assert story.sessions[ROLE].session == SESSION
    assert system.read_text(worktree / EDIT) == "x = 1\n"


def test_the_next_step_of_that_role_resumes_in_the_worktree(make_runtime) -> None:
    rt, story, worktree = cut_off(make_runtime)
    view = rt.get_story_view(story)
    write_story(view.config, "s1", "cli")
    plan = view.plan(StepRequest(ROLE, "go", "s1"))
    assert view.config.repo == worktree and plan.scope.repo == worktree
    assert salvage.offer(story.interrupted) in plan.prompt
    assert "crash" in plan.prompt and plan.launch.resume == SESSION


def test_resume_without_a_halt_kind_records_killed(make_runtime) -> None:
    rt, story, _ = in_flight(make_runtime)
    cli._recover_stories(rt, Start("", StartMode.RESUME))
    assert story.interrupted.cause is Cause.KILLED


def test_resume_with_a_crash_halt_kind_records_crash(make_runtime) -> None:
    rt, story, _ = in_flight(make_runtime)
    rt.state.halt_kind = HaltKind.CRASH
    cli._recover_stories(rt, Start("", StartMode.RESUME))
    assert story.interrupted.cause is Cause.CRASH


def test_the_interrupted_record_survives_a_state_json_round_trip(make_runtime) -> None:
    rt, _, _ = cut_off(make_runtime, Cause.SIGTERM)
    loaded = state.load(rt.config.run_dir).stories["s1"]
    assert loaded.interrupted == Interruption(ROLE, "s1", BRIEF, Cause.SIGTERM, None)
    assert loaded.in_flight is None


def test_every_halt_kind_is_a_cause() -> None:
    assert {Cause(k) for k in HaltKind} <= set(Cause)


def test_the_story_stays_at_implement_after_the_resume(make_runtime) -> None:
    _, story, _ = cut_off(make_runtime)
    assert story.step == "implement"
