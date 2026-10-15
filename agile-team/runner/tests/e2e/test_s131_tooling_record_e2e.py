"""s131 e2e: the driver commits the Tooling record before the story advances (AC1-AC3)."""

from __future__ import annotations

import functools

from agile_team import config as config_mod
from agile_team import ops_review, story_spec
from agile_team.dispatch import RECORD_FAILED
from agile_team.git_ops import GitError

from ..conftest import handoff, write_story
from ..pipeline_helpers import Script, add_story, build, drive

AUTO = {"ac": "AC1", "verdict": "automatic", "how": "pytest tests/e2e"}
SUBJECT = ops_review.RECORD_SUBJECT.format(story="s1")
ERROR = "git commit: fatal: index.lock exists"


def world(make_runtime, fake):
    script = Script({"devops": [handoff("done", tooling=[AUTO])]})
    steps = config_mod.pipeline_steps(["design", "tests", "implement", "review"])
    rt = build(make_runtime, script, steps=steps)
    add_story(rt)
    write_story(rt.config, "s1", "cli")
    rt.pipeline.checks.story_spec = functools.partial(story_spec.read, rt.config)
    return rt


def wrap_commit(rt, hook):
    real = rt.git.commit

    def commit(paths, message):
        if message.startswith(SUBJECT):
            hook()
        return real(paths, message)

    rt.git.commit = commit


def test_the_record_is_committed_while_the_story_is_at_ops_review(make_runtime, fake) -> None:
    """AC1: through the driver, the commit happens before the step moves."""
    rt = world(make_runtime, fake)
    seen = []
    wrap_commit(rt, lambda: seen.append(rt.state.stories["s1"].step))
    drive(rt)
    assert seen == ["ops-review"]


def test_a_failed_record_commit_holds_at_ops_review_with_a_clean_tree(make_runtime, fake) -> None:
    """AC2: the story stays, the file is restored, the event names the failure."""
    rt = world(make_runtime, fake)
    path = rt.config.repo / ".team" / "stories" / "s1.md"
    before = path.read_text()

    def boom():
        raise GitError(ERROR)

    wrap_commit(rt, boom)
    drive(rt)
    story = rt.state.stories["s1"]
    assert story.step == "ops-review" and story.hold == "gate_hold" and story.rounds == 0
    assert path.read_text() == before and rt.git.is_clean()
    reason = RECORD_FAILED.format(step="ops-review", error=GitError(ERROR))
    gates = [e for e in rt.events.events() if e.kind == "gate"]
    assert any(reason in str(e) for e in gates)
