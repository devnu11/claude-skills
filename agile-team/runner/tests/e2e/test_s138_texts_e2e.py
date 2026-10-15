"""s138 end to end: hold and refusal texts name the action; none says to edit a story file."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from agile_team import cli, story_spec, suite_runs, system
from agile_team import state as state_mod
from agile_team.state import RunState

from ..conftest import FakeQuery, git, present, write_story
from ..test_dispatch import open_story, run
from ..test_s86_dependencies import st, start_args
from ..test_s94_story_files import wire

REVIEW_STACK = Path(cli.__file__).parents[2] / "docs" / "customer" / "review-stack.md"
EDIT = re.compile(r"(?i)\bedit\b|\bfix (the |its )?(story )?(file|frontmatter)|fix depends_on")


def test_ac1_gate_hold_hands_the_po_the_actions_not_an_edit(make_runtime) -> None:
    rt = make_runtime(FakeQuery())
    wire(rt)
    open_story(rt, "acceptance")
    present(rt.config)
    write_story(rt.config, "s1", "mars")
    report = run(rt, "customer-proxy", story="s1")
    assert report["gate"]["verdict"] == "hold"
    reason = report["reason"]
    assert "Only the runner writes story files" in reason
    for action in ("continue_story", "ask_user", "story amend"):
        assert action in reason
    assert not EDIT.search(story_spec.STORY_FILE_HOLD)


def test_ac2_start_refuses_a_cycle_and_names_the_human_steps(
    configured: Path, key_home: Path
) -> None:
    state_mod.save(configured / ".team/run", RunState(stories={"s1": st("s1"), "s2": st("s2")}))
    system.make_dirs(configured / ".team/stories")
    system.write_text(configured / ".team/stories/s1.md", "---\ndepends_on: [s2]\n---\n")
    system.write_text(configured / ".team/stories/s2.md", "---\ndepends_on: [s1]\n---\n")
    git(configured, "add", "-A")
    git(configured, "commit", "-qm", "cycle")
    with pytest.raises(cli.CliError) as err:
        cli.cmd_start(start_args(configured, key_home, "--task", "t"), FakeQuery("never"))
    text = str(err.value)
    assert "s1 -> s2 -> s1" in text
    for step in ("story amend cannot change depends_on", "git commit", "agile-team start"):
        assert step in text
    assert "agile-team accept-checkout" in text
    assert "fix depends_on in" not in text


@pytest.mark.parametrize("text", [story_spec.STORY_FILE_HOLD, suite_runs.BAD_SUITE_RUNS])
def test_ac3_role_texts_never_say_edit(text: str) -> None:
    assert EDIT.search(text) is None
    assert "ask_user" in text


def test_ac4_review_stack_says_who_acts_on_a_bug_story() -> None:
    text = " ".join(REVIEW_STACK.read_text().split())
    assert "the team opens a bug story" not in text
    assert "Product Owner asks the liaison for a bug story, the liaison writes it" in text
