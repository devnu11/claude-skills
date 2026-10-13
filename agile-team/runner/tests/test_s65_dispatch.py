"""s65: confined steps get git's ceiling and a workspace (rules G1, G2, G9)."""

from pathlib import Path

import pytest
from agile_team import dispatch, git_check, presentation, system
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState

from .conftest import present
from .fake_system import FakeSystem


def story_at(rt, step: str) -> None:
    rt.state.stories["s1"] = StoryState("s1", "Add todo", step, sprint=1)


def plan_of(rt, role: str):
    return rt.plan(StepRequest(role, "go", "s1"))


def test_confined_steps_are_exactly_e2e_and_acceptance() -> None:
    assert set(dispatch.GIT_CONFINED) == {"e2e", "acceptance"}


def test_integration_tester_is_confined_to_the_presentation_workspace(make_runtime) -> None:
    rt = make_runtime()
    story_at(rt, "e2e")
    present(rt.config)
    plan = plan_of(rt, "integration-tester")
    expected = system.resolve(presentation.workspace_of(rt.config, "s1"))
    assert plan.scope.git_workspace == expected
    env = plan.launch.env
    assert env[git_check.CEILING_ENV] == str(system.resolve(rt.config.run_dir))
    assert env[git_check.KEEP_CWD_ENV] == "1"
    assert env["ANTHROPIC_API_KEY"] == "k"


def test_proxy_is_confined_to_its_copy_of_the_workspace(make_runtime) -> None:
    rt = make_runtime()
    story_at(rt, "acceptance")
    present(rt.config)
    plan = plan_of(rt, "customer-proxy")
    workspace = plan.scope.git_workspace
    assert workspace is not None and workspace.name == "workspace"
    assert workspace == system.resolve(presentation.copied_workspace(plan.prepared.root))
    assert git_check.CEILING_ENV in plan.launch.env


def test_developer_step_is_not_confined(make_runtime) -> None:
    rt = make_runtime()
    story_at(rt, "implement")
    plan = plan_of(rt, "developer-cli")
    assert plan.scope.git_workspace is None
    assert git_check.CEILING_ENV not in (plan.launch.env or {})
    assert git_check.KEEP_CWD_ENV not in (plan.launch.env or {})


def test_fitting_step_picks_the_first_matching_key() -> None:
    table = {"e2e": 1, "acceptance": 2}
    assert dispatch.fitting_step("integration-tester", table) == "e2e"
    assert dispatch.fitting_step("customer-proxy", table) == "acceptance"
    assert dispatch.fitting_step("developer", table) is None


# ----- G9 / AC8: the workspace survives ----------------------------------------------


def story_of() -> StoryState:
    return StoryState("s4", "A story", "e2e", sprint=1)


def test_workspace_and_copy_paths(configured: Path) -> None:
    config = __import__("agile_team.config", fromlist=["load"]).load(configured)
    source = presentation.source_dir(config, "s4")
    assert presentation.workspace_of(config, "s4") == source / "workspace"
    root = Path("/x/sandbox")
    assert presentation.copied_workspace(root) == root / "presentation" / "workspace"


def test_lay_out_keeps_what_is_there(configured: Path, fake: FakeSystem) -> None:
    from agile_team import config as cfg

    config = cfg.load(configured)
    source = presentation.lay_out(config, story_of())
    system.write_text(source / "workspace" / "a.txt", "keep")
    system.write_text(source / "PRESENTATION.md", "guide")
    fake.put(source / "workspace" / ".git" / "HEAD", "ref\n")
    presentation.lay_out(config, story_of())
    assert system.read_text(source / "workspace" / "a.txt") == "keep"
    assert system.read_text(source / "PRESENTATION.md") == "guide"
    inits = [c for c in fake.commands if "init" in c.argv]
    assert len(inits) == 1


def test_lay_out_inits_a_workspace_that_lacks_git_and_keeps_files(
    configured: Path, fake: FakeSystem
) -> None:
    from agile_team import config as cfg

    config = cfg.load(configured)
    source = present(config, "s4")
    presentation.lay_out(config, story_of())
    assert system.read_text(source / "workspace" / "todo.txt") == "milk\n"
    (init,) = [c for c in fake.commands if "init" in c.argv]
    assert init.cwd == source / "workspace"


def test_a_bounce_back_to_e2e_keeps_the_workspace_files(make_runtime) -> None:
    rt = make_runtime()
    story_at(rt, "e2e")
    rt.state.stories["s1"].rounds = 1
    source = present(rt.config)
    plan_of(rt, "integration-tester")
    assert system.read_text(source / "workspace" / "todo.txt") == "milk\n"
    assert system.exists(source / "PRESENTATION.md")


@pytest.mark.parametrize("bad", ["../x", "S1", "a/b"])
def test_lay_out_still_refuses_unsafe_ids(configured: Path, bad: str) -> None:
    from agile_team import config as cfg
    from agile_team import sandbox

    with pytest.raises(sandbox.SandboxError):
        presentation.lay_out(cfg.load(configured), StoryState(bad, "t", "e2e", sprint=1))
