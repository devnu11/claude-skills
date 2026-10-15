"""s131: the Tooling record is committed before the story advances; a failed commit holds."""

from agile_team import ops_review, system
from agile_team.config import STORIES_DIR
from agile_team.dispatch import RECORD_FAILED
from agile_team.git_ops import GitError

from .conftest import handoff
from .test_dispatch import run
from .test_s115_runtime import AUTO, start

SUBJECT = ops_review.RECORD_SUBJECT.format(story="s1")
ERROR = "git commit: fatal: index.lock exists"


def fail_tooling_commit(rt, fake, staged=False) -> None:
    """Make only the Tooling commit raise; optionally stage the path first."""
    real = rt.git.commit

    def commit(paths, message):
        if not message.startswith(SUBJECT):
            return real(paths, message)
        if staged:
            rt.git.run("add", "-A", "--", *paths)
        raise GitError(ERROR)

    rt.git.commit = commit


def failing_run(make_runtime, fake, staged=False):
    rt, q = start(make_runtime)
    fake.track()
    fail_tooling_commit(rt, fake, staged)
    file = rt.config.repo / STORIES_DIR / "s1.md"
    before = system.read_text(file)
    return rt, q, file, before, run(rt, "devops", story="s1")


def test_the_record_is_committed_while_the_story_is_still_at_ops_review(make_runtime, fake) -> None:
    rt, _q = start(make_runtime)
    fake.track()
    seen = []
    real = rt.git.commit

    def commit(paths, message):
        if message.startswith(SUBJECT):
            seen.append(rt.state.stories["s1"].step)
        return real(paths, message)

    rt.git.commit = commit
    run(rt, "devops", story="s1")
    assert seen == ["ops-review"]
    assert rt.state.stories["s1"].step == "tests"


def test_the_record_commit_exists_before_the_story_is_advanced(make_runtime, fake) -> None:
    rt, _q = start(make_runtime)
    tree = fake.track()
    subjects = []
    real = rt._advance_and_log

    def advance(plan, outcome):
        subjects.append(tree.commits[-1].subject())
        return real(plan, outcome)

    rt._advance_and_log = advance
    run(rt, "devops", story="s1")
    assert subjects and subjects[0].startswith(SUBJECT)


def test_a_failed_record_commit_holds_the_gate(make_runtime, fake) -> None:
    rt, _q, _file, _before, report = failing_run(make_runtime, fake)
    story = rt.state.stories["s1"]
    assert report["gate"]["verdict"] == "hold"
    assert story.step == "ops-review" and story.rounds == 0
    assert "tooling" not in report["gate"]
    reason = RECORD_FAILED.format(step="ops-review", error=GitError(ERROR))
    assert report["gate"]["reason"] == reason and "index.lock" in reason


def test_a_failed_record_commit_leaves_the_tree_clean(make_runtime, fake) -> None:
    rt, _q, file, before, _report = failing_run(make_runtime, fake)
    assert system.read_text(file) == before
    assert rt.git.is_clean()


def test_a_failed_record_commit_after_staging_leaves_the_tree_clean(make_runtime, fake) -> None:
    rt, _q, file, before, _report = failing_run(make_runtime, fake, staged=True)
    assert system.read_text(file) == before
    assert rt.git.is_clean()


def test_a_failed_record_commit_hands_over_as_gate_hold(make_runtime, fake) -> None:
    rt, _q, _file, _before, _report = failing_run(make_runtime, fake)
    assert rt.state.stories["s1"].hold == "gate_hold"


def test_a_failing_reset_does_not_mask_the_commit_error(make_runtime, fake) -> None:
    rt, _q = start(make_runtime)
    fake.track()
    fail_tooling_commit(rt, fake)
    real = rt.git.attempt
    rt.git.attempt = lambda *a: (1, "reset broke") if a[:1] == ("reset",) else real(*a)
    report = run(rt, "devops", story="s1")
    assert report["gate"]["verdict"] == "hold"
    assert "index.lock" in report["gate"]["reason"]
    assert rt.state.stories["s1"].step == "ops-review"


def test_a_bounce_attempts_no_record_commit(make_runtime, fake) -> None:
    rt, q = start(make_runtime)
    q.text = handoff("done", tooling=[{**AUTO, "verdict": "missing", "needs": "a harness"}])
    tree = fake.track()
    run(rt, "devops", story="s1")
    assert not any(c.subject().startswith(SUBJECT) for c in tree.commits)


def test_unchanged_text_makes_no_second_record_commit(make_runtime, fake) -> None:
    rt, _q = start(make_runtime)
    tree = fake.track()
    run(rt, "devops", story="s1")
    count = sum(c.subject().startswith(SUBJECT) for c in tree.commits)
    rt.state.stories["s1"].step = "ops-review"
    report = run(rt, "devops", story="s1")
    assert report["gate"]["tooling"]["commit"] is None
    assert sum(c.subject().startswith(SUBJECT) for c in tree.commits) == count
