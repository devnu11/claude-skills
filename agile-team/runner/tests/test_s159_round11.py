"""s159 round-10 review: D4 (poll read fails), the open PR (AC8.1), S9, GONE_STASH, D1."""

from __future__ import annotations

from agile_team.dispatch import MANAGER
from agile_team.gates import StoryState, StoryStatus
from agile_team.git_ops import Git
from agile_team.router import MANAGER_KEY, Work
from agile_team.salvage import InFlight
from agile_team.upstream import UpstreamError

from .fake_system import FAKE_REPO, Done
from .test_s159_round7 import SHA, rp, story_of
from .test_s159_scheduler import scheduler, story
from .test_s159_story_ci_rebase import HEAD, poller, ready, story_ci

OTHER = "f" * 40


# ---------- D4 (AC8.3) ----------


def test_a_failing_sha_read_is_no_result_and_records_nothing_d4(make_runtime, fake) -> None:
    rt, st, poll = poller(make_runtime, fake)

    def boom(sha: str) -> list:
        raise UpstreamError("gh failed")

    rt.prs.sha_checks = boom  # type: ignore[method-assign]
    assert poll.read_checks(st) == []
    assert poll.poll(st, 1000.0) is None and st.ci is None


# ---------- an open PR is not opened twice (AC8.1) ----------


def test_a_story_with_a_pr_opens_no_second_one_ac8_1(make_runtime, fake) -> None:
    rt, st = ready(make_runtime, fake)
    st.pr = 42
    story_ci.StoryPusher(rt).after_step(st)
    assert [c for c in rt.prs.calls if c[0] == "create"] == []
    assert st.pr == 42 and st.pushed == HEAD


# ---------- S9: save_edits (AC2.13) ----------


def saved(make_runtime, fake, *refs: Done):
    rt = make_runtime()
    st = story_of("s1")
    st.in_flight = InFlight("developer", "s1", "brief", session="sess")
    fake.reply(("rev-parse", "-q", "--verify", "refs/stash"), *refs)
    return rp.StoryReplay(rt).save_edits(Git(FAKE_REPO), st)


def test_a_step_with_nothing_in_flight_stashes_nothing_s9(make_runtime, fake) -> None:
    rt = make_runtime()
    got = rp.StoryReplay(rt).save_edits(Git(FAKE_REPO), story_of("s1"))
    assert got == rp.Stash("s1") and not any("stash" in c.argv for c in fake.commands)


def test_an_unchanged_stash_ref_means_nothing_was_saved_s9(make_runtime, fake) -> None:
    got = saved(make_runtime, fake, Done(0, SHA + "\n"))
    assert got.saved is False and got.sha == SHA
    assert any("stash" in c.argv and "push" in c.argv for c in fake.commands)


def test_a_changed_stash_ref_is_saved_with_the_new_sha_s9(make_runtime, fake) -> None:
    got = saved(make_runtime, fake, Done(0, OTHER + "\n"), Done(0, SHA + "\n"))
    assert got == rp.Stash("s1", True, SHA)


def test_the_first_ever_stash_is_saved_s9(make_runtime, fake) -> None:
    got = saved(make_runtime, fake, Done(1, ""), Done(0, SHA + "\n"))
    assert got == rp.Stash("s1", True, SHA)


# ---------- GONE_STASH (AC2.13) ----------


def test_a_stash_gone_from_the_list_is_not_popped_and_the_po_is_told_n7(
    make_runtime, monkeypatch, fake
) -> None:
    rt = make_runtime()
    st = story_of("s1")
    rt.state.stories["s1"] = st
    posted: list = []
    monkeypatch.setattr(rt.relay, "post", posted.append)
    fake.reply(("stash", "list"), Done(0, f"{OTHER}\n"))
    rp.StoryReplay(rt).restore_edits(Git(FAKE_REPO), rp.Stash("s1", True, SHA))
    assert not any("pop" in c.argv for c in fake.commands)
    assert rp.GONE_STASH.format(sha=SHA) == st.runner_note
    assert [n.text for n in posted] == [st.runner_note]


# ---------- D1: the Manager review beside a story step (AC6.8) ----------


def test_a_running_manager_review_does_not_hold_a_story_step_d1(make_runtime) -> None:
    a = story("s1")
    rt, s = scheduler(make_runtime, a)
    rt.state.story_branches = True
    s.tasks[MANAGER_KEY] = object()  # type: ignore[assignment]
    assert s.can_start(Work("developer-cli", a, "brief")) is None


def test_a_running_story_step_does_not_hold_the_manager_review_d1(make_runtime) -> None:
    a = story("s1")
    rt, s = scheduler(make_runtime, a)
    rt.state.story_branches = True
    s.tasks["s1"] = object()  # type: ignore[assignment]
    assert s.can_start(Work(MANAGER, None, "review")) is None


def test_a_dependency_not_yet_landed_still_blocks_a_story_d1(make_runtime) -> None:
    dep = story("s1", step="land")
    dep.status = StoryStatus.ACTIVE
    a = StoryState(id="s2", title="T", step="implement", sprint=1, depends_on=["s1"])
    _, s = scheduler(make_runtime, dep, a)
    assert "s1" in s.can_start(Work("developer-cli", a, "brief"))
