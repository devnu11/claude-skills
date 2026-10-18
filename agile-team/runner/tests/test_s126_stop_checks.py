"""s126: each role's stop checks run as an SDK Stop hook; failures go back to the same agent."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import gates, guard, stages, stop_checks, system
from agile_team.boundary import StepKind
from agile_team.dispatch import Plan, Runtime, Said, _Drain, build_options
from agile_team.events import EventKind
from agile_team.git_ops import Git
from agile_team.roles import parse_handoff
from agile_team.stop_checks import (
    EVERY_ROLE,
    MAX_REFUSALS,
    STOP_CHECKS,
    STOP_HOOK_TIMEOUT_S,
    WAY_OUT,
    StopCheck,
    StopChecks,
)
from claude_agent_sdk import AssistantMessage, TextBlock

from .conftest import handoff
from .pipeline_helpers import add_story

COVERAGE = "pytest --cov"
GREEN = (0, "tests/test_x.py ..\nTOTAL   10   0   100%")
OWN_FAIL = (1, "FAILED tests/test_x.py::test_x - assert 1 == 2\n1 failed")
E2E_FAIL = (1, "FAILED tests/e2e/test_e.py::test_e - boom\n1 failed")
LISTING = "src/app.py\ntests/test_x.py\ntests/e2e/test_e.py\n"
STEPS = ["design", "tests", "implement", "e2e", "acceptance", "review"]


class Script:
    """Scripted gate and lint commands; records every command it is asked to run."""

    def __init__(self, suite: list[tuple[int, str]] | None = None) -> None:
        self.suite = list(suite or [GREEN])
        self.lint: tuple[int, str] = (0, "")
        self.red: tuple[int, str] = (1, "FAILED tests/test_x.py::test_x\n1 failed")
        self.calls: list[str] = []

    def __call__(self, command: str) -> tuple[int, str]:
        self.calls.append(command)
        if command == COVERAGE:
            return self.suite.pop(0) if len(self.suite) > 1 else self.suite[0]
        if "ruff check --quiet" in command:
            return self.lint
        if command == "pytest":
            return self.red
        return (0, LISTING) if command == gates.LS_ALL_COMMAND else (0, "")

    def count(self, text: str) -> int:
        return sum(text in c for c in self.calls)


@dataclass
class StubGit:
    """The two git calls the hook makes itself; the digest is whatever the test sets."""

    digest: str = "d1"

    def head(self) -> str:
        return "abc123"

    def content_digest(self, base: str) -> str:
        return self.digest

    def changed_paths(self) -> list[str]:
        return []


@dataclass
class Rig:
    rt: Runtime
    plan: Plan
    script: Script
    git: StubGit

    def say(self, status: str = "done", **extra: Any) -> None:
        self.plan.said.text = handoff(status, **extra)

    def stop(self, **input_data: Any) -> dict[str, Any]:
        data = {"hook_event_name": "Stop", "stop_hook_active": False, **input_data}
        return asyncio.run(self.plan.stop_hook.hook(data, None, None))

    def events(self, kind: EventKind) -> list[Any]:
        return [e for e in self.rt.events.events() if e.kind == kind]

    @property
    def hook(self) -> StopChecks:
        return self.plan.stop_hook


@pytest.fixture
def rig(
    make_runtime: Callable[..., Runtime], monkeypatch: pytest.MonkeyPatch
) -> Callable[..., Rig]:
    def build(
        role: str = "developer",
        step: str = "implement",
        kind: StepKind = StepKind.ROLE,
        suite: list[tuple[int, str]] | None = None,
        changed: list[str] | None = None,
    ) -> Rig:
        script = Script(suite)
        rt = make_runtime(runner=script)
        rt.pipeline.steps = list(STEPS)
        git = StubGit()
        rt.git = git
        story = add_story(rt, "s1", step)
        resolved = rt.resolve(role)
        plan = Plan(resolved, rt.scope_for(resolved), story, kind=kind)
        plan.stop_hook = StopChecks(rt, plan)
        found = changed if changed is not None else []
        monkeypatch.setattr(guard, "audit_step", lambda g, s: SimpleNamespace(in_scope=found))
        for path in found:
            system.make_dirs((rt.config.repo / path).parent)
            system.write_text(rt.config.repo / path, "x = 1\n")
        out = Rig(rt, plan, script, git)
        out.say()
        return out

    return build


# ----- the table (SC2, AC4) -----


def test_checks_for_orders_every_role_then_the_role_row() -> None:
    assert stop_checks.checks_for("developer-gui") == (
        StopCheck.HANDOFF,
        StopCheck.LINT,
        StopCheck.SUITE,
    )
    assert stop_checks.checks_for("code-reviewer") == EVERY_ROLE
    assert stop_checks.family("developer-cli") == "developer"
    assert stop_checks.family("unit-tester") == "unit-tester"


def test_table_rows() -> None:
    assert "unit-tester" not in STOP_CHECKS
    assert STOP_CHECKS["integration-tester"] == (StopCheck.PRESENTATION,)
    assert MAX_REFUSALS == 3
    assert stop_checks.SPECS[StopCheck.SUITE].step == "implement"
    assert stop_checks.SPECS[StopCheck.LINT].step is None


def test_a_new_table_row_needs_no_code(
    rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(STOP_CHECKS, "code-reviewer", (StopCheck.PRESENTATION,))
    r = rig(role="code-reviewer", step="e2e")
    r.rt.pipeline.checks.presentation = lambda story: "PRESENTATION.md is missing"
    assert "missing" in r.stop()["reason"]


# ----- developer suite (AC1, AC3, SC8, SC11, SC12) -----


def test_failing_own_test_is_refused_then_green_passes(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[OWN_FAIL, GREEN])
    refused = r.stop()
    assert refused["decision"] == "block"
    assert "FAILED tests/test_x.py::test_x" in refused["reason"]
    assert refused["reason"].endswith(WAY_OUT)
    assert "refusal 1 of 3" in refused["reason"]
    assert r.stop() == {}


def test_failures_come_shortest_first() -> None:
    text = stop_checks.refusal_text(
        [
            stop_checks.Failure(StopCheck.SUITE, "long failure text here", 1.0),
            stop_checks.Failure(StopCheck.LINT, "short", 0.5),
        ],
        stages.Attempt(1, 3),
    )
    assert text.index("[lint] short") < text.index("[suite] long failure")
    assert "refusal 1 of 3" in text and text.endswith(WAY_OUT)


def test_coverage_shortfall_is_refused_with_the_reason(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[(0, "TOTAL   10   5   50%")])
    reason = r.stop()["reason"]
    assert "[suite]" in reason and "coverage" in reason


def test_failure_only_in_another_roles_file_lets_the_stop_through(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[E2E_FAIL])
    assert r.stop() == {}
    assert r.events(EventKind.STOP_CHECK) == []


def test_timed_out_suite_is_not_refused(rig: Callable[..., Rig]) -> None:
    from agile_team.commands import TIMED_OUT

    r = rig(suite=[(TIMED_OUT, "")])
    assert r.stop() == {}


def test_suite_runs_only_at_implement(rig: Callable[..., Rig]) -> None:
    r = rig(step="review", suite=[OWN_FAIL])
    assert r.stop() == {}
    assert r.script.count(COVERAGE) == 0


def test_a_check_pointed_at_a_step_with_no_gate_passes(
    rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC9a: no gate at the step means the check passes and runs no command."""
    monkeypatch.setitem(
        stop_checks.SPECS,
        StopCheck.SUITE,
        stop_checks.Spec(stages.Name.STOP_SUITE, "review"),
    )
    r = rig(step="review", suite=[OWN_FAIL])
    assert r.stop() == {}
    assert r.script.count(COVERAGE) == 0


def test_gate_fix_step_runs_only_handoff_and_lint(rig: Callable[..., Rig]) -> None:
    r = rig(kind=StepKind.GATE_FIX, suite=[OWN_FAIL])
    assert r.stop() == {}
    assert r.script.count(COVERAGE) == 0


# ----- lint (AC2, SC7) -----


def test_lint_fixes_before_checking(rig: Callable[..., Rig]) -> None:
    r = rig(changed=["src/app.py"])
    assert r.stop() == {}
    ruff = [c for c in r.script.calls if "ruff" in c]
    assert "ruff check --fix" in ruff[0]
    assert "ruff check --quiet" in ruff[-1]
    assert all("src/app.py" in c for c in ruff)
    assert [e.data["stage"] for e in r.events(EventKind.RUNNER_STAGE)].count("stop.lint") == 1


def test_unfixable_lint_is_refused_with_its_output(rig: Callable[..., Rig]) -> None:
    r = rig(changed=["src/app.py"])
    r.script.lint = (1, "app.py:1:1: F821 undefined name")
    reason = r.stop()["reason"]
    assert "[lint]" in reason and "F821 undefined name" in reason
    assert reason.endswith(WAY_OUT)


def test_lint_skips_files_that_are_not_lintable(rig: Callable[..., Rig]) -> None:
    r = rig(changed=["docs/notes.md"])
    assert r.stop() == {}
    assert r.script.count("ruff") == 0
    stage_names = [e.data["stage"] for e in r.events(EventKind.RUNNER_STAGE)]
    assert "stop.lint" not in stage_names


def test_lint_skips_when_nothing_changed(rig: Callable[..., Rig]) -> None:
    r = rig(changed=[])
    assert r.stop() == {}
    assert r.script.count("ruff") == 0


def test_lint_skips_files_missing_on_disk(
    rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    r = rig(changed=[])
    monkeypatch.setattr(guard, "audit_step", lambda g, s: SimpleNamespace(in_scope=["src/gone.py"]))
    assert r.stop() == {}
    assert r.script.count("ruff") == 0


# ----- file_runs and config (AC2) -----


def test_file_runs_groups_by_root_in_first_seen_order() -> None:
    tc = cfg.Toolchain(
        commands={},
        targeted=[
            cfg.Targeted(root="a", command="t"),
            cfg.Targeted(root="b", command="t"),
        ],
        files=cfg.FileCommands(fix="fix {root} {files}", lint_files="lint {root} {files}"),
    )
    runs = tc.file_runs(cfg.FileCommand.FIX, ["b/x.py", "a/y.py", "b/z.py"])
    assert runs == ["fix b x.py z.py", "fix a y.py"]


def test_file_runs_without_template_is_empty() -> None:
    tc = cfg.Toolchain(commands={})
    assert tc.file_runs(cfg.FileCommand.FIX, ["x.py"]) == []


def test_file_runs_unrooted_files_use_dot() -> None:
    tc = cfg.Toolchain(commands={}, files=cfg.FileCommands(lint_files="l {root} {files}"))
    assert tc.file_runs(cfg.FileCommand.LINT, ["x.py"]) == ["l . x.py"]


def test_file_commands_template_is_a_lookup() -> None:
    fc = cfg.FileCommands(fix="f", lint_files="l")
    assert fc.template(cfg.FileCommand.FIX) == "f"
    assert fc.template(cfg.FileCommand.LINT) == "l"


def test_python_preset_supplies_files_and_config_overrides(
    make_runtime: Callable[..., Runtime],
) -> None:
    rt = make_runtime()
    files = rt.config.toolchain.files
    assert "ruff check --fix" in files.fix and "ruff check --quiet" in files.lint_files
    assert files.lintable == ("*.py",)


def test_budget_default_and_validation() -> None:
    assert cfg.Gates().stop_check_budget_s == 1800.0
    assert cfg.DEFAULT_STOP_BUDGET_S == 1800.0


# ----- the gate reuses the hook's run (SC13, AC3) -----


def test_gate_reuses_the_hooks_run_on_the_same_content(rig: Callable[..., Rig]) -> None:
    r = rig()
    assert r.stop() == {}
    assert r.script.count(COVERAGE) == 1
    out = r.hook.reusing(r.rt.pipeline).evaluate(r.plan.story, parse_handoff(r.plan.said.text))
    assert r.script.count(COVERAGE) == 1
    assert out.reason.endswith("(the stop hook's run on this tree)")


def test_proof_is_used_once(rig: Callable[..., Rig]) -> None:
    r = rig()
    r.stop()
    assert r.hook.reused() is not None
    assert r.hook.reused() is None


def test_changed_content_runs_coverage_again(rig: Callable[..., Rig]) -> None:
    r = rig()
    r.stop()
    r.git.digest = "d2"
    r.hook.reusing(r.rt.pipeline).evaluate(r.plan.story, parse_handoff(r.plan.said.text))
    assert r.script.count(COVERAGE) == 2


def test_no_proof_before_any_run(rig: Callable[..., Rig]) -> None:
    assert rig().hook.reused() is None


# ----- other roles (AC4, SC9, SC10) -----


@pytest.mark.parametrize(
    "suite", [(1, "FAILED tests/test_x.py::test_x\n1 failed"), (0, "2 passed")]
)
def test_unit_tester_is_never_refused_for_the_suite_result(
    rig: Callable[..., Rig], suite: tuple[int, str]
) -> None:
    r = rig(role="unit-tester", step="tests")
    r.script.red = suite
    assert r.stop() == {}
    assert r.hook.reused() is None


def test_presentation_missing_is_refused_and_complete_allowed(rig: Callable[..., Rig]) -> None:
    r = rig(role="integration-tester", step="e2e")
    r.rt.pipeline.checks.presentation = lambda story: "PRESENTATION.md is empty"
    assert "PRESENTATION.md is empty" in r.stop()["reason"]
    r.rt.pipeline.checks.presentation = lambda story: None
    assert r.stop() == {}


def test_presentation_not_run_without_acceptance_step(rig: Callable[..., Rig]) -> None:
    r = rig(role="integration-tester", step="e2e")
    r.rt.pipeline.steps = [s for s in STEPS if s != "acceptance"]
    r.rt.pipeline.checks.presentation = lambda story: "PRESENTATION.md is empty"
    assert r.stop() == {}


def test_bad_handoff_is_refused(rig: Callable[..., Rig]) -> None:
    r = rig()
    r.say(asserts=3)
    reason = r.stop()["reason"]
    assert "your handoff block does not parse" in reason
    assert "asserts must be a string" in reason
    assert reason.endswith(WAY_OUT)
    assert r.script.calls == []


def test_unknown_status_is_refused_not_an_escalation(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[OWN_FAIL], changed=["src/app.py"])
    r.say("odd")
    assert "your handoff block does not parse" in r.stop()["reason"]
    assert r.script.calls == []


# ----- escalation is never blocked (AC8, SC6) -----


@pytest.mark.parametrize("status", ["changes_requested", "blocked", "failed"])
def test_non_done_handoff_stops_with_no_checks(rig: Callable[..., Rig], status: str) -> None:
    r = rig(suite=[OWN_FAIL], changed=["src/app.py"])
    r.say(status)
    assert r.stop() == {}
    assert r.script.calls == []


def test_dispute_handoff_stops_with_no_checks(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[OWN_FAIL])
    r.say("changes_requested", dispute={"test": "tests/test_x.py::test_x", "rule": "SC7"})
    assert r.stop() == {}
    assert r.script.calls == []


def test_the_way_out_names_the_dispute() -> None:
    assert "changes_requested" in WAY_OUT and "dispute" in WAY_OUT


# ----- bounded (AC5, SC4, SC14, SC16) -----


def test_cap_of_three_then_the_gate_decides(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[OWN_FAIL])
    for n in (1, 2, 3):
        reason = r.stop()["reason"]
        assert f"refusal {n} of 3" in reason
    before = len(r.script.calls)
    assert r.stop() == {}
    assert len(r.script.calls) == before


def test_spent_budget_allows_the_stop_with_no_command(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[OWN_FAIL])
    r.rt.config.gates.stop_check_budget_s = 5.0
    r.hook.spent = 5.0
    assert r.stop() == {}
    assert r.script.calls == []


def test_refusal_writes_one_event_per_failure(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[OWN_FAIL], changed=["src/app.py"])
    r.script.lint = (1, "app.py:1:1: F821 undefined name")
    r.stop()
    events = r.events(EventKind.STOP_CHECK)
    assert sorted(e.data["check"] for e in events) == ["lint", "suite"]
    first = events[0]
    assert first.role == "developer" and first.story == "s1"
    assert set(first.data) == {"check", "stage", "attempt", "of", "seconds", "text"}
    assert first.data["attempt"] == 1 and first.data["of"] == 3


def test_event_text_is_capped_at_twenty_lines(rig: Callable[..., Rig]) -> None:
    long = "\n".join(f"FAILED tests/test_x.py::test_{i}" for i in range(50))
    r = rig(suite=[(1, long)])
    r.stop()
    text = r.events(EventKind.STOP_CHECK)[0].data["text"]
    assert len(text.splitlines()) <= stop_checks.EVENT_LINES == 20


def test_allowed_stop_writes_no_event(rig: Callable[..., Rig]) -> None:
    r = rig()
    assert r.stop() == {}
    assert r.events(EventKind.STOP_CHECK) == []


def test_stages_in_a_refused_attempt_carry_the_attempt(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[OWN_FAIL, OWN_FAIL])
    r.stop()
    r.stop()
    rows = [e for e in r.events(EventKind.RUNNER_STAGE) if e.data["stage"] == "stop.suite"]
    assert [e.data["attempt"] for e in rows] == [{"n": 1, "of": 3}, {"n": 2, "of": 3}]


def test_gate_stage_has_no_attempt(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[OWN_FAIL])
    r.stop()
    r.rt.pipeline.evaluate(r.plan.story, parse_handoff(r.plan.said.text))
    gate = [e for e in r.events(EventKind.RUNNER_STAGE) if e.data["stage"] == "gate.tests+coverage"]
    assert gate and all(e.data["attempt"] is None for e in gate)


def test_attempt_as_dict() -> None:
    assert stages.Attempt(2, 3).as_dict() == {"n": 2, "of": 3}


# ----- wiring (SC1, SC17, SC18) -----


def test_role_step_options_carry_a_stop_hook_with_our_timeout(rig: Callable[..., Rig]) -> None:
    r = rig()
    matchers = build_options(r.plan).hooks["Stop"]
    assert len(matchers) == 1 and matchers[0].timeout == STOP_HOOK_TIMEOUT_S
    assert STOP_HOOK_TIMEOUT_S == 86_400.0


def test_a_plan_without_a_hook_has_no_stop_entry(rig: Callable[..., Rig]) -> None:
    r = rig()
    r.plan.stop_hook = None
    assert "Stop" not in build_options(r.plan).hooks


def test_stop_hook_kinds() -> None:
    assert {StepKind.ROLE, StepKind.GATE_FIX} == stop_checks.STOP_HOOK_KINDS


def test_runtime_plan_attaches_the_hook_to_role_steps_only(rig: Callable[..., Rig]) -> None:
    from agile_team.dispatch import StepRequest

    r = rig()
    role = StepRequest("developer", "s1", "go", kind=StepKind.ROLE)
    team_fix = StepRequest("developer", "s1", "go", kind=StepKind.TEAM_FIX)
    assert isinstance(r.rt.plan(role).stop_hook, StopChecks)
    assert r.rt.plan(team_fix).stop_hook is None


def test_drain_keeps_the_latest_text_in_said() -> None:
    said = Said()
    drain = _Drain(said=said)
    drain.take(AssistantMessage(content=[TextBlock(text="one")], model="m"))
    assert said.text == "one"
    drain.take(AssistantMessage(content=[TextBlock(text="two")], model="m"))
    assert said.text == "two"


def test_input_message_wins_over_said(rig: Callable[..., Rig]) -> None:
    r = rig(suite=[OWN_FAIL])
    r.plan.said.text = "no handoff here"
    assert r.stop(last_assistant_message=handoff("blocked")) == {}
    assert r.script.calls == []


# ----- stages and the docs (AC7) -----


def test_stop_stages_are_after_step_rows() -> None:
    names = [n for n in stages.Name if str(n).startswith("stop.")]
    assert sorted(names) == sorted(
        [
            stages.Name.STOP_HANDOFF,
            stages.Name.STOP_LINT,
            stages.Name.STOP_SUITE,
            stages.Name.STOP_PRESENTATION,
            stages.Name.STOP_REQUIREMENTS,
        ]
    )
    rows = [stages.STAGES[n] for n in names]
    assert all(r.when == stages.When.AFTER and r.attach == stages.Attach.STEP for r in rows)
    labels = [r.label for r in rows]
    assert len(set(labels)) == 5 and all(len(x) <= 24 for x in labels)
    assert stages.reserved("stop.anything")


class DigestGit(Git):
    """A Git whose ``run`` answers from a table, so the digest logic runs with no process."""

    def __init__(self, diff: str, new: str = "", blob: str = "h") -> None:
        super().__init__(Path("/r"))
        self.answers = {"diff": diff, "ls-files": new}
        self.blob = blob

    def run(self, *args: str) -> str:
        if args[0] == "hash-object":
            return "\n".join(f"{self.blob}-{p}" for p in args[2:]) + "\n"
        return self.answers[args[0]]


@pytest.fixture
def on_disk(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    present: set[str] = {"a.py", "b.py", "new.py"}
    monkeypatch.setattr(system, "is_file", lambda path: path.name in present)
    return present


def test_digest_is_stable_and_ignores_listing_order(on_disk: set[str]) -> None:
    a = DigestGit("a.py\0b.py\0").content_digest("base")
    assert a == DigestGit("b.py\0a.py\0").content_digest("base")
    assert len(a) == 64


def test_digest_changes_with_a_new_untracked_file(on_disk: set[str]) -> None:
    plain = DigestGit("a.py\0").content_digest("base")
    assert plain != DigestGit("a.py\0", "new.py\0").content_digest("base")


def test_digest_changes_with_a_file_edit(on_disk: set[str]) -> None:
    before = DigestGit("a.py\0", blob="old").content_digest("base")
    assert before != DigestGit("a.py\0", blob="edited").content_digest("base")


def test_digest_marks_a_deleted_file_and_depends_on_base(on_disk: set[str]) -> None:
    kept = DigestGit("a.py\0").content_digest("base")
    on_disk.clear()
    assert DigestGit("a.py\0").content_digest("base") != kept
    assert DigestGit("").content_digest("one") != DigestGit("").content_digest("two")


def test_digest_of_a_clean_tree_runs_no_hash_object(on_disk: set[str]) -> None:
    seen: list[str] = []
    git = DigestGit("")
    git.run = lambda *a: seen.append(a[0]) or ""  # type: ignore[method-assign]
    git.content_digest("base")
    assert seen == ["diff", "ls-files"]


def _known() -> Any:
    return cfg.Known(roles=set(), environment_kinds=set())


def test_config_file_keys_override_the_preset(repo: Path) -> None:
    raw = {"toolchain": {"preset": "python", "files": {"lintable": ["*.md"], "fix": "x {files}"}}}
    files = cfg.from_raw(repo, raw).toolchain.files
    assert files.lintable == ("*.md",)
    assert files.fix == "x {files}"
    assert "ruff check --quiet" in files.lint_files


@pytest.mark.parametrize("key", ["fix", "lint_files"])
def test_a_file_template_without_files_is_a_config_error(repo: Path, key: str) -> None:
    config = cfg.from_raw(repo, {"toolchain": {"files": {key: "ruff check"}}})
    rule = "toolchain.files.fix and toolchain.files.lint_files must hold {files}"
    assert rule in cfg.validate(config, _known())


def test_a_zero_budget_is_a_config_error(repo: Path) -> None:
    config = cfg.from_raw(repo, {"gates": {"stop_check_budget_s": 0}})
    assert "gates.stop_check_budget_s must be positive" in cfg.validate(config, _known())


def test_coverage_rows_keep_misses_and_total_only() -> None:
    table = "\n".join(
        [
            "Name        Stmts   Miss  Cover",
            "a.py           10      0   100%",
            "b.py           10      3    70%",
            "TOTAL          20      3    85%",
        ]
    )
    assert stop_checks.coverage_rows(table) == [
        "b.py           10      3    70%",
        "TOTAL          20      3    85%",
    ]


REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("rel", "needle"),
    [
        ("agile_team/roles/_shared.md", "## Stop checks"),
        ("agile_team/roles/developer.md", "## Your stop check"),
        ("agile_team/roles/integration-tester.md", "presentation is complete"),
    ],
)
def test_role_files_say_what_the_stop_checks(rel: str, needle: str) -> None:
    path = Path(stop_checks.__file__).parent.parent / rel
    assert needle in system.read_text(path)


@pytest.mark.parametrize("needle", ["pending-tests", "Pending tests", '"tests": "changed"'])
def test_the_unit_tester_role_file_has_no_red_first_rule_or_tests_claim(needle: str) -> None:
    path = Path(stop_checks.__file__).parent / "roles/unit-tester.md"
    assert needle not in system.read_text(path)


def test_protocol_documents_stop_checks() -> None:
    text = system.read_text(REPO_ROOT / "agile-team/reference/protocol.md")
    assert "### Stop checks (s126)" in text
