"""s135: the runner onboards queued stories between steps (design O, P, H, A, R; AC2-AC4, AC6)."""

from __future__ import annotations

import json

import pytest
from agile_team import acceptance, reverts, rewrite, system
from agile_team import boundary as bd
from agile_team.events import EventKind
from agile_team.gates import StoryState, StoryStatus, Trace
from agile_team.revert_log import RevertEntry
from agile_team.state import RunState
from agile_team.story_drafts import LIAISON_AUTHOR, Action, Approval, StoryRequest
from agile_team.story_intake import INTAKE_HOLDS, Intake, StoryQueue

from .fake_system import Done
from .story_setup import Opening, opened

DRAFT = (
    '---\ntitle: "Add   todo"\nacceptance:\n'
    '  - id: AC1\n    text: "adds an item"\n    environment: cli\n'
    "---\n\nAs a user, I want to add items.\n"
)
WITH_ID = "---\nid: {sid}\n" + DRAFT[4:]
OLD = (
    '---\nid: s1\ntitle: "Add todo"\nextra: keep\nacceptance:\n'
    '  - id: AC1\n    text: "old"\n    environment: cli\n'
    "---\n\nBody.\n"
)
AMEND = DRAFT.replace("Add   todo", "Add todo")
STORIES = ".team/stories"


def request(**kw) -> StoryRequest:
    base = {
        "id": "",
        "action": Action.NEW,
        "story": "",
        "approved_by": Approval.NONE,
        "plan": "",
        "sprint": "backlog",
        "after": "",
        "file": "draft.md",
        "text": DRAFT,
    }
    return StoryRequest(**(base | kw))


def queue(rt, **kw) -> StoryRequest:
    return StoryQueue(rt.config.run_dir).queue(request(**kw))


def apply(rt) -> None:
    Intake(rt).apply()


def world(make_runtime, fake):
    rt = make_runtime()
    fake.track()
    return rt


def kind(rt, name: str) -> list:
    return [e for e in rt.events.events() if e.kind == name]


def told_texts(rt) -> list[str]:
    return [system.read_text(t.path) for t in rt.relay.told()]


def sha12(fake) -> str:
    return fake.tree.head[:12]


def file_of(rt, sid: str) -> str:
    return system.read_text(rt.config.repo / STORIES / f"{sid}.md")


def commit_args(fake) -> list[tuple[str, ...]]:
    return [c.argv for c in fake.commands if c.argv[:2] == ("git", "commit")]


def sprint_world(rt) -> None:
    """Sprint 1 open with s1 and s2; s3 in the backlog; order s1, s2, s3."""
    for sid in ("s1", "s2", "s3"):
        opened(rt, Opening(sid, f"title {sid}"))
    rt.state.sprint = 1
    rt.state.stories["s1"].sprint = 1
    rt.state.stories["s2"].sprint = 1
    rt.state.order = ["s1", "s2", "s3"]
    rt.save()


# ----- the queue --------------------------------------------------------------------


def test_the_queue_numbers_requests_and_round_trips_them(make_runtime) -> None:
    rt = make_runtime()
    first, second = queue(rt), queue(rt, file="b.md")
    assert (first.id, second.id) == ("q1", "q2")
    folder = rt.config.run_dir / "liaison" / "stories"
    assert sorted(p.name for p in system.list_dir(folder)) == ["q1.json", "q2.json"]
    back = StoryQueue(rt.config.run_dir).all()
    assert [r.id for r in back] == ["q1", "q2"] and back[1].file == "b.md"
    assert back[0].action is Action.NEW and back[0].approved_by is Approval.NONE
    assert back[0].at > 0


def test_pending_leaves_out_settled_ids(make_runtime) -> None:
    rt = make_runtime()
    queue(rt), queue(rt)
    assert [r.id for r in StoryQueue(rt.config.run_dir).pending({"q1": "x"})] == ["q2"]


def test_a_request_with_a_bad_enum_is_a_bad_request() -> None:
    raw = json.loads(request(id="q1").to_json())
    raw["approved_by"] = "robot"
    out = StoryRequest.from_json("q1", json.dumps(raw))
    assert not isinstance(out, StoryRequest) and out.id == "q1"


def test_unparseable_json_is_a_bad_request() -> None:
    assert not isinstance(StoryRequest.from_json("q1", "{nope"), StoryRequest)


def test_holds_that_allow_intake() -> None:
    assert {h.value for h in INTAKE_HOLDS} == {"ci_failed", "ci_infra", "main_broken"}


# ----- onboarding a new story (O2, O3, AC2) -----------------------------------------


def test_a_new_story_gets_the_next_id_a_file_and_one_commit(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt)
    before = len(fake.tree.commits)
    apply(rt)
    assert file_of(rt, "s1") == WITH_ID.format(sid="s1")
    assert len(fake.tree.commits) == before + 1
    last = fake.tree.commits[-1]
    assert last.paths() == {f"{STORIES}/s1.md"}
    assert last.subject() == "docs(s1): created story to Add todo"


def test_the_next_id_skips_ids_in_state_and_in_files(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    opened(rt, Opening("s2", "two"))
    system.make_dirs(rt.config.repo / STORIES)
    system.write_text(rt.config.repo / STORIES / "s5.md", "x")
    queue(rt)
    apply(rt)
    assert "s6" in rt.state.stories and system.exists(rt.config.repo / STORIES / "s6.md")


def test_the_first_id_is_s1(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt)
    apply(rt)
    assert list(rt.state.stories) == ["s1"]


def test_the_story_is_recorded_like_a_step_commit(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt)
    apply(rt)
    story = rt.state.stories["s1"]
    assert story.title == "Add   todo" and story.step == rt.pipeline.first()
    assert story.file_commits == [fake.tree.head] and story.commit is None
    assert story.files == [f"{STORIES}/s1.md"]
    assert story.sprint is None


def test_depends_on_is_recorded(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    opened(rt, Opening("s1", "one"))
    text = DRAFT.replace("acceptance:", "depends_on: [s1]\nacceptance:", 1)
    queue(rt, text=text)
    apply(rt)
    assert rt.state.stories["s2"].depends_on == ["s1"]


def test_the_checkout_is_recorded_for_the_new_head(make_runtime, fake, monkeypatch) -> None:
    rt = world(make_runtime, fake)
    seen: list[str] = []
    monkeypatch.setattr(rt, "record_checkout", lambda: seen.append(fake.tree.head))
    queue(rt)
    apply(rt)
    assert seen and seen[-1] == fake.tree.head


def test_the_outcome_is_recorded_and_saved(make_runtime, fake) -> None:
    from agile_team import state as state_mod

    rt = world(make_runtime, fake)
    queue(rt)
    apply(rt)
    text = rt.state.story_requests["q1"]
    assert text.startswith(f"opened s1 {sha12(fake)}; ")
    assert state_mod.load(rt.config.run_dir).story_requests == rt.state.story_requests


def test_story_opened_event_has_the_liaison_and_the_data(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt, approved_by=Approval.HUMAN, sprint="next", after="")
    apply(rt)
    [ev] = kind(rt, EventKind.STORY_OPENED)
    assert ev.role == "liaison" and ev.story == "s1"
    assert ev.data == {
        "title": "Add   todo",
        "step": rt.pipeline.first(),
        "depends_on": [],
        "request": "q1",
        "commit": fake.tree.head,
        "approved_by": "human",
        "sprint": "next",
        "after": "",
    }


def test_the_po_is_told_once_and_the_liaison_is_posted_to(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt, approved_by=Approval.HUMAN)
    apply(rt)
    placed = rt.state.story_requests["q1"].split("; ", 1)[1]
    [told] = told_texts(rt)
    assert told == (
        f'Runner note: the liaison\'s story q1 is now s1 "Add   todo" (approved by the human; '
        f"commit {sha12(fake)}), placed {placed}. Read {STORIES}/s1.md, then schedule it."
    )
    [msg] = rt.relay.messages()
    assert msg.kind == "update" and msg.stories == ["s1"]
    assert msg.text == f"Runner: story q1 is s1, commit {sha12(fake)}, placed {placed}."


def test_each_request_is_settled_once_in_number_order(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt), queue(rt, text=DRAFT.replace("Add   todo", "Second"))
    apply(rt)
    commits = len(fake.tree.commits)
    apply(rt)
    assert len(fake.tree.commits) == commits
    assert [rt.state.stories[s].title for s in ("s1", "s2")] == ["Add   todo", "Second"]
    assert list(rt.state.story_requests) == ["q1", "q2"]


def test_nothing_queued_does_nothing(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    commits = len(fake.tree.commits)
    apply(rt)
    assert len(fake.tree.commits) == commits and rt.state.story_requests == {}


# ----- authorship (O3, AC3) ---------------------------------------------------------


def test_none_commits_as_the_liaison_with_its_involvement_line(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt, approved_by=Approval.NONE)
    apply(rt)
    message = fake.tree.commits[-1].message
    assert "\n\nHuman-involvement: none: written and submitted by the liaison\n" in message
    assert "Liaison-request: q1" in message and "Co-Authored-By:" in message
    [argv] = commit_args(fake)
    assert f"--author={LIAISON_AUTHOR}" in argv


def test_human_with_a_plan_names_the_plan_and_has_no_author(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt, approved_by=Approval.HUMAN, plan=".team/run/liaison/plans/p.md")
    apply(rt)
    message = fake.tree.commits[-1].message
    assert "Human-involvement: approved plan `.team/run/liaison/plans/p.md`\n" in message
    [argv] = commit_args(fake)
    assert not [a for a in argv if a.startswith("--author")]


def test_human_without_a_plan_is_approved_by_the_human(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt, approved_by=Approval.HUMAN)
    apply(rt)
    assert "Human-involvement: approved by the human\n" in fake.tree.commits[-1].message


# ----- placement (P1-P4) ------------------------------------------------------------


def placed(make_runtime, fake, **kw):
    rt = world(make_runtime, fake)
    sprint_world(rt)
    queue(rt, **kw)
    apply(rt)
    return rt


def test_current_joins_the_open_sprint_first(make_runtime, fake) -> None:
    rt = placed(make_runtime, fake, sprint="current")
    assert rt.state.stories["s4"].sprint == 1
    assert rt.state.order == ["s4", "s1", "s2", "s3"]
    assert rt.state.story_requests["q1"].endswith("; in sprint 1")
    [add] = kind(rt, EventKind.SPRINT_ADD)
    assert add.role == "liaison" and add.data["stories"] == ["s4"]


def test_current_without_an_open_sprint_falls_back_to_the_backlog(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    sprint_world(rt)
    rt.state.sprint = 0
    queue(rt, sprint="current")
    apply(rt)
    assert rt.state.stories["s4"].sprint is None and rt.state.order[-1] == "s4"
    assert "; in the backlog; not added to sprint 0: " in rt.state.story_requests["q1"]
    assert kind(rt, EventKind.SPRINT_ADD) == []


def test_next_goes_right_after_the_sprints_last_story(make_runtime, fake) -> None:
    rt = placed(make_runtime, fake, sprint="next")
    assert rt.state.order == ["s1", "s2", "s4", "s3"]
    assert rt.state.stories["s4"].sprint is None
    assert "in the backlog, first for the next sprint" in rt.state.story_requests["q1"]


def test_next_with_no_sprint_stories_goes_first(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    opened(rt, Opening("s1", "one"))
    queue(rt, sprint="next")
    apply(rt)
    assert rt.state.order[0] == "s2"


def test_backlog_goes_last(make_runtime, fake) -> None:
    rt = placed(make_runtime, fake, sprint="backlog")
    assert rt.state.order == ["s1", "s2", "s3", "s4"]
    assert rt.state.story_requests["q1"].endswith("; in the backlog")


def test_backlog_with_an_empty_plan_is_just_the_story(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt, sprint="backlog")
    apply(rt)
    assert rt.state.order == ["s1"]


@pytest.mark.parametrize("mode", ["current", "next", "backlog"])
def test_after_places_right_after_that_story_in_each_mode(make_runtime, fake, mode) -> None:
    rt = placed(make_runtime, fake, sprint=mode, after="s2")
    assert rt.state.order == ["s1", "s2", "s4", "s3"]
    assert rt.state.story_requests["q1"].endswith(" after s2")


def test_a_finished_after_is_dropped_with_its_text(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    sprint_world(rt)
    queue(rt, sprint="backlog", after="s3")
    rt.state.stories["s3"].status = StoryStatus.DONE
    rt.save()
    apply(rt)
    assert rt.state.order[-1] == "s4"
    assert "; --after s3 dropped: it is done" in rt.state.story_requests["q1"]


def test_priority_events_are_the_liaisons(make_runtime, fake) -> None:
    rt = placed(make_runtime, fake, sprint="backlog")
    events = kind(rt, EventKind.PRIORITY)
    assert events and events[-1].role == "liaison"
    assert events[-1].data["reason"] == "placed for the liaison's request q1"


# ----- the safe point (O1) ----------------------------------------------------------


def hold(rt, name: str | None) -> None:
    rt.state.boundary = bd.Boundary(bd.Edge.END, 1, hold=bd.BoundaryHold(name) if name else None)


def test_nothing_is_settled_while_a_boundary_is_open(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt)
    hold(rt, None)
    commits = len(fake.tree.commits)
    apply(rt)
    assert rt.state.story_requests == {} and len(fake.tree.commits) == commits
    rt.state.boundary = None
    apply(rt)
    assert rt.state.story_requests["q1"].startswith("opened s1 ")


def test_a_ci_failed_hold_lets_intake_run(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt)
    hold(rt, "ci_failed")
    apply(rt)
    assert rt.state.story_requests["q1"].startswith("opened s1 ")


def test_a_sync_conflict_hold_does_not(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt)
    hold(rt, "sync_conflict")
    apply(rt)
    assert rt.state.story_requests == {}


# ----- refusals (R1) ----------------------------------------------------------------


def refused(rt, rid: str = "q1") -> str:
    text = rt.state.story_requests[rid]
    assert text.startswith("refused: ")
    return text.removeprefix("refused: ")


def test_a_draft_that_no_longer_checks_is_refused(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt, text=DRAFT.replace("environment: cli", "environment: gone"))
    commits = len(fake.tree.commits)
    apply(rt)
    assert "gone" in refused(rt)
    assert len(fake.tree.commits) == commits and rt.state.stories == {}
    assert told_texts(rt) == []
    [ev] = kind(rt, EventKind.STORY_REFUSED)
    assert ev.role == "liaison" and ev.story is None
    assert ev.data == {"request": "q1", "action": "new", "reason": refused(rt)}
    [msg] = rt.relay.messages()
    assert msg.kind == "update" and msg.text == f"Runner: story q1 was refused: {refused(rt)}"


def test_several_problems_are_joined_with_semicolons(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt, text="---\nid: s9\n---\n\n")
    apply(rt)
    assert "; " in refused(rt)


def test_a_bad_json_request_is_refused_the_same_way(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    folder = rt.config.run_dir / "liaison" / "stories"
    system.make_dirs(folder)
    system.write_text(folder / "q1.json", "not json")
    apply(rt)
    assert refused(rt)
    [ev] = kind(rt, EventKind.STORY_REFUSED)
    assert ev.data["request"] == "q1" and not told_texts(rt)
    assert len(rt.relay.messages()) == 1


def test_a_refused_request_is_not_retried(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    queue(rt, text="no frontmatter")
    apply(rt)
    apply(rt)
    assert len(kind(rt, EventKind.STORY_REFUSED)) == 1


def test_a_failed_commit_removes_the_file_and_leaves_the_tree_clean(make_runtime, fake) -> None:
    rt = world(make_runtime, fake)
    fake.reply(("git", "commit"), Done(1, "", "boom"))
    queue(rt)
    apply(rt)
    assert "commit failed: " in refused(rt) and "boom" in refused(rt)
    assert not system.exists(rt.config.repo / STORIES / "s1.md")
    assert any(c.argv[:3] == ("git", "reset", "-q") for c in fake.commands[-3:])
    assert "s1" not in rt.state.stories and kind(rt, EventKind.STORY_OPENED) == []


# ----- amend (A1-A6, AC4) -----------------------------------------------------------


def amending(make_runtime, fake, **kw):
    rt = world(make_runtime, fake)
    story = opened(rt, Opening("s1", "Add todo"))
    story.step, story.rounds, story.hold = "implement", 2, "stuck"
    story.status, story.trace = StoryStatus.NEEDS_MANAGER, Trace.EXEMPT
    story.tried = [acceptance.Tried("cli", next(iter(acceptance.Mark)))]
    system.make_dirs(rt.config.repo / STORIES)
    system.write_text(rt.config.repo / STORIES / "s1.md", OLD)
    rt.save()
    queue(rt, action=Action.AMEND, story="s1", sprint="", text=AMEND, **kw)
    return rt


NEW_FILE = (
    '---\nid: s1\ntitle: "Add todo"\nextra: keep\nacceptance:\n'
    '  - id: "AC1"\n    text: "adds an item"\n    environment: "cli"\n'
    "---\n\nBody.\n"
)


def test_amend_replaces_the_acs_and_keeps_the_rest(make_runtime, fake) -> None:
    rt = amending(make_runtime, fake)
    apply(rt)
    assert file_of(rt, "s1") == NEW_FILE


def test_amend_is_one_commit_appended_to_file_commits(make_runtime, fake) -> None:
    rt = amending(make_runtime, fake)
    before = len(fake.tree.commits)
    apply(rt)
    assert len(fake.tree.commits) == before + 1
    last = fake.tree.commits[-1]
    assert last.paths() == {f"{STORIES}/s1.md"}
    assert last.subject() == "docs(s1): amended story to Add todo"
    assert "Human-involvement: none: written and submitted by the liaison" in last.message
    assert rt.state.stories["s1"].file_commits == [fake.tree.head]
    assert rt.state.story_requests["q1"] == f"amended s1 {sha12(fake)}"


def test_amend_sends_the_story_back_to_design(make_runtime, fake) -> None:
    rt = amending(make_runtime, fake)
    apply(rt)
    s = rt.state.stories["s1"]
    assert s.step == rt.pipeline.design_step() and s.rounds == 0 and s.hold is None
    assert s.tried == [] and s.trace is Trace.CHECKED and s.status is StoryStatus.ACTIVE
    assert s.note == (
        "The liaison amended the ACs (q1); design against the new ACs and "
        "trace each to a requirement."
    )


def test_amend_keeps_a_blocked_story_blocked(make_runtime, fake) -> None:
    rt = amending(make_runtime, fake)
    rt.state.stories["s1"].status = StoryStatus.BLOCKED
    rt.save()
    apply(rt)
    assert rt.state.stories["s1"].status is StoryStatus.BLOCKED


def test_story_amended_event_carries_old_and_new(make_runtime, fake) -> None:
    rt = amending(make_runtime, fake)
    apply(rt)
    [ev] = kind(rt, EventKind.STORY_AMENDED)
    assert ev.role == "liaison" and ev.story == "s1"
    assert ev.data == {
        "request": "q1",
        "commit": fake.tree.head,
        "approved_by": "none",
        "from_step": "implement",
        "step": rt.pipeline.design_step(),
        "old": [{"id": "AC1", "text": "old", "environment": "cli"}],
        "new": [{"id": "AC1", "text": "adds an item", "environment": "cli"}],
    }


def test_amend_tells_the_po_and_posts_to_the_liaison(make_runtime, fake) -> None:
    rt = amending(make_runtime, fake)
    apply(rt)
    step = rt.pipeline.design_step()
    [told] = told_texts(rt)
    assert told == (
        f"Runner note: the liaison amended s1's ACs (q1; written by the liaison alone; "
        f"commit {sha12(fake)}). It is back at {step} from implement. Old: AC1. New: AC1. "
        f"Read {STORIES}/s1.md."
    )
    [msg] = rt.relay.messages()
    assert msg.text == (
        f"Runner: story q1 amended s1's ACs, commit {sha12(fake)}; it is back at {step}."
    )


def test_amend_of_a_story_that_finished_meanwhile_is_refused(make_runtime, fake) -> None:
    rt = amending(make_runtime, fake)
    rt.state.stories["s1"].status = StoryStatus.DONE
    rt.save()
    commits = len(fake.tree.commits)
    apply(rt)
    assert refused(rt) == "s1 is done; story amend changes open stories only"
    assert len(fake.tree.commits) == commits and file_of(rt, "s1") == OLD
    assert kind(rt, EventKind.STORY_AMENDED) == []


def test_amend_whose_frontmatter_cannot_be_rewritten_is_refused(make_runtime, fake) -> None:
    rt = amending(make_runtime, fake)
    odd = OLD.replace("  - id: AC1", "  - &a\n    id: AC1").replace(
        "---\n\nBody", "ref: *a\n---\n\nBody"
    )
    system.write_text(rt.config.repo / STORIES / "s1.md", odd)
    apply(rt)
    assert refused(rt) == (
        "cannot rewrite .team/stories/s1.md's acceptance block; fix its frontmatter"
    )
    assert file_of(rt, "s1") == odd


def test_a_failed_amend_commit_restores_the_old_text(make_runtime, fake) -> None:
    rt = amending(make_runtime, fake)
    fake.reply(("git", "commit"), Done(1, "", "boom"))
    apply(rt)
    assert "commit failed: " in refused(rt)
    assert file_of(rt, "s1") == OLD and rt.state.stories["s1"].file_commits == []
    assert rt.state.stories["s1"].step == "implement"


# ----- recorded like a step commit: rewrite, reverts, snapshot (O4) ------------------


def test_remap_state_remaps_file_commits(make_runtime) -> None:
    state = RunState(stories={"s1": StoryState("s1", "t", "design", file_commits=["aaa", "bbb"])})
    count = rewrite.remap_state(state, {"aaa": "AAA"})
    assert state.stories["s1"].file_commits == ["AAA", "bbb"] and count == 1


def test_a_reverted_story_keeps_its_file_commits() -> None:
    story = StoryState("s1", "t", "design", file_commits=["f1"], commit="c1")
    entry = RevertEntry("2026-10-14", 2, "bad", ["a" * 40], "c" * 40, "d" * 40)
    back = reverts.Back("design", entry, [])
    assert reverts.reverted_story(story, back).file_commits == ["f1"]


def test_story_commits_never_picks_the_file_commit() -> None:
    log = [("f1", "docs(s1): created story to Add todo"), ("c1", "feat(s1): add todo")]
    assert reverts.story_commits(log, "feat(s1): add todo") == ["c1"]
    assert reverts.story_commits(log, "docs(s1): amended story to Add todo") == []


def test_the_snapshot_lists_the_file_commit_first(scratch) -> None:
    from agile_team import state as state_mod

    from .test_snapshot import build, make_config

    config = make_config(scratch / "repo")
    story = StoryState("s1", "t", "design", commit="c1", code_commits=["c2"], file_commits=["f1"])
    state_mod.save(config.run_dir, RunState(stories={"s1": story}))
    [shown] = [s for s in build(config, scratch)["stories"] if s["id"] == "s1"]
    assert shown["commits"] == ["f1", "c1", "c2"]
