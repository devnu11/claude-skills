"""s185: s159's AC10 (resume and switch) still holds under s179's wording of REQ-160."""

from __future__ import annotations

import asyncio

import pytest
from agile_team import state as state_mod
from agile_team import system
from agile_team.boundary import StackEntry
from agile_team.events import EventKind
from agile_team.gates import StoryState, StoryStatus
from agile_team.po_tools import SWITCH_REFUSED, Tools
from agile_team.salvage import Cause, InFlight
from agile_team.state import RunStatus
from agile_team.switchover import AHEAD, PAST_DESIGN, PENDING, STACK

from .fake_system import Done
from .test_s163_handover_switch import HEAD_A, direct
from .test_s179_resume_keeps_worktrees import pruned, removals, resumed, story

# ---------- AC1: one resume, one story of each kind (REQ-239) ----------


def test_a_resume_keeps_open_sprint_worktrees_and_removes_the_rest_ac1(make_runtime, fake) -> None:
    flying = InFlight("developer-cli", "s3", "brief")
    rt = resumed(
        make_runtime,
        story("s1"),
        story("s2", status=StoryStatus.BLOCKED),
        story("s3", status=StoryStatus.DONE, sprint=2, in_flight=flying),
        story("s4", status=StoryStatus.DONE),
        story("s5", status=StoryStatus.CANCELLED),
        story("s6", sprint=None),
        story("s7", sprint=2),
    )
    got = {(e.story, e.data["reason"]) for e in pruned(rt)}
    assert got == {
        ("s4", "done"),
        ("s5", "cancelled"),
        ("s6", "not_in_sprint"),
        ("s7", "not_in_sprint"),
    }


def test_a_resume_removes_the_dir_of_a_story_nobody_knows_ac1(make_runtime, fake) -> None:
    rt = make_runtime()
    rt.state.sprint = 1
    rt.state.stories = {"s1": story("s1"), "s4": story("s4", status=StoryStatus.DONE)}
    for sid in ("s1", "s4", "s9"):
        system.make_dirs(rt.config.run_dir / "worktrees" / sid)
    rt.recover_stories(Cause.CRASH)
    worktrees = rt.config.run_dir / "worktrees"
    assert system.is_dir(worktrees / "s1")
    assert not system.exists(worktrees / "s4") and not system.exists(worktrees / "s9")
    got = [(e.story, e.data["worktree"], e.data["reason"]) for e in pruned(rt)]
    assert sorted(got) == [("s4", "s4", "done"), ("s9", "s9", "unknown")]
    assert all(e.role is None for e in pruned(rt))
    assert rt.state.stories["s4"].worktree_head == ""
    assert rt.state.stories["s1"].worktree_head == story("s1").worktree_head
    kept = [r for r in removals(fake) if r.endswith("/s1")]
    assert kept == []


@pytest.mark.parametrize(
    "kw",
    [{"status": StoryStatus.DONE}, {"status": StoryStatus.CANCELLED}, {"sprint": None}],
)
def test_an_interrupted_steps_worktree_is_kept_whatever_its_kind_ac1(
    make_runtime, fake, kw
) -> None:
    flying = InFlight("developer-cli", "s1", "brief")
    rt = resumed(make_runtime, story("s1", in_flight=flying, **kw))
    assert system.is_dir(rt.config.run_dir / "worktrees" / "s1")
    assert pruned(rt) == []
    assert removals(fake) == []


# ---------- AC2: an older state.json resumes (REQ-240) ----------

OLDER = (
    '{"status": "stopped", "stories": {"s1": {"id": "s1", "title": "Old",'
    ' "step": "implement", "sprint": 1}}, "sprint": 1}'
)


def older_runtime(make_runtime):
    rt = make_runtime()
    system.make_dirs(rt.config.run_dir)
    system.write_text(rt.config.run_dir / state_mod.STATE_FILE, OLDER)
    rt.state = state_mod.load(rt.config.run_dir)
    return rt


def test_an_older_state_resumes_without_removing_or_halting_ac2(make_runtime, fake) -> None:
    rt = older_runtime(make_runtime)
    rt.recover_stories(Cause.CRASH)
    assert pruned(rt) == []
    assert removals(fake) == []
    assert rt.state.story_branches is False
    assert rt.state.status != RunStatus.BLOCKED


def test_an_older_state_gets_the_story_branch_defaults_ac2(make_runtime) -> None:
    s1 = older_runtime(make_runtime).state.stories["s1"]
    assert (s1.branch, s1.base_sha, s1.worktree_head, s1.pushed) == ("", "", "", "")
    assert (s1.pr, s1.landed, s1.replays) == (None, None, 0)


def test_a_stray_dir_under_an_older_state_is_kept_for_an_open_story_ac2(make_runtime, fake) -> None:
    rt = older_runtime(make_runtime)
    system.make_dirs(rt.config.run_dir / "worktrees" / "s1")
    rt.recover_stories(Cause.CRASH)
    assert system.is_dir(rt.config.run_dir / "worktrees" / "s1")
    assert pruned(rt) == []


# ---------- AC3: the switch refuses, naming every obstacle (REQ-241) ----------


class SwitchUpstream:
    """Answers the three upstream questions the switch asks from tables."""

    def __init__(self, in_target: dict | None = None, ahead: int = 0) -> None:
        self.in_target, self.ahead = in_target or {}, ahead

    def missing(self) -> str:
        return ""

    def classify_in_target(self, head: str) -> str | None:
        return self.in_target.get(head)

    def count_unpicked(self, ref: str) -> int:
        return self.ahead if ref == "HEAD" else 0


def set_scene(
    rt,
    *,
    past: bool = False,
    pending: bool = False,
    stack: bool = False,
    ahead: int = 0,
    in_target: dict | None = None,
) -> None:
    """A run on story branches off, with each obstacle present or clear."""
    step = "implement" if past else "design"
    rt.state.sprint = 1
    rt.state.stories = {"s1": StoryState("s1", "T", step, sprint=1)}
    rt.upstream = SwitchUpstream(in_target, ahead)
    if stack:
        rt.state.upstream.stack = [StackEntry(1, "team/sprint-1", "o" * 40, "o" * 40, head=HEAD_A)]
    if pending:
        system.make_dirs(rt.config.repo / ".team")
        system.write_text(rt.config.repo / ".team/pending-tests.json", '{"s2": ["t"]}')


def refusal(rt, monkeypatch, ids: list[str] | None = None) -> str | None:
    """The switch refusal after the start's stack drop.

    Calls ``_drop_merged_entries`` then ``_switch_refusal``, the two steps ``start_sprint``
    runs once the earlier sprint checks pass.
    """
    direct(monkeypatch)
    tools = Tools(rt)
    asyncio.run(tools._drop_merged_entries())
    return tools._switch_refusal(ids or ["s1"])


def test_every_obstacle_is_listed_together_ac3(make_runtime, fake, monkeypatch) -> None:
    rt = make_runtime()
    set_scene(rt, past=True, pending=True, stack=True, ahead=2)
    text = refusal(rt, monkeypatch)
    assert text.startswith(SWITCH_REFUSED.split("{")[0])
    for line in (
        PAST_DESIGN.format(ids="s1"),
        PENDING.format(ids="s2"),
        STACK.format(n=1),
        AHEAD.format(n=2),
    ):
        assert f"- {line}" in text
    assert rt.state.story_branches is False


OBSTACLES = [
    ({"past": True}, PAST_DESIGN.format(ids="s1")),
    ({"pending": True}, PENDING.format(ids="s2")),
    ({"stack": True}, STACK.format(n=1)),
    ({"ahead": 3}, AHEAD.format(n=3)),
]


@pytest.mark.parametrize(("kw", "line"), OBSTACLES)
def test_each_obstacle_alone_refuses_ac3(make_runtime, fake, monkeypatch, kw, line) -> None:
    rt = make_runtime()
    set_scene(rt, **kw)
    text = refusal(rt, monkeypatch)
    assert text.count("\n- ") == 1 and f"- {line}" in text
    assert rt.state.story_branches is False


def test_a_dropped_stack_entry_is_no_obstacle_ac3(make_runtime, fake, monkeypatch) -> None:
    rt = make_runtime()
    set_scene(rt, stack=True, in_target={HEAD_A: "patch-equivalent"})
    assert refusal(rt, monkeypatch) is None
    assert rt.state.upstream.stack == []


def test_a_patch_equivalent_copy_is_no_obstacle_ac3(make_runtime, fake, monkeypatch) -> None:
    rt = make_runtime()
    set_scene(rt, ahead=0)
    assert refusal(rt, monkeypatch) is None
    assert rt.state.story_branches is True


# ---------- AC3: a Product Backlog story past design (REQ-241) ----------


def with_product_backlog_story(rt) -> StoryState:
    set_scene(rt)
    s8 = StoryState("s8", "T", "implement", sprint=None)
    rt.state.stories["s8"] = s8
    return s8


def test_a_product_backlog_story_past_design_keeps_its_step_ac3(
    make_runtime, fake, monkeypatch
) -> None:
    rt = make_runtime()
    s8 = with_product_backlog_story(rt)
    assert refusal(rt, monkeypatch, ["s1"]) is None
    assert rt.state.story_branches is True
    assert s8.step == "implement" and s8.branch == ""


def test_that_storys_next_start_makes_its_branch_and_worktree_ac3(make_runtime, fake) -> None:
    rt = make_runtime()
    s8 = with_product_backlog_story(rt)
    rt.state.story_branches = True
    s8.sprint = 1
    fake.reply(("rev-parse", "HEAD"), Done(0, "c" * 40 + "\n"))
    assert rt.prepare_story(s8) is None
    argvs = [list(c.argv) for c in fake.commands]
    assert [a for a in argvs if "branch" in a and "team/story-s8" in a]
    assert [a for a in argvs if "worktree" in a and "add" in a]
    [event] = [e for e in rt.events.events() if e.kind == EventKind.STORY_BRANCH]
    assert event.story == "s8" and event.data["action"] == "created"
