"""s135 end to end on real git: story onboarding, authorship, revert, amend.

``agile-team story`` queues a file; one ``Intake.apply`` (the router's safe point) commits it.
Everything after that, ``Reverter`` and ``git log``, runs for real in ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

from agile_team import cli, system
from agile_team.git_ops import Git
from agile_team.reverts import Reverter
from agile_team.story_drafts import LIAISON_AUTHOR
from agile_team.story_intake import Intake

from ..conftest import git

DRAFT = (
    '---\ntitle: "Add todo"\nacceptance:\n'
    '  - id: AC1\n    text: "adds an item"\n    environment: cli\n'
    "---\n\nAs a user, I want to add items.\n"
)
AMENDED = DRAFT.replace("adds an item", "adds and lists an item")
FILE = ".team/stories/s1.md"


def queue(repo: Path, *args: str) -> None:
    """Run ``agile-team story …`` through the real CLI; it must succeed."""
    assert cli.main(["--repo", str(repo), "story", *args]) == 0


def draft(repo: Path, text: str, name: str = "draft.md") -> str:
    """Write a draft file outside the repo's tracked paths and give its path."""
    path = repo / ".team" / "run" / name
    system.make_dirs(path.parent)
    system.write_text(path, text)
    return str(path)


def onboard(make_runtime, repo: Path, approval: str):
    """Queue DRAFT with ``approval`` and run one intake tick; the runtime."""
    rt = make_runtime()
    queue(repo, "new", draft(repo, DRAFT), "--approved-by", approval)
    Intake(rt).apply()
    return rt


def log(repo: Path, fmt: str) -> list[str]:
    """``git log --format=fmt`` of the team branch, newest first."""
    return git(repo, "log", f"--format={fmt}").splitlines()


def test_ac2_ac3_liaison_mode_commits_as_the_liaison(make_runtime, configured: Path) -> None:
    rt = onboard(make_runtime, configured, "none")
    story = rt.state.stories["s1"]
    assert git(configured, "log", "-1", "--format=%s").strip() == (
        "docs(s1): created story to Add todo"
    )
    assert git(configured, "log", "-1", "--format=%an <%ae>").strip() == LIAISON_AUTHOR
    body = git(configured, "log", "-1", "--format=%B")
    assert "Human-involvement: none: written and submitted by the liaison" in body
    assert story.file_commits == [git(configured, "rev-parse", "HEAD").strip()]
    assert system.read_text(configured / FILE).count("adds an item") == 1
    assert git(configured, "status", "--porcelain").strip() == ""


def test_ac3_human_mode_commits_as_the_repo_user(make_runtime, configured: Path) -> None:
    onboard(make_runtime, configured, "human")
    assert git(configured, "log", "-1", "--format=%an <%ae>").strip() == "Test <t@example.com>"
    assert "Human-involvement: approved" in git(configured, "log", "-1", "--format=%B")


def step_commit(repo: Path, rt) -> str:
    """A code commit for s1 as a developer step makes it, recorded on the story."""
    system.write_text(repo / "src" / "todo.py", "ITEMS = []\n")
    sha = rt.git.commit(["src/todo.py"], "feat(s1): add the todo list")
    story = rt.state.stories["s1"]
    story.commit, story.code_commits = sha, [sha]
    rt.save()
    return sha


def test_ac6_the_creation_commit_survives_a_story_revert(make_runtime, configured: Path) -> None:
    rt = onboard(make_runtime, configured, "none")
    created = rt.state.stories["s1"].file_commits[:]
    code = step_commit(configured, rt)
    result = Reverter(rt).run({"story": "s1", "reason": "wrong approach"})
    assert result["status"] == "reverted", result
    assert not (configured / "src" / "todo.py").exists()
    assert "adds an item" in system.read_text(configured / FILE)
    assert rt.state.stories["s1"].file_commits == created
    assert code in result["commits"] and created[0] not in result["commits"]
    assert Git(configured).is_ancestor(created[0])


def test_ac4_amend_replaces_the_acs_and_goes_back_to_design(make_runtime, configured: Path) -> None:
    rt = onboard(make_runtime, configured, "none")
    story = rt.state.stories["s1"]
    story.step, story.rounds = "implement", 2
    rt.save()
    amend = draft(configured, AMENDED, "amend.md")
    queue(configured, "amend", "s1", amend, "--approved-by", "none")
    Intake(rt).apply()
    assert "adds and lists an item" in system.read_text(configured / FILE)
    assert "adds an item" not in system.read_text(configured / FILE)
    assert log(configured, "%s")[0] == "docs(s1): amended story to Add todo"
    assert rt.state.stories["s1"].step == rt.pipeline.first()
    amended = [e for e in rt.events.events() if e.kind == "story-amended"]
    assert len(amended) == 1 and amended[0].story == "s1"
    assert git(configured, "status", "--porcelain").strip() == ""
