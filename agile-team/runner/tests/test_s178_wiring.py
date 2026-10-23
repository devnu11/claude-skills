"""s178: the dispatch wiring of reserved requirement ids (the brief, the story view's gate)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agile_team import gates, system
from agile_team.requirement_ids import BLOCK_SIZE

from .fake_system import Done, FakeSystem
from .test_dispatch import open_story
from .test_s1_gate import write_req

FOLDER = "docs/requirements"
LS_TREE = ("git", "ls-tree", "--name-only")


def names(*numbers: int) -> str:
    return "".join(f"{FOLDER}/REQ-{n:03d}.md\n" for n in numbers)


def prepare(rt, fake: FakeSystem, branches: bool, head: tuple[int, ...] = (1,)):
    """A sprint whose head holds ``head`` and whose design story is s1."""
    fake.reply(LS_TREE, Done(0, ""))
    fake.reply((*LS_TREE, "HEAD"), Done(0, names(*head)))
    rt.state.sprint, rt.state.story_branches = 1, branches
    story = open_story(rt, "design", trace=gates.Trace.CHECKED, base_sha="b" * 40)
    write_req(rt.config.repo, 1, covers='["s1/AC1"]')
    return story


def attach(rt, role: str, story) -> str:
    plan = SimpleNamespace(role=SimpleNamespace(name=role), story=story, prompt="brief")
    rt._attach_requirements(plan)
    return plan.prompt


def test_branch_mode_architect_brief_offers_the_block_and_saves_it(make_runtime, fake) -> None:
    rt = make_runtime()
    story = prepare(rt, fake, branches=True)
    prompt = attach(rt, "architect", story)
    assert story.req_block == 2
    last = 2 + BLOCK_SIZE - 1
    assert f"this story's ids are REQ-002 to REQ-{last:03d}" in prompt
    assert "write REQ-002.md, the next free id" in prompt
    assert rt.state.stories["s1"].req_block == 2


def test_branch_mode_keeps_the_block_on_a_second_brief(make_runtime, fake) -> None:
    rt = make_runtime()
    story = prepare(rt, fake, branches=True)
    attach(rt, "architect", story)
    assert "this story's ids are REQ-002 to" in attach(rt, "architect", story)
    assert story.req_block == 2


def test_two_parallel_architect_briefs_are_offered_different_ids(make_runtime, fake) -> None:
    rt = make_runtime()
    first = prepare(rt, fake, branches=True)
    second = gates.StoryState("s2", "Two", "design", sprint=1, trace=gates.Trace.CHECKED)
    rt.state.stories["s2"] = second
    attach(rt, "architect", first)
    prompt = attach(rt, "architect", second)
    assert second.req_block == first.req_block + BLOCK_SIZE
    assert f"this story's ids are REQ-{second.req_block:03d} to" in prompt


def test_the_retry_brief_after_a_clash_names_an_id_other_work_does_not_hold(
    make_runtime, fake
) -> None:
    rt = make_runtime()
    story = prepare(rt, fake, branches=True)
    other = gates.StoryState(
        "s2", "Two", "design", sprint=1, branch="team/story-s2", base_sha="c" * 40
    )
    rt.state.stories["s2"] = other
    fake.reply((*LS_TREE, "team/story-s2"), Done(0, names(1, 2, 3)))
    story.req_block = 2
    prompt = attach(rt, "architect", story)
    assert story.req_block == 4
    assert "write REQ-004.md, the next free id" in prompt


@pytest.mark.parametrize("role", ["code-reviewer", "customer-proxy"])
def test_reviewer_and_proxy_briefs_reserve_nothing(make_runtime, fake, role: str) -> None:
    rt = make_runtime()
    story = prepare(rt, fake, branches=True)
    prompt = attach(rt, role, story)
    assert story.req_block == 0
    assert "this story's ids" not in prompt


def test_without_story_branches_the_architect_brief_is_the_plain_one(make_runtime, fake) -> None:
    rt = make_runtime()
    story = prepare(rt, fake, branches=False)
    prompt = attach(rt, "architect", story)
    assert story.req_block == 0
    assert "write REQ-002.md, the next free id" in prompt
    assert "this story's ids" not in prompt


def test_the_story_view_design_gate_reports_an_id_the_head_uses(make_runtime, fake) -> None:
    rt = make_runtime()
    story = prepare(rt, fake, branches=True, head=(1, 5))
    view = rt.get_story_view(story)
    folder = view.config.requirements_dir
    system.make_dirs(folder)
    system.write_text(folder / "REQ-005.md", "x\n")
    lines = view.pipeline.checks.clashed("s1")
    assert any("REQ-005 is already used on the sprint head" in line for line in lines)


def test_the_story_view_design_gate_names_the_other_story(make_runtime, fake) -> None:
    rt = make_runtime()
    story = prepare(rt, fake, branches=True)
    other = gates.StoryState("s2", "Two", "design", sprint=1, branch="team/story-s2")
    rt.state.stories["s2"] = other
    fake.reply((*LS_TREE, "team/story-s2"), Done(0, names(7)))
    view = rt.get_story_view(story)
    folder = view.config.requirements_dir
    system.make_dirs(folder)
    system.write_text(folder / "REQ-007.md", "x\n")
    lines = view.pipeline.checks.clashed("s1")
    assert any("REQ-007 is already used by s2" in line for line in lines)


def test_the_root_runtime_design_gate_has_no_clash_check(make_runtime, fake) -> None:
    rt = make_runtime()
    prepare(rt, fake, branches=True)
    assert rt.pipeline.checks.clashed("s1") == []
