"""s115: the ops-review brief section and the Tooling record, through the runtime."""

import functools

from agile_team import story_spec, system
from agile_team.config import STORIES_DIR

from .conftest import FakeQuery, handoff, write_story
from .test_dispatch import open_story, run

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
    rt, q = start(make_runtime, step="implement")
    run(rt, "devops", story="s1")
    assert not q.calls or "## Ops review" not in q.calls[0]["prompt"]


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
