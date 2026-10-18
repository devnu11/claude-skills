"""s159: the pure modules: story_branches, budget_reserve, kept_sessions, switchover."""

from __future__ import annotations

import pytest
from agile_team.gates import StoryState
from agile_team.ledger import Entry
from agile_team.roles import ResolvedRole

from .lazy import Lazy

br = Lazy("agile_team.budget_reserve")
ks = Lazy("agile_team.kept_sessions")
sb = Lazy("agile_team.story_branches")
switchover = Lazy("agile_team.switchover")

# ---------- story_branches (section 3) ----------


def test_story_branch_names_the_replay_only_after_a_replay() -> None:
    """s159 spec: story branch names the replay only after a replay."""
    assert sb.story_branch("team/story-", "s1", 0) == "team/story-s1"
    assert sb.story_branch("team/story-", "s1", 2) == "team/story-s1-r2"


def test_landing_branch_has_the_land_suffix() -> None:
    """s159 spec: landing branch has the land suffix."""
    assert sb.landing_branch("team/story-", "s1") == "team/story-s1-land"
    assert sb.LAND_SUFFIX == "-land"


def test_merge_subject_round_trips_through_merge_id() -> None:
    """s159 spec: merge subject round trips through merge id."""
    subject = sb.merge_subject("s159", "Story branches")
    assert subject == "merge(s159): Story branches"
    assert sb.merge_id(subject) == "s159"


def test_merge_id_is_none_for_other_subjects() -> None:
    """s159 spec: merge id is none for other subjects."""
    assert sb.merge_id("fix(s1): thing") is None
    assert sb.merge_id("") is None


def test_data_classes_default() -> None:
    """s159 spec: data classes default."""
    assert sb.Landed("m").pushed == "" and sb.Landed("m").pr is None
    kept = sb.KeptSession("sid", "opus", "high", "anthropic")
    assert kept.reported == 0.0
    assert sb.StoryCi("a", "green", "pr").source == "pr"
    rebase = sb.StoryRebase("o", "b", "old", "br", ["f"], "devops")
    assert rebase.role == "devops"


def test_story_state_has_the_new_fields_defaulted() -> None:
    """s159 spec: story state has the new fields defaulted."""
    story = StoryState(id="s1", title="t", step="design")
    assert (story.branch, story.base_sha, story.replays, story.pushed) == ("", "", 0, "")
    assert (story.pr, story.landed, story.worktree_head) == (None, None, "")
    assert story.drift == [] and story.sessions == {} and story.land_reran == []
    assert story.in_flight is None and story.ci is None and story.rebase is None


# ---------- budget_reserve (C4, AC12.1) ----------


def entry(cost: float, role="developer", model="opus", **kw) -> Entry:
    return Entry(role=role, model=model, cost_usd=cost, **kw)


def test_min_steps_is_five() -> None:
    """s159 spec: min steps is five."""
    assert br.RESERVE_MIN_STEPS == 5


def test_reserve_is_the_floor_with_fewer_than_five_entries() -> None:
    """s159 spec: reserve is the floor with fewer than five entries."""
    entries = [entry(10.0) for _ in range(4)]
    assert br.reserve(entries, br.Who("developer", "opus", 1.0)) == 1.0


def test_reserve_is_mean_plus_three_sigma() -> None:
    """s159 spec: reserve is mean plus three sigma."""
    entries = [entry(c) for c in (2.0, 4.0, 2.0, 4.0, 3.0)]
    mean = 3.0
    sigma = (sum((c - mean) ** 2 for c in (2.0, 4.0, 2.0, 4.0, 3.0)) / 5) ** 0.5
    got = br.reserve(entries, br.Who("developer", "opus", 1.0))
    assert got == pytest.approx(mean + 3 * sigma, rel=0.2)
    assert got > mean


def test_reserve_never_falls_below_the_floor() -> None:
    """s159 spec: reserve never falls below the floor."""
    entries = [entry(0.1) for _ in range(6)]
    assert br.reserve(entries, br.Who("developer", "opus", 1.0)) == 1.0


def test_reserve_ignores_resumed_estimated_and_other_roles() -> None:
    """s159 spec: reserve ignores resumed estimated and other roles."""
    noise = [
        entry(50.0, resumed=True),
        entry(50.0, estimated=True),
        entry(50.0, role="architect"),
        entry(50.0, model="haiku"),
    ]
    fresh = [entry(1.0) for _ in range(4)]
    assert br.reserve(noise + fresh, br.Who("developer", "opus", 2.0)) == 2.0


def test_start_refusal_at_the_edge() -> None:
    """s159 spec: start refusal at the edge."""
    assert br.start_refusal(br.Headroom(8.0, 10.0), [1.0, 1.0]) is not None
    assert br.start_refusal(br.Headroom(8.0, 10.0), [1.0]) is not None
    assert br.start_refusal(br.Headroom(7.9, 10.0), [1.0, 1.0]) is None
    assert br.start_refusal(br.Headroom(0.0, 10.0), []) is None


# ---------- kept_sessions (K1 to K3) ----------


def role(model="opus", effort="high", provider="anthropic") -> ResolvedRole:
    return ResolvedRole(name="developer", body="", model=model, effort=effort, provider=provider)


def story_with_session() -> StoryState:
    story = StoryState(id="s1", title="t", step="implement")
    story.sessions["developer"] = sb.KeptSession("sid", "opus", "high", "anthropic")
    story.sessions["architect"] = sb.KeptSession("aid", "opus", "high", "anthropic")
    return story


def test_resume_when_model_effort_and_provider_match() -> None:
    """s159 spec: resume when model effort and provider match."""
    assert ks.resume_of(story_with_session(), role()) == "sid"


@pytest.mark.parametrize("kw", [{"model": "haiku"}, {"effort": "low"}, {"provider": "other"}])
def test_no_resume_when_anything_differs(kw) -> None:
    """s159 spec: no resume when anything differs."""
    assert ks.resume_of(story_with_session(), role(**kw)) is None


def test_no_resume_without_a_kept_session() -> None:
    """s159 spec: no resume without a kept session."""
    assert ks.resume_of(StoryState(id="s1", title="t", step="x"), role()) is None


def test_drop_all_and_drop_role() -> None:
    """s159 spec: drop all and drop role."""
    story = story_with_session()
    ks.drop_role(story, "developer")
    assert list(story.sessions) == ["architect"]
    ks.drop_role(story, "missing")
    ks.drop_all(story)
    assert story.sessions == {}


@pytest.mark.parametrize(
    "text", ["prompt is too long", "context window exceeded", "Context length limit"]
)
def test_context_exceeded_patterns(text) -> None:
    """s159 spec: context exceeded patterns."""
    assert ks.context_exceeded(text)


def test_context_not_exceeded_for_other_errors() -> None:
    """s159 spec: context not exceeded for other errors."""
    assert not ks.context_exceeded("connection reset")
    assert ks.CONTEXT_PATTERNS


# ---------- switchover (W1) ----------


def facts(**kw) -> switchover.SwitchFacts:
    base = dict(past_design=[], pending_ids=[], stack=0, ahead=0)
    return switchover.SwitchFacts(**{**base, **kw})


def test_a_clean_switch_has_no_refusals() -> None:
    """s159 spec: a clean switch has no refusals."""
    assert switchover.refusals(facts()) == []


def test_every_reason_is_listed_together() -> None:
    """s159 spec: every reason is listed together."""
    got = switchover.refusals(facts(past_design=["s1"], pending_ids=["s2"], stack=1, ahead=3))
    assert len(got) == 4
    assert "s1" in got[0] and "s2" in got[1]


def test_each_reason_alone() -> None:
    """s159 spec: each reason alone."""
    assert len(switchover.refusals(facts(past_design=["s1"]))) == 1
    assert len(switchover.refusals(facts(pending_ids=["s1"]))) == 1
    assert len(switchover.refusals(facts(stack=2))) == 1
    assert len(switchover.refusals(facts(ahead=1))) == 1
