"""s135: ``agile-team story new|amend`` checks a draft and queues it (Q1-Q5; AC1, AC4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agile_team import cli, system
from agile_team import state as state_mod
from agile_team.gates import StoryState, StoryStatus
from agile_team.state import RunState
from agile_team.story_drafts import LIAISON_AUTHOR, USAGE, Action, Approval

DRAFT = (
    '---\ntitle: "Add todo"\nacceptance:\n'
    '  - id: AC1\n    text: "adds an item"\n    environment: cli\n'
    "---\n\nAs a user, I want to add items.\n"
)
FIELDS = {
    "action",
    "story",
    "approved_by",
    "plan",
    "sprint",
    "after",
    "file",
    "text",
    "at",
}


def put(repo: Path, text: str = DRAFT, name: str = "draft.md") -> str:
    system.write_text(repo / name, text)
    return str(repo / name)


def story_file(repo: Path, sid: str, text: str) -> None:
    system.make_dirs(repo / ".team" / "stories")
    system.write_text(repo / ".team" / "stories" / f"{sid}.md", text)


def with_state(repo: Path, *stories: StoryState) -> None:
    run_dir = repo / ".team" / "run"
    state_mod.save(run_dir, RunState(stories={s.id: s for s in stories}))


def story(sid: str, status: StoryStatus = StoryStatus.ACTIVE) -> StoryState:
    return StoryState(sid, f"title {sid}", "design", status=status)


def run(repo: Path, *args: str) -> int:
    return cli.main(["--repo", str(repo), "story", *args])


def queued(repo: Path) -> list[str]:
    folder = repo / ".team" / "run" / "liaison" / "stories"
    return sorted(p.name for p in system.list_dir(folder)) if system.is_dir(folder) else []


def refusal(capsys) -> list[str]:
    err = capsys.readouterr().err
    assert err.startswith("agile-team story: ")
    return err.removeprefix("agile-team story: ").rstrip("\n").split("\n")


# ----- constants and the command row ------------------------------------------------


def test_usage_text_and_enums() -> None:
    assert USAGE == "story new takes <file.md>; story amend takes <id> <file.md>"
    assert [a.value for a in Action] == ["new", "amend"]
    assert [a.value for a in Approval] == ["human", "none"]
    assert LIAISON_AUTHOR == "Claude (agile-team liaison) <noreply@anthropic.com>"


def test_story_is_a_command_right_after_share() -> None:
    names = [c.name for c in cli.COMMANDS]
    assert names.index("story") == names.index("share") + 1


# ----- story new: queued (AC1) ------------------------------------------------------


def test_a_clean_draft_is_queued_with_every_field(configured: Path, capsys) -> None:
    path = put(configured)
    assert run(configured, "new", path, "--approved-by", "human") == 0
    assert queued(configured) == ["q1.json"]
    raw = json.loads(system.read_text(configured / ".team/run/liaison/stories/q1.json"))
    assert set(raw) == FIELDS
    assert raw["action"] == "new" and raw["story"] == "" and raw["approved_by"] == "human"
    assert raw["plan"] == "" and raw["sprint"] == "backlog" and raw["after"] == ""
    assert raw["file"] == path and raw["text"] == DRAFT and isinstance(raw["at"], float | int)
    out = capsys.readouterr().out
    assert out == (
        'queued q1: new story "Add todo" (approved by the human); the runner gives it '
        "an id and commits it between steps\n"
    )


def test_none_approval_prints_the_liaison_alone_text(configured: Path, capsys) -> None:
    assert run(configured, "new", put(configured), "--approved-by", "none") == 0
    assert "(written by the liaison alone)" in capsys.readouterr().out


def test_options_are_kept_in_the_request(configured: Path) -> None:
    with_state(configured, story("s2"))
    story_file(configured, "s2", "x")
    plan = put(configured, "plan", "plan.md")
    code = run(
        configured,
        "new",
        put(configured),
        "--approved-by",
        "human",
        "--sprint",
        "next",
        "--after",
        "s2",
        "--plan",
        plan,
    )
    assert code == 0
    raw = json.loads(system.read_text(configured / ".team/run/liaison/stories/q1.json"))
    assert raw["sprint"] == "next" and raw["after"] == "s2"
    assert raw["plan"] in ("plan.md", plan)


def test_each_new_draft_gets_the_next_number(configured: Path) -> None:
    path = put(configured)
    run(configured, "new", path, "--approved-by", "none")
    run(configured, "new", path, "--approved-by", "none")
    assert queued(configured) == ["q1.json", "q2.json"]


def test_new_never_writes_stories_or_calls_git(configured: Path, fake) -> None:
    run(configured, "new", put(configured), "--approved-by", "human")
    assert not system.exists(configured / ".team" / "stories")
    assert [c for c in fake.commands if c.argv[:1] == ("git",)] == []


def test_new_works_when_the_run_is_stopped(configured: Path) -> None:
    state_mod.save(configured / ".team" / "run", RunState())
    assert run(configured, "new", put(configured), "--approved-by", "none") == 0


def test_depends_on_naming_known_stories_is_accepted(configured: Path) -> None:
    with_state(configured, story("s1"))
    text = DRAFT.replace("acceptance:", "depends_on: [s1]\nacceptance:", 1)
    assert run(configured, "new", put(configured, text), "--approved-by", "none") == 0


def test_approved_by_is_required_and_checked(configured: Path) -> None:
    with pytest.raises(SystemExit):
        run(configured, "new", put(configured))
    with pytest.raises(SystemExit):
        run(configured, "new", put(configured), "--approved-by", "robot")


# ----- story new: refused with every reason -----------------------------------------


def test_a_bad_draft_is_refused_with_every_line_and_queues_nothing(
    configured: Path, capsys
) -> None:
    with_state(configured, story("s1"))
    bad = (
        "---\nid: s9\ndepends_on: [s404]\nacceptance:\n"
        '  - id: AC1\n    text: "a"\n    environment: nowhere\n'
        '  - id: AC1\n    text: "b"\n    environment: cli\n'
        "---\n\n   \n"
    )
    path = put(configured, bad)
    code = run(configured, "new", path, "--approved-by", "human", "--after", "s77")
    assert code == 1
    lines = refusal(capsys)
    text = "\n".join(lines)
    assert f"{path}: id is written by the runner; remove it" in lines
    assert "title" in text and "nowhere" in text and "AC1" in text
    assert f"{path}: depends_on names unknown stories: s404" in lines
    assert f"{path}: the body must hold the user story" in lines
    assert "--after: no story 's77'" in lines
    assert len(lines) >= 7
    assert queued(configured) == []


def test_the_shared_key_is_refused_as_runner_written(configured: Path, capsys) -> None:
    path = put(configured, DRAFT.replace("acceptance:", "shared: []\nacceptance:", 1))
    assert run(configured, "new", path, "--approved-by", "none") == 1
    assert f"{path}: shared is written by the runner; remove it" in refusal(capsys)


def test_depends_on_must_be_a_list_of_ids(configured: Path, capsys) -> None:
    path = put(configured, DRAFT.replace("acceptance:", "depends_on: s1\nacceptance:", 1))
    assert run(configured, "new", path, "--approved-by", "none") == 1
    assert f"{path}: depends_on must be a list of story ids" in refusal(capsys)


def test_no_frontmatter_is_refused(configured: Path, capsys) -> None:
    path = put(configured, "just text\n")
    assert run(configured, "new", path, "--approved-by", "none") == 1
    assert queued(configured) == [] and refusal(capsys)


def test_an_unreadable_file_gives_its_line_plus_the_option_lines(configured: Path, capsys) -> None:
    missing = str(configured / "nope.md")
    code = run(configured, "new", missing, "--approved-by", "none", "--after", "s77")
    assert code == 1
    lines = refusal(capsys)
    assert lines[0].startswith(f"cannot read {missing}: ")
    assert "--after: no story 's77'" in lines
    assert len(lines) == 2
    assert queued(configured) == []


def test_after_must_name_an_open_story(configured: Path, capsys) -> None:
    with_state(configured, story("s3", StoryStatus.DONE))
    code = run(configured, "new", put(configured), "--approved-by", "none", "--after", "s3")
    assert code == 1
    assert refusal(capsys) == ["--after: s3 is done; name an open story"]


def test_plan_needs_human_approval(configured: Path, capsys) -> None:
    plan = put(configured, "plan", "plan.md")
    code = run(configured, "new", put(configured), "--approved-by", "none", "--plan", plan)
    assert code == 1
    assert "--plan needs --approved-by human" in refusal(capsys)


def test_plan_must_name_a_file(configured: Path, capsys) -> None:
    code = run(configured, "new", put(configured), "--approved-by", "human", "--plan", "no.md")
    assert code == 1
    assert refusal(capsys) == ["--plan: no file no.md"]
    assert queued(configured) == []


def test_new_takes_exactly_one_target(configured: Path, capsys) -> None:
    assert run(configured, "new", "a.md", "b.md", "--approved-by", "none") == 1
    assert refusal(capsys) == [USAGE]


def test_amend_takes_exactly_two_targets(configured: Path, capsys) -> None:
    assert run(configured, "amend", "s1", "--approved-by", "none") == 1
    assert refusal(capsys) == [USAGE]
    assert run(configured, "amend", "s1", "a.md", "b.md", "--approved-by", "none") == 1
    assert refusal(capsys) == [USAGE]


# ----- story amend (AC4) ------------------------------------------------------------

OLD = (
    '---\nid: s1\ntitle: "Add todo"\nacceptance:\n'
    '  - id: AC1\n    text: "old"\n    environment: cli\n'
    "---\n\nBody.\n"
)


def amending(repo: Path, status: StoryStatus = StoryStatus.ACTIVE) -> None:
    with_state(repo, StoryState("s1", "Add todo", "implement", status=status))
    story_file(repo, "s1", OLD)


def test_a_clean_amend_is_queued(configured: Path, capsys) -> None:
    amending(configured)
    path = put(configured)
    assert run(configured, "amend", "s1", path, "--approved-by", "human") == 0
    raw = json.loads(system.read_text(configured / ".team/run/liaison/stories/q1.json"))
    assert raw["action"] == "amend" and raw["story"] == "s1" and raw["sprint"] == ""
    assert raw["after"] == "" and raw["text"] == DRAFT
    assert capsys.readouterr().out == (
        "queued q1: new ACs for s1 (approved by the human); the runner commits them between "
        "steps and sends s1 back to design; the draft's body is not used\n"
    )


def test_amend_of_an_unknown_story_is_refused(configured: Path, capsys) -> None:
    assert run(configured, "amend", "s9", put(configured), "--approved-by", "none") == 1
    assert "no story 's9'" in refusal(capsys)
    assert queued(configured) == []


def test_amend_of_a_finished_story_is_refused(configured: Path, capsys) -> None:
    amending(configured, StoryStatus.DONE)
    assert run(configured, "amend", "s1", put(configured), "--approved-by", "none") == 1
    assert "s1 is done; story amend changes open stories only" in refusal(capsys)


def test_amend_refuses_sprint_and_after(configured: Path, capsys) -> None:
    amending(configured)
    code = run(
        configured, "amend", "s1", put(configured), "--approved-by", "none", "--sprint", "next"
    )
    assert code == 1
    assert "--sprint and --after apply to story new only" in refusal(capsys)


def test_amend_with_a_different_title_is_refused(configured: Path, capsys) -> None:
    amending(configured)
    path = put(configured, DRAFT.replace("Add todo", "Other"))
    assert run(configured, "amend", "s1", path, "--approved-by", "none") == 1
    assert refusal(capsys) == [
        f"{path}: title is 'Other', not s1's 'Add todo'; story amend replaces only the ACs",
    ]


def test_amend_with_a_different_depends_on_is_refused(configured: Path, capsys) -> None:
    amending(configured)
    with_state(configured, StoryState("s1", "Add todo", "implement"), story("s2"))
    path = put(configured, DRAFT.replace("acceptance:", "depends_on: [s2]\nacceptance:", 1))
    assert run(configured, "amend", "s1", path, "--approved-by", "none") == 1
    assert f"{path}: depends_on is [s2], not s1's []; story amend replaces only the ACs" in (
        refusal(capsys)
    )


def test_amend_with_the_same_acs_is_refused(configured: Path, capsys) -> None:
    amending(configured)
    same = DRAFT.replace('"adds an item"', '"old"')
    path = put(configured, same)
    assert run(configured, "amend", "s1", path, "--approved-by", "none") == 1
    assert refusal(capsys) == [f"{path}: the ACs are the same as s1's; nothing to amend"]


def test_amend_of_a_story_file_without_frontmatter_is_refused(configured: Path, capsys) -> None:
    with_state(configured, StoryState("s1", "Add todo", "implement"))
    story_file(configured, "s1", "no frontmatter\n")
    assert run(configured, "amend", "s1", put(configured), "--approved-by", "none") == 1
    out = refusal(capsys)
    assert any(
        line.startswith("cannot amend s1: ") and line.endswith("has no readable frontmatter")
        for line in out
    )


# ----- status (cli) -----------------------------------------------------------------


def test_status_shows_queued_and_settled_story_requests(configured: Path, capsys) -> None:
    path = put(configured)
    run(configured, "new", path, "--approved-by", "none")
    run(configured, "new", path, "--approved-by", "none")
    run_dir = configured / ".team" / "run"
    state_mod.save(run_dir, RunState(story_requests={"q1": "refused: x"}))
    capsys.readouterr()
    assert cli.main(["--repo", str(configured), "status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["queued_stories"] == ["q2"] and out["story_requests"] == {"q1": "refused: x"}


def test_state_round_trips_story_requests_and_loads_old_states() -> None:
    st = RunState(story_requests={"q1": "opened s1 abc"})
    assert RunState.from_json(st.to_json()).story_requests == {"q1": "opened s1 abc"}
    data = json.loads(RunState().to_json())
    data.pop("story_requests", None)
    assert RunState.from_json(json.dumps(data)).story_requests == {}
