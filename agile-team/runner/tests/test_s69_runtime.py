"""s69: runner results in briefs, quality pre-run, developer runner tools, test_files record."""

from __future__ import annotations

import asyncio
import json
import shlex
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from agile_team import runner_tools, system
from agile_team.config import Targeted
from agile_team.dispatch import Runtime, StepRequest
from agile_team.gates import LS_FILES_COMMAND, StoryState, StoryStatus
from agile_team.loops import Setback
from agile_team.results import Ran
from agile_team.runner_tools import (
    NO_NEW_TESTS,
    NO_ROOT,
    NO_STORY,
    NO_TARGETED,
    NO_TESTS_NAMED,
    NOT_A_TARGET,
    UNTRACKED_TEST,
    RunnerTools,
)

from .conftest import FakeQuery, FakeRunner
from .fake_system import FakeSystem
from .pipeline_helpers import add_story

PKG = "agile-team/runner"
PKG_TEST = f"{PKG}/tests/test_x.py"
ROW = Targeted(PKG, "uv run --directory agile-team/runner pytest -q {tests}")
ALL = Targeted("", "pytest {tests}")


def tracked(path: str) -> dict[str, tuple[int, str]]:
    """The fake ``git ls-files`` answer for a file id."""
    command = LS_FILES_COMMAND.format(path=shlex.quote(path), suffix=shlex.quote("*/" + path))
    return {command: (0, path)}


def write(repo: Path, rel: str, text: str = "x\n"):
    def action() -> None:
        system.make_dirs((repo / rel).parent)
        system.write_text(repo / rel, text)

    return action


def run_step(rt: Runtime, role: str, sid: str = "s1") -> dict[str, Any]:
    return asyncio.run(rt.run_role(StepRequest(role, "go", sid)))


def prompt(rt: Runtime, role: str, sid: str = "s1") -> str:
    return rt.user_prompt(rt.plan(StepRequest(role, "go", sid)))


# ----- B2: the gate's run is kept ---------------------------------------


def test_implement_gate_keeps_the_coverage_run(make_runtime, configured: Path) -> None:
    runner = FakeRunner({"pytest --cov": (0, "TOTAL 99%")})
    rt = make_runtime(FakeQuery(action=write(configured, "src/a.py")), runner)
    add_story(rt, step="implement")
    run_step(rt, "developer-cli")
    kept = rt.results.latest("s1", "coverage")
    assert kept.code == 0 and kept.tail == "TOTAL 99%"
    assert kept.at == rt.git.head() and kept.where == "implement gate"


def test_an_escalating_gate_still_keeps_its_run(make_runtime, configured: Path) -> None:
    rt = make_runtime(
        FakeQuery(action=write(configured, "src/a.py")),
        FakeRunner({"pytest --cov": (1, "1 failed")}),
    )
    st = add_story(rt, step="implement", status=StoryStatus.ACTIVE)
    reason = "tests fail:\n1 failed"
    from agile_team.loops import normalise

    st.streak = [
        Setback("implement", "implement", "developer-cli", "bounce", "runner", normalise(reason))
    ]
    run_step(rt, "developer-cli")
    assert st.status is StoryStatus.NEEDS_MANAGER
    assert rt.results.latest("s1", "coverage").tail == "1 failed"


# ----- B5: briefs --------------------------------------------------------


def test_developer_brief_shows_the_kept_test_output(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, step="implement")
    rt.results.keep("s1", Ran("test", 1, "FAILED test_x", "abcdef1234", "tests gate"))
    text = prompt(rt, "developer-cli")
    assert "## Runner results" in text and "FAILED test_x" in text
    assert "### test: exit 1 (tests gate, at abcdef1)" in text


def test_brief_without_results_has_no_section(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, step="implement")
    assert "## Runner results" not in prompt(rt, "developer-cli")


# ----- Q1-Q3: the quality pre-run ---------------------------------------


def quality_runtime(make_runtime) -> tuple[Runtime, FakeRunner]:
    runner = FakeRunner({"ruff check .": (1, "E501"), "pytest --cov": (0, "TOTAL 97%")})
    rt = make_runtime(FakeQuery(), runner)
    add_story(rt, step="quality")
    return rt, runner


def test_quality_step_runs_lint_and_coverage_and_shows_them(make_runtime) -> None:
    rt, runner = quality_runtime(make_runtime)
    text = prompt(rt, "quality-czar")
    assert runner.calls == ["ruff check .", "pytest --cov"]  # static is unset: skipped
    assert "### lint: exit 1 (before quality, at" in text and "E501" in text
    assert text.index("### coverage") < text.index("### lint")
    assert rt.results.latest("s1", "coverage").where == "before quality"


def test_kept_coverage_at_head_is_reused(make_runtime) -> None:
    rt, runner = quality_runtime(make_runtime)
    rt.results.keep("s1", Ran("coverage", 0, "TOTAL 99%", rt.git.head(), "implement gate"))
    text = prompt(rt, "quality-czar")
    assert runner.calls == ["ruff check ."] and "TOTAL 99%" in text


def test_kept_coverage_not_at_head_is_rerun(make_runtime) -> None:
    rt, runner = quality_runtime(make_runtime)
    rt.results.keep("s1", Ran("coverage", 0, "old", "0000000", "implement gate"))
    prompt(rt, "quality-czar")
    assert "pytest --cov" in runner.calls


def test_quality_pre_run_is_a_runner_chore(make_runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    rt, _ = quality_runtime(make_runtime)
    seen: list[tuple[str, str | None]] = []

    @contextmanager
    def doing(what: str, story: str | None = None):
        seen.append((what, story))
        yield

    monkeypatch.setattr(rt.pulse, "doing", doing)
    rt.plan(StepRequest("quality-czar", "go", "s1"))
    assert seen == [("quality checks for s1", "s1")]


def test_quality_step_without_story_runs_nothing(make_runtime) -> None:
    runner = FakeRunner()
    rt = make_runtime(FakeQuery(), runner)
    rt.plan(StepRequest("quality-czar", "go", None))
    assert runner.calls == []


# ----- R1: developer plans carry the runner tools ------------------------


def test_developer_plan_gets_runner_tools(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, step="implement")
    plan = rt.plan(StepRequest("developer-cli", "go", "s1"))
    assert "runner" in plan.launch.mcp_servers
    assert {"mcp__runner__run_tests", "mcp__runner__run_new_tests"} <= set(
        plan.launch.extra_allowed
    )


def test_other_roles_get_none(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, step="tests")
    plan = rt.plan(StepRequest("unit-tester", "go", "s1"))
    assert "runner" not in plan.launch.mcp_servers
    assert not [t for t in plan.launch.extra_allowed if t.startswith("mcp__runner")]
    assert runner_tools.tool_names() == ["mcp__runner__run_tests", "mcp__runner__run_new_tests"]


# ----- R7: test_files ----------------------------------------------------


def test_unit_tester_commit_records_test_files(
    make_runtime, configured: Path, fake: FakeSystem
) -> None:
    fake.track()

    def both() -> None:
        write(configured, "tests/test_a.py")()
        write(configured, "tests/test_b.py")()

    q = FakeQuery(action=both)
    rt = make_runtime(q, FakeRunner({"pytest": (1, "F")}))
    st = add_story(rt, step="tests")
    run_step(rt, "unit-tester")
    assert st.test_files == ["tests/test_a.py", "tests/test_b.py"]
    st.step = "tests"
    q.action = write(configured, "tests/test_a.py", "y\n")
    run_step(rt, "unit-tester")
    assert st.test_files == ["tests/test_a.py", "tests/test_b.py"]


def test_developer_commit_records_no_test_files(
    make_runtime, configured: Path, fake: FakeSystem
) -> None:
    fake.track()
    rt = make_runtime(FakeQuery(action=write(configured, "src/a.py")), FakeRunner())
    st = add_story(rt, step="implement")
    run_step(rt, "developer-cli")
    assert st.test_files == [] and len(st.code_commits) == 1


def test_legacy_story_has_empty_test_files() -> None:
    assert StoryState("s1", "t", "tests").test_files == []


# ----- runner_tools ------------------------------------------------------


def tools(make_runtime, results=None, rows=(ROW,), story: bool = True):
    runner = FakeRunner(results)
    rt = make_runtime(FakeQuery(), runner)
    rt.config.toolchain.targeted = list(rows)
    add_story(rt, step="implement")
    plan = rt.plan(StepRequest("developer-cli", "go", "s1" if story else None))
    return RunnerTools(rt, plan), rt, runner


def call(fn, args: dict[str, Any]) -> dict[str, Any]:
    return json.loads(asyncio.run(fn(args))["content"][0]["text"])


def refused(reply: dict[str, Any]) -> str:
    assert reply["status"] == "refused"
    return reply["reason"]


def test_empty_list_is_refused(make_runtime) -> None:
    t, rt, runner = tools(make_runtime)
    before = list(runner.calls)
    assert refused(call(t.run_tests, {"tests": []})) == NO_TESTS_NAMED
    assert runner.calls == before
    assert not [e for e in rt.events.events() if e.kind == "tests-run"]


@pytest.mark.parametrize("bad", ["tests/", "tests/e2e", "-k", "tests/*.py"])
def test_non_targets_are_refused(make_runtime, bad: str) -> None:
    t, _, _ = tools(make_runtime)
    assert refused(call(t.run_tests, {"tests": [bad]})) == NOT_A_TARGET.format(test=bad)


def test_unresolved_id_is_refused(make_runtime) -> None:
    results = {LS_FILES_COMMAND.format(path="t.py", suffix=shlex.quote("*/t.py")): (0, "")}
    t, _, _ = tools(make_runtime, results)
    assert refused(call(t.run_tests, {"tests": ["t.py"]})) == UNTRACKED_TEST.format(
        test="t.py", file="t.py"
    )


def test_no_rows_is_refused(make_runtime) -> None:
    t, _, _ = tools(make_runtime, tracked(PKG_TEST), rows=())
    assert refused(call(t.run_tests, {"tests": [PKG_TEST]})) == NO_TARGETED


def test_path_under_no_root_is_refused(make_runtime) -> None:
    other = "other/tests/test_y.py"
    t, _, _ = tools(make_runtime, tracked(other))
    assert refused(call(t.run_tests, {"tests": [other]})) == NO_ROOT.format(test=other, path=other)


def test_run_tests_runs_root_relative_quoted_ids(make_runtime) -> None:
    results = {
        **tracked(PKG_TEST),
        ROW.command.replace("{tests}", "tests/test_x.py::test_y"): (3, "boom"),
    }
    t, _, runner = tools(make_runtime, results)
    reply = call(t.run_tests, {"tests": [f"{PKG_TEST}::test_y"]})
    command = ROW.command.replace("{tests}", "tests/test_x.py::test_y")
    assert reply["status"] == "ran" and "seconds" in reply
    assert reply["runs"] == [{"command": command, "exit": 3, "output": "boom"}]
    assert command in runner.calls


def test_ids_are_grouped_by_longest_root(make_runtime) -> None:
    other = f"{PKG}/sub/tests/test_s.py"
    a = Targeted(f"{PKG}/sub", "sub {tests}")
    results = {**tracked(PKG_TEST), **tracked(other), **tracked("u/test_u.py")}
    t, _, _ = tools(make_runtime, results, rows=(ROW, a, ALL))
    reply = call(t.run_tests, {"tests": [PKG_TEST, "u/test_u.py", other, f"{PKG_TEST}::t2"]})
    commands = [r["command"] for r in reply["runs"]]
    assert commands == [
        ROW.command.replace("{tests}", "tests/test_x.py tests/test_x.py::t2"),
        "pytest u/test_u.py",
        "sub tests/test_s.py",
    ]


def test_batches_quote_ids_and_keep_other_braces() -> None:
    row = Targeted("", "run {x} {tests}")
    out = runner_tools.batches(["a b/test_y.py"], runner_tools.Toolchain(targeted=[row]))
    assert out[0].command == "run {x} " + shlex.quote("a b/test_y.py")
    assert out[0].tests == ("a b/test_y.py",)


def test_located_swaps_the_file_part() -> None:
    assert (
        runner_tools.located("test_x.py::test_y", "pkg/tests/test_x.py")
        == "pkg/tests/test_x.py::test_y"
    )
    assert runner_tools.located("test_x.py", "pkg/tests/test_x.py") == "pkg/tests/test_x.py"


def test_run_logs_one_event_inside_a_chore(make_runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    results = {**tracked(PKG_TEST), ROW.command.replace("{tests}", "tests/test_x.py"): (1, "bad")}
    t, rt, _ = tools(make_runtime, results)
    seen: list[tuple[str, str | None]] = []

    @contextmanager
    def doing(what: str, story: str | None = None):
        seen.append((what, story))
        yield

    monkeypatch.setattr(rt.pulse, "doing", doing)
    call(t.run_tests, {"tests": [PKG_TEST]})
    assert seen == [("running named tests for developer-cli on s1", "s1")]
    events = [e for e in rt.events.events() if e.kind == "tests-run"]
    assert len(events) == 1 and events[0].role == "developer-cli" and events[0].story == "s1"
    assert events[0].data["tests"] == [PKG_TEST]
    assert events[0].data["exits"] == [1]
    assert isinstance(events[0].data["seconds"], float)


def test_run_new_tests_runs_recorded_existing_test_files(make_runtime, configured: Path) -> None:
    write(configured, "tests/test_a.py")()
    write(configured, "tests/helpers.py")()
    results = tracked("tests/test_a.py")
    t, rt, _ = tools(make_runtime, results, rows=(ALL,))
    rt.state.stories["s1"].test_files = [
        "tests/test_a.py",
        "tests/helpers.py",
        "tests/gone_test.py",
    ]
    reply = call(t.run_new_tests, {})
    assert [r["command"] for r in reply["runs"]] == ["pytest tests/test_a.py"]


def test_run_new_tests_with_none_left(make_runtime) -> None:
    t, _, _ = tools(make_runtime, rows=(ALL,))
    assert refused(call(t.run_new_tests, {})) == NO_NEW_TESTS.format(story="s1")


def test_run_new_tests_without_story(make_runtime) -> None:
    t, _, _ = tools(make_runtime, rows=(ALL,), story=False)
    assert refused(call(t.run_new_tests, {})) == NO_STORY


def test_server_and_text_result() -> None:
    assert set(runner_tools.SCHEMAS) == {"run_tests", "run_new_tests"}
    assert runner_tools.mcp_server is not None
    assert runner_tools.text_result({"a": 1})["content"][0]["type"] == "text"
    from agile_team import po_tools

    assert po_tools.text_result is runner_tools.text_result
