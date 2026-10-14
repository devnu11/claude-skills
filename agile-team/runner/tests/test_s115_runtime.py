"""s115: the ops-review brief section and the Tooling record, through the runtime."""

import functools
from types import SimpleNamespace

from agile_team import story_spec, system
from agile_team.config import STORIES_DIR

from .conftest import FakeQuery, handoff, write_story
from .test_dispatch import open_story, run
from .test_s45 import manager, manager_rt, repeated_story

AUTO = {"ac": "AC1", "verdict": "automatic", "how": "pytest"}
OTHER = {"ac": "AC1", "verdict": "automatic", "how": "a different check"}


def start(make_runtime, step="ops-review", **kw):
    q = FakeQuery(text=handoff("done", tooling=[AUTO]))
    rt = make_runtime(q)
    open_story(rt, step)
    write_story(rt.config, "s1", "cli")
    rt.pipeline.checks.story_spec = functools.partial(story_spec.read, rt.config)
    return rt, q


def test_devops_at_ops_review_gets_the_section(make_runtime) -> None:
    rt, q = start(make_runtime)
    run(rt, "devops", story="s1")
    prompt = q.calls[0]["prompt"]
    assert "## Ops review" in prompt and "| AC1 | cli | criterion 1 |" in prompt


def test_storyless_devops_gets_no_section(make_runtime) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    run(rt, "devops")
    assert "## Ops review" not in q.calls[0]["prompt"]


def test_devops_on_another_step_gets_no_section(make_runtime) -> None:
    rt, _q = start(make_runtime, step="implement")
    plan = SimpleNamespace(story=rt.state.stories["s1"], prompt="brief")
    rt._attach_ops_review(plan)
    assert plan.prompt == "brief"


def test_a_gate_fix_step_gets_no_section(make_runtime) -> None:
    rt, _q = start(make_runtime, step="ops-review")
    plan = SimpleNamespace(story=rt.state.stories["s1"], prompt="brief")
    plan.story.step = "tests"
    rt._attach_ops_review(plan)
    assert plan.prompt == "brief"


def test_the_commit_holds_only_the_story_file_with_its_subject(make_runtime, fake) -> None:
    rt, _q = start(make_runtime)
    fake.track()
    report = run(rt, "devops", story="s1")
    assert report["gate"]["tooling"]["commit"]
    commit = next(c for c in fake.tree.commits if "tooling review" in c.subject())
    assert commit.subject() == "chore(s1): record the tooling review in the story file"
    assert commit.paths() == {f"{STORIES_DIR}/s1.md"}


def test_an_unfiled_missing_row_holds_through_gate_hold(make_runtime) -> None:
    rt, q = start(make_runtime)
    q.text = handoff("done", tooling=[{**AUTO, "verdict": "missing", "needs": "a harness"}])
    report = run(rt, "devops", story="s1")
    story = rt.state.stories["s1"]
    assert report["gate"]["verdict"] == "hold" and story.hold == "gate_hold"
    assert story.step == "ops-review"


def test_a_devops_fault_is_off_pipeline_and_stays_off_ops_review(make_runtime) -> None:
    rt = manager_rt(make_runtime, fault="devops")
    story = repeated_story(rt)
    report = manager(rt)
    assert report["fault"]["kind"] == "off_pipeline"
    assert story.step == "tests"


def test_a_story_past_design_stays_put_at_start(make_runtime) -> None:
    rt, _q = start(make_runtime, step="tests")
    rt.state.begin_sprint(["s1"])
    assert rt.state.stories["s1"].step == "tests"


def test_pass_writes_the_tooling_section_and_commits_it(make_runtime) -> None:
    rt, _q = start(make_runtime)
    report = run(rt, "devops", story="s1")
    file = f"{STORIES_DIR}/s1.md"
    text = system.read_text(rt.config.repo / file)
    assert "## Tooling" in text and "- AC1: automatic today: pytest" in text
    assert report["gate"]["tooling"]["file"] == file
    assert report["gate"]["tooling"]["commit"]
    assert rt.state.stories["s1"].step == "tests"


def test_identical_rows_do_not_commit_again(make_runtime) -> None:
    rt, _q = start(make_runtime)
    run(rt, "devops", story="s1")
    rt.state.stories["s1"].step = "ops-review"
    report = run(rt, "devops", story="s1")
    assert report["gate"]["tooling"]["commit"] is None


def test_second_pass_replaces_the_section(make_runtime) -> None:
    rt, q = start(make_runtime)
    run(rt, "devops", story="s1")
    q.text = handoff("done", tooling=[OTHER])
    rt.state.stories["s1"].step = "ops-review"
    run(rt, "devops", story="s1")
    text = system.read_text(rt.config.repo / STORIES_DIR / "s1.md")
    assert text.count("## Tooling") == 1 and "a different check" in text
    assert "pytest" not in text.split("## Tooling")[1]
