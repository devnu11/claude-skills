"""s114 end to end: no Scribe, no briefs; old state loads; a retired role config is refused."""

from __future__ import annotations

import json
from pathlib import Path

from agile_team import cli
from agile_team import state as state_mod
from agile_team.gates import StoryStatus
from agile_team.roles import RoleBook

from ..conftest import handoff
from ..pipeline_helpers import Script, add_story, build, drive, step_roles

WHY = (
    "the Scribe was retired in s114: the architect writes ADRs in .team/adr/ "
    "and roles get no briefs"
)
MARKER = "BRIEF-MARKER-developer"


def test_old_state_and_briefs_run_a_story_to_done_with_no_scribe(make_runtime, configured) -> None:
    """AC1/AC2: a stale brief stays out of prompts, scribe_due is dropped, no Scribe step runs."""
    briefs = configured / ".team" / "briefs"
    briefs.mkdir(parents=True)
    (briefs / "developer.md").write_text(MARKER)
    script = Script({"code-reviewer": [handoff()]})
    rt = build(make_runtime, script, steps=["review"])
    old = {"scribe_due": ["s0"], "overrides": {"scribe": {"model": "haiku"}}}
    run_dir = rt.config.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / state_mod.STATE_FILE).write_text(json.dumps(old))
    rt.state = state_mod.load(run_dir)
    add_story(rt, "s1", "review")
    drive(rt)
    assert rt.state.stories["s1"].status is StoryStatus.DONE
    assert step_roles(rt) == ["code-reviewer"]
    assert all(MARKER not in p for ps in script.prompts.values() for p in ps)
    state_mod.save(run_dir, rt.state)
    saved = json.loads((run_dir / state_mod.STATE_FILE).read_text())
    assert "scribe_due" not in saved and "scribe" not in saved.get("overrides", {})


def test_every_prompt_ignores_a_brief(configured: Path) -> None:
    """AC1: no role's prompt carries the brief or a Scribe heading."""
    briefs = configured / ".team" / "briefs"
    briefs.mkdir(parents=True)
    book = RoleBook.for_repo(configured, {})
    for name in book.names():
        (briefs / f"{name}.md").write_text(f"BRIEF-MARKER-{name}")
        prompt = book.system_prompt(book.resolve(name), "scope")
        assert f"BRIEF-MARKER-{name}" not in prompt
        assert "Brief from the Scribe" not in prompt


def test_architect_owns_adrs(configured: Path) -> None:
    """AC3: the architect may write .team/adr/** and its role file says to."""
    book = RoleBook.for_repo(configured, {})
    architect = book.resolve("architect")
    assert ".team/adr/**" in architect.write
    assert ".team/adr/NNNN-<slug>.md" in architect.body


def test_roles_scribe_section_makes_start_refuse(configured: Path, capsys) -> None:
    """AC2: [roles.scribe] in the config exits 1 with the retirement message."""
    toml = configured / ".agile-team.toml"
    toml.write_text(toml.read_text() + '\n[roles.scribe]\nmodel = "haiku"\n')
    code = cli.main(["--repo", str(configured), "start", "--task", "go"])
    err = capsys.readouterr().err
    assert code == 1
    assert f"{WHY}; remove [roles.scribe] from .agile-team.toml" in err


def test_scribe_role_file_makes_the_cli_refuse(configured: Path, capsys) -> None:
    """AC2/SC7: a live scribe.md in the repo roles refuses with exit 1, not a traceback."""
    roles = configured / ".team" / "roles"
    roles.mkdir(parents=True, exist_ok=True)
    (roles / "scribe.md").write_text("Keep ADRs short.\n")
    code = cli.main(["--repo", str(configured), "config", "check"])
    err = capsys.readouterr().err
    assert code == 1
    assert f"{WHY}; delete {roles / 'scribe.md'}" in err


def test_briefs_dir_is_gone_from_the_repo() -> None:
    """AC4: the repo no longer holds .team/briefs; .team/adr stays."""
    root = Path(__file__).resolve().parents[4]
    assert not (root / ".team" / "briefs").exists()
    assert any((root / ".team" / "adr").glob("*.md"))
