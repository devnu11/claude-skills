"""A story step in its worktree (s159 B3) agrees with its gates on where things live: the
presentation and the Proxy's sandbox in the main checkout's run dir (B2), the acceptance
report in the worktree. Built as ``start`` builds it, with ``cli.make_pipeline``."""

from __future__ import annotations

from pathlib import Path

from agile_team import acceptance, cli, guard, presentation, system
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState, Verdict
from agile_team.guard import ToolCall

from .conftest import present, write_story

REPORT = ".team/acceptance/s1.md"


def worktree_view(make_runtime, step: str):
    """The run, s1 at ``step`` with a worktree, and the run seen from that worktree."""
    rt = make_runtime(pipeline_for=cli.make_pipeline)
    rt.state.story_branches = True
    story = StoryState("s1", "T", step, sprint=1, worktree_head="a" * 40, branch="team/story-s1")
    rt.state.stories["s1"] = story
    view = rt.at(story)
    write_story(view.config, "s1", "cli")
    return rt, view, story


def check(scope: guard.Scope, name: str, path: Path | str) -> str | None:
    key = guard.PATH_KEYS[name]
    return guard.check_tool_use(scope, ToolCall(name, {key: str(path)}))


# ----- e2e: the integration-tester (F1 to F3) -----


def test_the_tester_brief_names_the_presentation_in_the_main_run_dir(make_runtime) -> None:
    rt, view, _ = worktree_view(make_runtime, "e2e")
    plan = view.plan(StepRequest("integration-tester", "go", "s1"))
    source = rt.config.run_dir / "presentation/s1/cli"
    assert f"- cli (package): {source.as_posix()}/ (AC1)" in plan.prompt
    assert system.is_dir(source / "workspace")
    assert plan.scope.git_workspace == system.resolve(rt.config.run_dir / "presentation/s1")


def test_the_tester_may_write_that_presentation_and_its_worktree_only(make_runtime) -> None:
    rt, view, _ = worktree_view(make_runtime, "e2e")
    scope = view.plan(StepRequest("integration-tester", "go", "s1")).scope
    guide = rt.config.run_dir / "presentation/s1/cli/PRESENTATION.md"
    assert scope.repo == view.config.repo and scope.run_home == rt.config.repo
    assert check(scope, "Write", guide) is None
    assert check(scope, "Write", view.config.repo / "tests/e2e/test_s1.py") is None
    assert "outside the repo" in check(scope, "Write", rt.config.repo / "src/app.py")
    assert "may not write .team/run/state.json" in check(
        scope, "Write", rt.config.run_dir / "state.json"
    )


def test_the_e2e_stop_check_and_gate_read_the_presentation_the_brief_named(make_runtime) -> None:
    rt, view, story = worktree_view(make_runtime, "e2e")
    guide = rt.config.run_dir / "presentation/s1/cli/PRESENTATION.md"
    gap = view.pipeline.checks.presentation(story)
    assert gap and guide.as_posix() in gap and view.pipeline.unpresented(story) is not None
    present(rt.config, "s1")
    assert view.pipeline.checks.presentation(story) is None
    assert view.pipeline.checks.presented(story).verdict is Verdict.PASS
    assert view.pipeline.unpresented(story) is None


# ----- acceptance: the Customer Proxy (F4 to F6) -----


def proxy_plan(make_runtime):
    rt, view, _ = worktree_view(make_runtime, "acceptance")
    present(rt.config, "s1")
    return rt, view, view.plan(StepRequest("customer-proxy", "go", "s1"))


def test_the_proxy_sandbox_is_under_the_main_run_dir_and_it_may_write_it(make_runtime) -> None:
    rt, view, plan = proxy_plan(make_runtime)
    root = plan.prepared.root
    assert root == rt.config.run_dir / "customer/cli" and plan.scope.cwd == plan.prepared.workdir
    assert plan.scope.run_home == rt.config.repo and plan.scope.repo == view.config.repo
    assert check(plan.scope, "Write", "notes.md") is None
    assert check(plan.scope, "Write", root / "notes.md") is None
    assert check(plan.scope, "Read", root / "presentation/PRESENTATION.md") is None
    assert presentation.GUIDE in plan.prompt and str(root / "presentation") in plan.prompt


def test_the_proxy_report_goes_to_the_worktree_where_the_gate_reads_it(make_runtime) -> None:
    rt, view, plan = proxy_plan(make_runtime)
    report = view.config.repo / REPORT
    assert check(plan.scope, "Write", report) is None
    assert "outside the repo" in check(plan.scope, "Write", rt.config.repo / REPORT)
    line = acceptance.WORKTREE_LINE.format(repo=view.config.repo, file=REPORT)
    assert line in plan.prompt and "## Criteria for this step" in plan.prompt
    system.make_dirs(report.parent)
    system.write_text(report, "## Environment: cli\nok\n")
    assert view.pipeline.checks.read(REPORT) == "## Environment: cli\nok\n"


def test_a_main_checkout_step_still_sees_relative_paths_and_no_worktree_line(make_runtime) -> None:
    rt = make_runtime(pipeline_for=cli.make_pipeline)
    write_story(rt.config, "s1", "cli")
    rt.state.stories["s1"] = StoryState("s1", "T", "e2e", sprint=1)
    plan = rt.plan(StepRequest("integration-tester", "go", "s1"))
    assert "- cli (package): .team/run/presentation/s1/cli/ (AC1)" in plan.prompt
    assert plan.scope.run_home is None
    rt.state.stories["s1"].step = "acceptance"
    present(rt.config, "s1")
    proxy = rt.plan(StepRequest("customer-proxy", "go", "s1"))
    assert "This step's repo is" not in proxy.prompt and proxy.scope.run_home is None
