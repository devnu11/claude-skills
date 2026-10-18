"""s99 AC4: one runner-stage event per stage run, written by the real call sites."""

import asyncio
import json
from pathlib import Path

import pytest
from agile_team import boundary_runner, presentation, sandbox, stages, system, upstream
from agile_team.boundary import Edge, Stage
from agile_team.config import Environment, Targeted
from agile_team.dispatch import StepRequest
from agile_team.events import EventKind
from agile_team.gates import OpenDispute, StoryState
from agile_team.po_tools import Tools

from .conftest import FakeQuery, FakeRunner
from .fake_system import Done, FakeSystem
from .pipeline_helpers import add_story
from .test_boundary_runner import Env
from .test_s69_runtime import PKG_TEST, ROW, call, tools, tracked

NAME = stages.Name


def seen(rt) -> list[dict]:
    """The runner-stage events so far, as ``{name, story, **data}``."""
    return [
        {"name": e.data["stage"], "story": e.story, **e.data}
        for e in rt.events.events()
        if e.kind == EventKind.RUNNER_STAGE
    ]


def names(rt) -> list[str]:
    return [s["name"] for s in seen(rt)]


def placed(rt, story: StoryState | None = None):
    return rt.stage_log.within(stages.Place(story.id, story.step) if story else stages.NOWHERE)


# -- gates -----------------------------------------------------------------


def checks_runtime(make_runtime, results=None):
    rt = make_runtime(runner=FakeRunner(results))
    rt.pipeline.checks.commands["static"] = "mypy ."
    return rt


def test_the_implement_gate_writes_one_event_with_the_requests_story_and_step(
    make_runtime,
) -> None:
    rt = checks_runtime(make_runtime, {"pytest --cov": (0, "TOTAL 100 0 100%")})
    story = add_story(rt, step="implement")

    async def run_step(request):
        rt.pipeline.checks.tests_green_and_covered()
        return {}

    rt._run_step = run_step  # type: ignore[method-assign]
    asyncio.run(rt._placed_step(StepRequest("developer-cli", "go", "s1")))
    (event,) = seen(rt)
    assert (event["name"], event["when"], event["attach"]) == (
        "gate.tests+coverage",
        "after",
        "step",
    )
    assert event["story"] == "s1" and event["step"] == story.step == "implement"


def test_a_step_without_a_story_leaves_the_event_unplaced(make_runtime) -> None:
    rt = checks_runtime(make_runtime)

    async def run_step(request):
        rt.pipeline.checks.green()
        return {}

    rt._run_step = run_step  # type: ignore[method-assign]
    asyncio.run(rt._placed_step(StepRequest("developer-cli", "go", None)))
    (event,) = seen(rt)
    assert event["story"] is None and event["step"] is None


def test_the_quality_commands_are_before_stages(make_runtime) -> None:
    rt = checks_runtime(make_runtime)
    for command in ("lint", "static", "coverage"):
        rt.pipeline.checks.ran(command)
    runs = seen(rt)
    assert [r["name"] for r in runs] == ["quality.lint", "quality.static", "quality.coverage"]
    assert {r["when"] for r in runs} == {"before"}


def test_route_lint_and_dispute_output_are_stages(make_runtime) -> None:
    rt = checks_runtime(make_runtime)
    rt.pipeline.checks.lint_outputs()
    rt.pipeline.checks.test_output("t.py::a")
    assert names(rt) == ["gate.route-lint", "gate.dispute-output"]


def test_the_presentation_trial_is_a_stage(make_runtime) -> None:
    rt = checks_runtime(make_runtime)
    story = StoryState("s1", "Add", "e2e", sprint=1)
    rt.pipeline.checks.presented(story)
    assert names(rt) == ["presentation.trial"]


def test_pass_tests_writes_gate_green_for_the_story(make_runtime) -> None:
    rt = make_runtime(runner=FakeRunner({"pytest": (0, "ok")}))
    rt.state.sprint = 1
    dispute = OpenDispute("t.py::a", "W6", "r", "t.py", "abc")
    rt.state.stories["s1"] = StoryState("s1", "Add", "tests", sprint=1, dispute=dispute)
    rt.record_checkout()
    reply = asyncio.run(Tools(rt).pass_tests({"story": "s1", "reason": "r"}))
    out = json.loads(reply["content"][0]["text"])
    assert out["status"] != "refused"
    runs = [s for s in seen(rt) if s["name"] == "gate.green"]
    assert [r["story"] for r in runs] == ["s1"]


# -- dispatch --------------------------------------------------------------


def test_the_router_checkout_guard_has_no_story(make_runtime) -> None:
    rt = make_runtime(FakeQuery())
    assert rt.checkout_moved() is None
    (run,) = seen(rt)
    assert (run["name"], run["story"], run["attach"]) == ("checkout.guard", None, "step")


def test_verify_checkout_is_the_verify_stage(make_runtime) -> None:
    rt = make_runtime(FakeQuery())
    rt.record_checkout()
    rt.verify_checkout()
    assert names(rt) == ["checkout.verify"]


def test_presentation_layout_is_a_stage(make_runtime, monkeypatch) -> None:
    rt = make_runtime(FakeQuery())
    laid = []
    monkeypatch.setattr(presentation, "lay_out", lambda config, story: laid.append(story))
    story = StoryState("s9", "T", "e2e", sprint=1)
    plan = type("P", (), {"story": story, "prompt": "go"})()
    rt._lay_out_presentation(plan)  # type: ignore[arg-type]
    assert laid == [story] and names(rt) == ["presentation.layout"]
    assert plan.prompt == "go"  # a story without showings adds no section


def test_the_customer_proxy_prepare_is_the_env_prepare_stage(make_runtime, monkeypatch) -> None:
    rt = make_runtime(FakeQuery())
    environment = Environment("cli", "package")
    monkeypatch.setattr(rt.config, "environment", lambda name: environment)
    monkeypatch.setattr(rt, "_order", lambda d, story: None)

    def refuse(config, order):
        raise sandbox.SandboxError("no")

    rt.prepare_fn = refuse
    plan = type("P", (), {"story": None})()
    with pytest.raises(sandbox.SandboxError):
        rt._attach_environment(plan)  # type: ignore[arg-type]
    (run,) = seen(rt)
    assert run["name"] == "env.prepare" and run["raised"]


# -- boundary --------------------------------------------------------------


@pytest.mark.parametrize("stage", list(Stage))
def test_each_boundary_stage_writes_its_event(make_runtime, monkeypatch, stage: Stage) -> None:
    env = Env(make_runtime)

    def boom(runner, boundary):
        raise RuntimeError("x")

    monkeypatch.setitem(boundary_runner.STAGE_RUNNERS, stage, boom)
    env.open(Edge.START, stage=stage)
    env.br.step()
    (run,) = seen(env.rt)
    assert run["name"] == stages.BOUNDARY[stage].value
    assert (run["attach"], run["story"]) == ("boundary", None)


# -- runner tools ----------------------------------------------------------

OTHER = Targeted("other", "run-other {tests}")
OTHER_TEST = "other/tests/test_z.py"


def test_run_tests_with_two_batches_is_one_during_stage(make_runtime) -> None:
    results = {**tracked(PKG_TEST), **tracked(OTHER_TEST)}
    t, rt, _ = tools(make_runtime, results, rows=(ROW, OTHER))
    reply = call(t.run_tests, {"tests": [PKG_TEST, OTHER_TEST]})
    assert len(reply["runs"]) == 2
    (run,) = seen(rt)
    assert (run["name"], run["when"]) == ("runner-tool.run_tests", "during")


def test_run_new_tests_is_its_own_stage(make_runtime) -> None:
    t, rt, _ = tools(make_runtime, tracked(PKG_TEST))
    rt.state.stories["s1"].test_files = [PKG_TEST]
    system.make_dirs((rt.config.repo / PKG_TEST).parent)
    system.write_text(rt.config.repo / PKG_TEST, "x\n")
    call(t.run_new_tests, {})
    assert names(rt) == ["runner-tool.run_new_tests"]


def test_a_refused_run_tests_opens_no_stage(make_runtime) -> None:
    t, rt, _ = tools(make_runtime)
    assert call(t.run_tests, {"tests": []})["status"] == "refused"
    assert call(t.run_tests, {"tests": ["-k"]})["status"] == "refused"
    assert seen(rt) == []


# -- choke points ----------------------------------------------------------


def test_sandbox_run_shell_notes_the_command_and_code(configured: Path, fake: FakeSystem) -> None:
    fake.reply(("make",), Done(4))
    d = Environment("cli", "package", prepare="make it")
    from agile_team import config as cfg

    c = cfg.load(configured)
    c.environments = [d]
    p = sandbox.layout(c, d)
    with stages.unlogged(NAME.ENV_PREPARE) as run:
        assert sandbox.run_shell("make it", p) == 4
    assert (run.detail, run.code) == ("make it", 4)


def web(configured: Path):
    from agile_team import config as cfg

    d = Environment("ui", "web", prepare="exec serve 8799", url="http://127.0.0.1:8799/")
    c = cfg.load(configured)
    c.environments = [d]
    return c, d


def test_a_served_prepare_notes_zero_when_it_answers(configured: Path, fake: FakeSystem) -> None:
    from .fake_system import Hang

    fake.reply(("serve",), Hang("serving\n"))
    fake.web["http://127.0.0.1:8799/"] = system.HttpReply(200, "text/html", b"ok")
    c, d = web(configured)
    with stages.unlogged(NAME.ENV_PREPARE) as run:
        sandbox.Preparer().prepare(c, sandbox.Order(d))
    assert (run.detail, run.code) == ("exec serve 8799", 0)


def test_a_served_prepare_that_never_answers_notes_not_up_and_re_raises(
    configured: Path, fake: FakeSystem
) -> None:
    from .fake_system import Hang

    fake.reply(("serve",), Hang("serving\n"))
    c, d = web(configured)
    with stages.unlogged(NAME.ENV_PREPARE) as run, pytest.raises(sandbox.NotUp):
        sandbox.Preparer(attempts=1).prepare(c, sandbox.Order(d))
    assert (run.detail, run.code) == ("exec serve 8799", stages.NOT_UP)


def test_a_web_environment_without_prepare_notes_nothing(
    configured: Path, fake: FakeSystem
) -> None:
    from agile_team import config as cfg

    d = Environment("ui", "web", url="http://127.0.0.1:8799/")
    c = cfg.load(configured)
    c.environments = [d]
    fake.web["http://127.0.0.1:8799/"] = system.HttpReply(200, "text/html", b"ok")
    with stages.unlogged(NAME.ENV_PREPARE) as run:
        sandbox.Preparer().prepare(c, sandbox.Order(d))
    assert (run.detail, run.code) == ("", None)


def test_command_runner_notes_127_for_a_missing_binary(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("nosuchtool",), FileNotFoundError("nosuchtool"))
    with stages.unlogged(NAME.BOUNDARY_CI_WAIT) as run:
        result = upstream.command_runner(repo)(["nosuchtool", "x"], 1.0)
    assert result[0] == 127 and (run.detail, run.code) == ("nosuchtool x", 127)
