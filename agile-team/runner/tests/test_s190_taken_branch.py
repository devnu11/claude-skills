"""s190: a story whose fork name is taken by a leftover branch is adopted or held (T1-T7)."""

from __future__ import annotations

import asyncio

from agile_team import handover
from agile_team.config import Config
from agile_team.dispatch import StepRequest
from agile_team.events import EventKind
from agile_team.gates import StoryState
from agile_team.git_ops import Git

from .fake_system import FAKE_REPO, Done, FakeSystem
from .late import Late

HEAD = "a" * 40
TIP = "b" * 40
NAME = "team/story-s1"
VERIFY = ("rev-parse", "--verify", "--quiet")

sb = Late("story_branches")
ws = Late("workspaces")


def taken(tip: str = TIP, base: str = HEAD):
    return sb.TakenBranch("s1", NAME, tip, base)


def space():
    return ws.Workspaces(Git(FAKE_REPO), Config(repo=FAKE_REPO))


def fresh() -> StoryState:
    return StoryState(id="s1", title="t", step="design")


def argvs(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands]


def has(fake: FakeSystem, *words: str) -> bool:
    return any(all(w in argv for w in words) for argv in argvs(fake))


def branch_events(rt) -> list:
    return [e for e in rt.events.events() if e.kind == EventKind.STORY_BRANCH]


def at_head(fake: FakeSystem, tip: str | None) -> None:
    """Script the local branch: ``tip`` is its sha, None means no such branch."""
    fake.reply(("rev-parse", "HEAD"), Done(0, HEAD + "\n"))
    fake.reply(VERIFY, Done(1) if tip is None else Done(0, tip + "\n"))


# ---------- TakenBranch ----------


def test_is_at_base_only_for_an_equal_sha() -> None:
    assert taken(tip=HEAD).is_at_base
    assert not taken(tip=TIP).is_at_base
    assert not taken(tip=HEAD[:12]).is_at_base


def test_the_aside_branch_carries_twelve_characters_of_the_tip() -> None:
    assert taken().aside_branch == f"{NAME}-kept-{TIP[:12]}"


def test_the_reason_names_story_branch_tip_base_and_the_way_out() -> None:
    reason = taken().reason
    for part in ("s1", NAME, TIP[:12], HEAD[:12], "continue_story(s1)"):
        assert part in reason
    assert f"git branch -m {NAME} {NAME}-kept-{TIP[:12]}" in reason
    assert TIP[:13] not in reason and HEAD[:13] not in reason


def test_the_event_data_has_five_keys_with_full_shas() -> None:
    assert taken().event_data == {
        "action": "taken",
        "branch": NAME,
        "tip": TIP,
        "base_sha": HEAD,
        "aside": f"{NAME}-kept-{TIP[:12]}",
    }


def test_the_branch_actions_are_named() -> None:
    assert [a.value for a in sb.BranchAction] == ["created", "rebuilt", "adopted", "taken"]


# ---------- find_taken_branch (T1) ----------


def test_a_story_with_a_branch_record_is_never_checked(fake: FakeSystem) -> None:
    story = StoryState(id="s1", title="t", step="design", branch=NAME, base_sha=HEAD)
    assert space().find_taken_branch(story, HEAD) is None
    assert not has(fake, "--verify")


def test_a_free_name_is_not_taken(fake: FakeSystem) -> None:
    at_head(fake, None)
    assert space().find_taken_branch(fresh(), HEAD) is None
    assert has(fake, *VERIFY, f"refs/heads/{NAME}")


def test_an_existing_name_is_taken_with_its_stripped_tip(fake: FakeSystem) -> None:
    at_head(fake, TIP)
    assert space().find_taken_branch(fresh(), HEAD) == taken()


def test_the_name_follows_replays(fake: FakeSystem) -> None:
    at_head(fake, TIP)
    story = StoryState(id="s1", title="t", step="design", replays=1)
    found = space().find_taken_branch(story, HEAD)
    assert found is not None and found.branch == f"{NAME}-r1"
    assert has(fake, f"refs/heads/{NAME}-r1")


# ---------- describe_branch_start (T2) ----------


def test_a_record_describes_a_rebuild(fake: FakeSystem) -> None:
    story = StoryState(id="s1", title="t", step="design", branch=NAME, base_sha=HEAD)
    assert space().describe_branch_start(story, HEAD) == {"action": "rebuilt"}


def test_a_free_name_describes_a_creation(fake: FakeSystem) -> None:
    at_head(fake, None)
    assert space().describe_branch_start(fresh(), HEAD) == {"action": "created"}


def test_a_taken_name_describes_an_adoption_with_why(fake: FakeSystem) -> None:
    at_head(fake, HEAD)
    got = space().describe_branch_start(fresh(), HEAD)
    assert got == {"action": "adopted", "why": ws.ADOPTED_WHY}


# ---------- _fork through ensure (T2) ----------


def test_a_free_name_is_forked_at_the_sprint_head(fake: FakeSystem) -> None:
    at_head(fake, None)
    story = fresh()
    space().ensure(story, HEAD)
    assert has(fake, "branch", NAME, HEAD)
    assert story.branch == NAME and story.base_sha == HEAD


def test_a_name_at_the_sprint_head_is_adopted_without_git_branch(fake: FakeSystem) -> None:
    at_head(fake, HEAD)
    story = fresh()
    space().ensure(story, HEAD)
    assert not [
        a
        for a in argvs(fake)
        if "branch" in a
        and "worktree" not in a
        and "-m" not in a
        and "--verify" not in a
        and "symbolic-ref" not in a
    ]
    assert has(fake, "worktree", "add", NAME)
    assert story.branch == NAME and story.base_sha == HEAD


# ---------- prepare_story (T3, T2, T7) ----------


def test_a_name_taken_elsewhere_is_refused_and_nothing_changes(make_runtime, fake) -> None:
    rt = make_runtime()
    at_head(fake, TIP)
    story = fresh()
    refusal = rt.prepare_story(story)
    assert refusal == {"status": "refused", "reason": taken().reason}
    assert not has(fake, "worktree", "add")
    assert not [a for a in argvs(fake) if "branch" in a and NAME in a and "--verify" not in a]
    assert (story.branch, story.base_sha, story.worktree_head) == ("", "", "")
    [event] = branch_events(rt)
    assert event.data == taken().event_data


def test_a_name_at_the_sprint_head_is_adopted_with_an_event(make_runtime, fake) -> None:
    rt = make_runtime()
    at_head(fake, HEAD)
    story = fresh()
    assert rt.prepare_story(story) is None
    [event] = branch_events(rt)
    assert event.data["action"] == "adopted" and event.data["why"] == ws.ADOPTED_WHY
    assert event.data["branch"] == NAME and event.data["base_sha"] == HEAD
    assert story.branch == NAME


def test_a_free_name_is_created_with_an_event(make_runtime, fake) -> None:
    rt = make_runtime()
    at_head(fake, None)
    assert rt.prepare_story(fresh()) is None
    [event] = branch_events(rt)
    assert event.data["action"] == "created" and "why" not in event.data


# ---------- hand-over and continue_story (T3, T6, AC2) ----------


def test_run_in_worktree_puts_the_role_on_the_refusal(make_runtime, fake) -> None:
    rt = make_runtime()
    at_head(fake, TIP)
    story = fresh()
    request = StepRequest("tests", "", story.id)
    report = asyncio.run(rt.run_in_worktree(request, story))
    assert report["status"] == "refused" and report["role"] == "tests"
    [line] = handover.report_lines(report, "s1")
    assert line == f"s1: tests was refused: {taken().reason}"


def test_after_the_way_out_continue_story_lets_the_next_step_fork(make_runtime, fake) -> None:
    from agile_team.po_tools import Tools

    rt = make_runtime()
    at_head(fake, TIP)
    story = fresh()
    assert rt.prepare_story(story)["status"] == "refused"
    rt.state.stories["s1"] = story
    story.hold = "refused"
    asyncio.run(Tools(rt).continue_story({"story": "s1"}))
    assert story.hold is None
    at_head(fake, None)  # the human renamed the leftover
    assert rt.prepare_story(story) is None
    assert branch_events(rt)[-1].data["action"] == "created"


def test_without_the_way_out_the_refusal_repeats(make_runtime, fake) -> None:
    rt = make_runtime()
    at_head(fake, TIP)
    story = fresh()
    first, second = rt.prepare_story(story), rt.prepare_story(story)
    assert first == second and first["status"] == "refused"
    assert [e.data["action"] for e in branch_events(rt)] == ["taken", "taken"]
