"""s124: the pure helpers of revert_log, reverts and sprint_end, and the Git methods' argv."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import revert_log, reverts, sprint_end
from agile_team.events import Event, EventKind
from agile_team.gates import StoryState, StoryStatus
from agile_team.git_ops import Git, GitError
from agile_team.revert_log import RevertEntry

from .fake_system import Done, FakeSystem

SHA = "a" * 40
ENTRY = RevertEntry("2026-10-14", 2, "bad", [SHA, "b" * 40], "c" * 40, "d" * 40)


def test_short_and_file_line() -> None:
    assert revert_log.short(SHA) == "a" * 12
    assert revert_log.file_line(ENTRY) == (
        f"- 2026-10-14, sprint 2: bad Reverted commits: {'a' * 12}, {'b' * 12}. "
        f"Revert commit: {'c' * 12}."
    )


def test_with_entry_adds_the_heading_once() -> None:
    first = revert_log.with_entry("---\nid: s1\n---\nbody", ENTRY)
    assert first.startswith("---\nid: s1\n---\nbody\n\n## Reverted\n\n- 2026-10-14")
    assert first.endswith("\n")
    second = revert_log.with_entry(first, ENTRY)
    assert second.count("## Reverted") == 1
    assert second.endswith(revert_log.file_line(ENTRY) + "\n")
    assert second.count("- 2026-10-14") == 2


def test_brief_section() -> None:
    assert revert_log.brief_section([], "design") == ""
    text = revert_log.brief_section([ENTRY, ENTRY], "implement")
    assert text.startswith("## Reverted\n\nThis story was reverted 2× and starts again.")  # noqa: RUF001
    assert "Latest: 2026-10-14, sprint 2: bad" in text
    assert "REDESIGN" not in text and "After revert" not in text
    assert revert_log.brief_section([ENTRY], "design").endswith(
        revert_log.REDESIGN_LINE.format(count=1)
    )


@pytest.mark.parametrize(
    ("text", "count", "ok"),
    [
        ("## After revert 1\n", 1, True),
        ("x\n##  after REVERT 2 \n", 2, True),
        ("## After revert 1\n", 2, False),
        ("## After revert 12\n", 1, False),
        ("text ## After revert 1\n", 1, False),
        ("", 1, False),
    ],
)
def test_after_heading(text: str, count: int, ok: bool) -> None:
    assert revert_log.after_heading(text, count) is ok


def test_pr_and_design_file() -> None:
    line = revert_log.pr_line("s1: T", ENTRY)
    assert line == f"- s1: T: bad (reverted {'a' * 12}, {'b' * 12}; revert {'c' * 12})"
    assert revert_log.pr_section([]) == ""
    assert revert_log.pr_section([line]) == f"Reverted:\n{line}\n\n"
    assert revert_log.design_file("docs/", "s1") == "docs/design/s1.md"
    assert revert_log.design_file("docs", "s1") == "docs/design/s1.md"


def test_story_commits() -> None:
    log = [
        ("1", "feat(s1): T"),
        ("2", "feat(s2): U"),
        ("3", "fixup! feat(s1): T"),
        ("4", "feat(s1): T!"),
    ]
    assert reverts.story_commits(log, "feat(s1): T") == ["1", "3"]
    assert reverts.story_commits([], "x") == []


def test_back_step() -> None:
    steps = ["design", "tests", "implement"]
    assert reverts.back_step(steps, "implement") == "design"
    assert reverts.back_step(steps, "tests") == "design"
    assert reverts.back_step(steps, "design") == "design"
    assert reverts.back_step(["tests", "implement"], "implement") == "tests"
    assert reverts.back_step(["design", "implement"], "implement") == "design"


def test_worked_roles_first_seen_order() -> None:
    events = [
        Event(EventKind.STEP_END, "b", "s1"),
        Event(EventKind.STEP_START, "z", "s1"),
        Event(EventKind.STEP_END, "a", "s1"),
        Event(EventKind.STEP_END, "c", "s2"),
        Event(EventKind.STEP_END, "b", "s1"),
    ]
    assert reverts.worked_roles(events, "s1") == ["b", "a"]


def test_dependents() -> None:
    stories = {
        "s1": StoryState("s1", "t", "design"),
        "s2": StoryState("s2", "t", "design", depends_on=["s1"], commit="x"),
        "s3": StoryState("s3", "t", "design", depends_on=["s1"]),
        "s4": StoryState(
            "s4", "t", "design", depends_on=["s1"], commit="x", status=StoryStatus.DONE
        ),
    }
    assert reverts.dependents(stories, "s1") == ["s2"]


def test_decision() -> None:
    assert reverts.decision(" Revert. ") is reverts.Decision.REVERT
    assert reverts.decision('"KEEP"!') is reverts.Decision.KEEP
    assert reverts.decision("revert it") is reverts.Decision.UNCLEAR


def test_reverted_story_resets_and_keeps() -> None:
    old = StoryState(
        "s1", "T", "implement", rounds=3, commit="x", sprint=1, developer="d", po_developer="p",
        hold="h", code_commits=["x"], test_files=["t"], depends_on=["s0"],
    )  # fmt: skip
    back = reverts.Back("design", ENTRY, ["architect"])
    new = reverts.reverted_story(old, back)
    assert (new.id, new.title, new.depends_on, new.developer, new.po_developer) == (
        "s1", "T", ["s0"], "d", "p",
    )  # fmt: skip
    assert (new.step, new.sprint, new.commit, new.rounds, new.hold) == (
        "design",
        None,
        None,
        0,
        None,
    )
    assert new.code_commits == [] and new.test_files == []
    assert new.reverted == [ENTRY] and new.revert_owed == ["architect"]
    again = reverts.reverted_story(new, back)
    assert again.reverted == [ENTRY, ENTRY]


def test_ready_lines() -> None:
    stories = {f"s{n}": StoryState(f"s{n}", f"T{n}", "design") for n in range(1, 8)}
    ids = list(stories)
    lines = sprint_end.ready_lines(stories, ids[:2])
    assert lines == [sprint_end.READY_HEAD, "- s1: T1", "- s2: T2", sprint_end.READY_ADVICE]
    more = sprint_end.ready_lines(stories, ids)
    assert more[1:6] == [f"- s{n}: T{n}" for n in range(1, 6)]
    assert more[6] == "- and 2 more" and more[-1] == sprint_end.READY_ADVICE
    assert sprint_end.READY_SHOWN == 5


# ----- Git methods --------------------------------------------------------------------


def argvs(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [c.argv for c in fake.commands if c.argv[:1] == ("git",)]


def test_is_ancestor(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base"), Done(0), Done(1))
    git = Git(repo)
    assert git.is_ancestor(SHA) is True and git.is_ancestor(SHA) is False
    assert ("git", "merge-base", "--is-ancestor", SHA, "HEAD") in argvs(fake)


def test_log_from_gives_first_then_the_rest(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "log", "-1"), Done(0, "feat(s1): T\n"))
    fake.reply(("git", "log", "--reverse"), Done(0, f"{'b' * 40}\x1ffix\n{'c' * 40}\x1fmore\n"))
    got = Git(repo).log_from(SHA)
    assert got == [(SHA, "feat(s1): T"), ("b" * 40, "fix"), ("c" * 40, "more")]
    assert any("--reverse" in a and f"{SHA}..HEAD" in a for a in argvs(fake))


def test_revert_all_makes_one_commit(repo: Path, fake: FakeSystem) -> None:
    sha = Git(repo).revert_all(["3", "2", "1"], "revert(s1): T")
    git = argvs(fake)
    assert ("git", "reset", "-q") in git
    assert ("git", "revert", "--no-commit", "3", "2", "1") in git
    (commit,) = [a for a in git if a[1:2] == ("commit",)]
    assert (
        commit[-2] == "-m"
        and commit[-1].startswith("revert(s1): T")
        and "Co-Authored-By" in commit[-1]
    )
    assert sha == Git(repo).head()


def test_revert_all_aborts_on_conflict(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "revert", "--no-commit"), Done(1, "", "boom"))
    fake.reply(("git", "diff", "--name-only", "--diff-filter=U"), Done(0, "a.py\nb.py\n"))
    with pytest.raises(GitError, match=r"a\.py"):
        Git(repo).revert_all(["2", "1"], "m")
    git = argvs(fake)
    assert ("git", "revert", "--abort") in git
    assert not any(a[1:2] == ("commit",) for a in git)
