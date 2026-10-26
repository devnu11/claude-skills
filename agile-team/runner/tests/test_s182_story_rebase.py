"""s182: a story rebase's settle adds no commit; the commits check names each commit."""

from __future__ import annotations

import dataclasses
import json

import pytest
from agile_team import gates, guard, story_rebase
from agile_team.gates import StoryState
from agile_team.git_ops import Git
from agile_team.guard import Audit
from agile_team.state import RunState
from agile_team.story_rebase import CommitLists, ListedCommit

from .fake_system import FAKE_HEAD, FAKE_REPO, Done, FakeSystem
from .test_s46 import pipeline, story
from .test_s159_story_ci_rebase import REBASE

OLD_SPAN = f"{REBASE.base}..{REBASE.old}"
NEW_SPAN = f"{REBASE.onto}..HEAD"


def logs(fake: FakeSystem, wanted: list[tuple[str, str]], found: list[tuple[str, str]]) -> None:
    """Script the two ``git log`` spans as ``sha<TAB>subject`` lines."""
    for span, rows in ((OLD_SPAN, wanted), (NEW_SPAN, found)):
        fake.reply(("log", span), Done(0, "".join(f"{s}\t{m}\n" for s, m in rows)))


def reason(fake: FakeSystem, rebase=REBASE) -> str | None:
    return story_rebase._find_changed_commits(Git(FAKE_REPO), rebase)


A, B, C = "a1" * 20, "b2" * 20, "c3" * 20
X, Y = "d4" * 20, "e5" * 20
SHORT = story_rebase.SHA_WIDTH


# ---------- list_commits ----------


def test_list_commits_reads_sha_and_subject_oldest_first(fake: FakeSystem) -> None:
    logs(fake, [(A, "one"), (B, "two: with\ttab")], [])
    got = story_rebase.list_commits(Git(FAKE_REPO), OLD_SPAN)
    assert got == [ListedCommit(A, "one"), ListedCommit(B, "two: with\ttab")]
    (log,) = [c.argv for c in fake.commands if "log" in c.argv]
    assert "--reverse" in log and "--format=%H%x09%s" in log


def test_list_commits_of_an_empty_span_is_empty(fake: FakeSystem) -> None:
    logs(fake, [], [])
    assert story_rebase.list_commits(Git(FAKE_REPO), OLD_SPAN) == []


# ---------- the commits check (AC3, AC4) ----------


def test_equal_subjects_with_other_shas_pass(fake: FakeSystem) -> None:
    logs(fake, [(A, "one"), (B, "two")], [(X, "one"), (Y, "two")])
    assert reason(fake) is None


def test_an_extra_commit_by_the_role_is_listed(fake: FakeSystem) -> None:
    logs(fake, [(A, "one")], [(X, "one"), (Y, "extra thing")])
    lines = reason(fake).splitlines()
    assert lines[0] == story_rebase.COMMITS_CHANGED.format(branch=REBASE.branch, old=REBASE.old)
    assert lines[1:] == [f"- extra {Y[:SHORT]} extra thing (made by the role)"]


def test_an_extra_commit_in_made_is_the_runners(fake: FakeSystem) -> None:
    logs(fake, [(A, "one")], [(X, "one"), (Y, "fixup! one")])
    rebase = dataclasses.replace(REBASE, made=[Y])
    assert reason(fake, rebase).splitlines()[1:] == [
        f"- extra {Y[:SHORT]} fixup! one (made by the runner)"
    ]


def test_a_dropped_commit_is_listed_as_missing_with_the_old_branch(fake: FakeSystem) -> None:
    logs(fake, [(A, "one"), (B, "two")], [(X, "one")])
    assert reason(fake).splitlines()[1:] == [f"- missing {B[:SHORT]} two (on {REBASE.old})"]


def test_a_reworded_commit_is_listed_as_changed(fake: FakeSystem) -> None:
    logs(fake, [(A, "one"), (B, "two")], [(X, "one"), (Y, "two!")])
    assert reason(fake).splitlines()[1:] == [
        f"- changed {B[:SHORT]} two -> {Y[:SHORT]} two! (made by the role)"
    ]


def test_a_reworded_commit_by_the_runner_says_so(fake: FakeSystem) -> None:
    logs(fake, [(A, "one")], [(Y, "uno")])
    rebase = dataclasses.replace(REBASE, made=[Y])
    assert reason(fake, rebase).splitlines()[1].endswith("(made by the runner)")


def test_a_replace_with_more_found_than_wanted_lists_the_rest_as_extra(fake: FakeSystem) -> None:
    logs(fake, [(A, "one")], [(X, "uno"), (Y, "dos")])
    lines = reason(fake).splitlines()[1:]
    assert lines[0].startswith("- changed ") and lines[1].startswith("- extra ")
    assert Y[:SHORT] in lines[1] and len(lines) == 2


def test_a_replace_with_more_wanted_than_found_lists_the_rest_as_missing(fake: FakeSystem) -> None:
    logs(fake, [(A, "one"), (B, "two")], [(X, "uno")])
    lines = reason(fake).splitlines()[1:]
    assert lines[0].startswith("- changed ") and lines[1].startswith("- missing ")
    assert B[:SHORT] in lines[1] and len(lines) == 2


def test_a_reordered_commit_is_one_missing_and_one_extra(fake: FakeSystem) -> None:
    logs(fake, [(A, "one"), (B, "two")], [(X, "two"), (Y, "one")])
    kinds = [line.split()[1] for line in reason(fake).splitlines()[1:]]
    assert sorted(kinds) == ["extra", "missing"]


def test_describe_changed_commits_has_no_lines_for_equal_lists() -> None:
    same = [ListedCommit(A, "one")]
    assert story_rebase.describe_changed_commits(CommitLists(same, same, REBASE)) == []


def test_find_refusal_ends_with_the_named_commits(fake: FakeSystem) -> None:
    fake.reply(("symbolic-ref",), Done(0, REBASE.branch + "\n"))
    fake.reply(("merge-base", "--is-ancestor"), Done(0))
    logs(fake, [(A, "one")], [(X, "one"), (Y, "more")])
    assert f"- extra {Y[:SHORT]} more" in story_rebase.find_refusal(Git(FAKE_REPO), REBASE)


# ---------- is_foldable (R4) ----------


def foldable(fake: FakeSystem) -> None:
    fake.reply(("symbolic-ref",), Done(0, REBASE.branch + "\n"))
    fake.reply(("merge-base", "--is-ancestor"), Done(0))
    fake.reply(("rev-parse", REBASE.onto), Done(0, REBASE.onto + "\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, FAKE_HEAD + "\n"))


def test_a_finished_rebase_with_a_commit_over_onto_is_foldable(fake: FakeSystem) -> None:
    foldable(fake)
    assert story_rebase.is_foldable(Git(FAKE_REPO), REBASE) is True


def test_head_at_onto_is_not_foldable(fake: FakeSystem) -> None:
    foldable(fake)
    fake.reply(("rev-parse", "HEAD"), Done(0, REBASE.onto + "\n"))
    assert story_rebase.is_foldable(Git(FAKE_REPO), REBASE) is False


def test_head_off_the_branch_is_not_foldable(fake: FakeSystem) -> None:
    foldable(fake)
    fake.reply(("symbolic-ref",), Done(0, "elsewhere\n"))
    assert story_rebase.is_foldable(Git(FAKE_REPO), REBASE) is False


def test_head_off_the_base_is_not_foldable(fake: FakeSystem) -> None:
    foldable(fake)
    fake.reply(("merge-base", "--is-ancestor"), Done(1))
    assert story_rebase.is_foldable(Git(FAKE_REPO), REBASE) is False


def test_a_rebase_in_progress_is_not_foldable(fake: FakeSystem, monkeypatch) -> None:
    foldable(fake)
    monkeypatch.setattr(story_rebase, "find_unfinished", lambda git: "rebase in progress")
    assert story_rebase.is_foldable(Git(FAKE_REPO), REBASE) is False


# ---------- add_to_tip (R3) ----------


def test_add_to_tip_amends_with_exactly_the_paths_and_keeps_the_message(fake: FakeSystem) -> None:
    got = story_rebase.add_to_tip(Git(FAKE_REPO), ["a.py", "docs/b.md"])
    argvs = [c.argv[1:] for c in fake.commands if c.argv[:1] == ("git",)]
    assert got == FAKE_HEAD
    (add,) = [a for a in argvs if a[0] == "add"]
    assert add[-2:] == ("a.py", "docs/b.md") and "-A" in add and "--" in add
    (commit,) = [a for a in argvs if a[0] == "commit"]
    assert {"--amend", "--no-edit", "--no-verify"} <= set(commit) and "-m" not in commit
    assert argvs.index(("reset", "-q")) < argvs.index(add) < argvs.index(commit)


# ---------- StoryRebase.made ----------


def test_made_defaults_empty_and_round_trips() -> None:
    assert dataclasses.replace(REBASE).made == []
    st = StoryState("s1", "T", "land", sprint=1)
    st.rebase = dataclasses.replace(REBASE, made=[A])
    state = RunState()
    state.stories["s1"] = st
    assert RunState.from_json(state.to_json()).stories["s1"].rebase.made == [A]


def test_an_old_state_without_made_loads_empty() -> None:
    st = StoryState("s1", "T", "land", sprint=1)
    st.rebase = dataclasses.replace(REBASE)
    state = RunState()
    state.stories["s1"] = st
    data = state.to_json()
    assert "made" in data
    raw = json.loads(data)
    del raw["stories"]["s1"]["rebase"]["made"]
    loaded = RunState.from_json(json.dumps(raw)).stories["s1"].rebase
    assert loaded.made == []


# ---------- guard.set_aside (R2) ----------


def test_set_aside_commits_alone_keeps_a_ref_and_moves_the_branch_back(fake: FakeSystem) -> None:
    git = Git(FAKE_REPO)
    audit = Audit("developer", ["src/a.py"], ["tests/x"])
    sha = guard.set_aside(git, audit)
    argvs = [c.argv[1:] for c in fake.commands if c.argv[:1] == ("git",)]
    assert sha == FAKE_HEAD
    (add,) = [a for a in argvs if a[0] == "add"]
    assert add[-1] == "tests/x" and "src/a.py" not in add
    ref = ("update-ref", guard.SET_ASIDE_REF.format(sha=sha), sha)
    back = ("reset", "-q", "--keep", "HEAD^")
    assert ref in argvs and back in argvs
    assert argvs.index(ref) < argvs.index(back)
    assert not [a for a in argvs if a[0] == "revert"]


def test_the_set_aside_ref_lives_outside_refs_heads() -> None:
    assert guard.SET_ASIDE_REF.format(sha="abc") == "refs/agile-team/set-aside/abc"


# ---------- R7: no advance past a queued rebase ----------


def test_advance_is_refused_while_a_rebase_is_queued() -> None:
    p, _ = pipeline()
    st = story("tests")
    st.rebase = dataclasses.replace(REBASE)
    expected = gates.ADVANCE_REBASE.format(id=st.id, onto=REBASE.onto)
    assert p.ruling_move_refusal(st, "advance") == expected


def test_the_advance_refusal_names_the_story_and_onto() -> None:
    p, _ = pipeline()
    st = story("tests")
    st.rebase = dataclasses.replace(REBASE)
    msg = p.ruling_move_refusal(st, "advance")
    assert st.id in msg and REBASE.onto in msg and "upgrade_model" in msg


def test_the_rebase_refusal_comes_before_the_last_step_one() -> None:
    p, _ = pipeline()
    st = story(p.steps[-1])
    st.rebase = dataclasses.replace(REBASE)
    assert "story rebase" in p.ruling_move_refusal(st, "advance")


@pytest.mark.parametrize("ruling", ["upgrade_model", "rescope", "revise_design", "escalate"])
def test_other_rulings_are_not_refused_by_a_queued_rebase(ruling: str) -> None:
    p, _ = pipeline()
    st = story("tests")
    st.rebase = dataclasses.replace(REBASE)
    assert p.ruling_move_refusal(st, ruling) is None


def test_advance_without_a_queued_rebase_is_unchanged() -> None:
    p, _ = pipeline()
    assert p.ruling_move_refusal(story("tests"), "advance") is None
