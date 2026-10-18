"""s159: the pure branch-name helpers and the story-state records (section 3)."""

import dataclasses

from agile_team import story_branches as sb
from agile_team.gates import StoryState


def test_story_branch_without_replays_r1() -> None:
    assert sb.story_branch("team/story-", "s9", 0) == "team/story-s9"


def test_story_branch_after_replays_r1() -> None:
    assert sb.story_branch("team/story-", "s9", 2) == "team/story-s9-r2"


def test_landing_branch_r1() -> None:
    assert sb.landing_branch("team/story-", "s9") == "team/story-s9-land"


def test_merge_subject_and_id_round_trip_r1() -> None:
    subject = sb.merge_subject("s9", "Do a thing: well")
    assert subject == "merge(s9): Do a thing: well"
    assert sb.merge_id(subject) == "s9"


def test_merge_id_of_a_plain_subject_is_none_r1() -> None:
    assert sb.merge_id("feat: merge(s9) later") is None
    assert sb.merge_id("") is None


def test_records_default_r1() -> None:
    assert sb.Landed("m") == sb.Landed("m", "", None)
    session = sb.KeptSession("sess", "opus", "high", "anthropic")
    assert session.reported == 0.0
    rebase = sb.StoryRebase("o", "b", "old", "br", ["f"], "devops")
    assert rebase.role == "devops" and rebase.files == ["f"]
    assert sb.StoryCi("a" * 40, "green", "pr").source == "pr"


def test_story_state_new_fields_default_r1() -> None:
    story = StoryState(id="s1", title="t", step="design")
    assert (story.branch, story.base_sha, story.pushed, story.worktree_head) == ("", "", "", "")
    assert (story.replays, story.pr, story.landed, story.in_flight) == (0, None, None, None)
    assert (story.ci, story.rebase) == (None, None)
    assert story.drift == [] and story.land_reran == [] and story.sessions == {}


def test_story_state_new_fields_are_separate_per_story_r1() -> None:
    a = StoryState(id="a", title="t", step="design")
    b = StoryState(id="b", title="t", step="design")
    a.drift.append("x")
    a.sessions["dev"] = sb.KeptSession("s", "m", "e", "p")
    assert b.drift == [] and b.sessions == {}
    assert "sessions" in {f.name for f in dataclasses.fields(StoryState)}
