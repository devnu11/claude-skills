"""s99: the runner's stages are named, timed and kept as data (table, notes, events, [[tool]])."""

import asyncio
import json
from pathlib import Path

import pytest
from agile_team import (
    boundary,
    cli,
    dispatch,
    gates,
    runner_tools,
    stage_log,
    stages,
    system,
    tool_calls,
)
from agile_team import config as cfg
from agile_team.commands import TIMED_OUT, CommandShell
from agile_team.dashboard.step_times import Mark, Platform
from agile_team.events import EventKind, EventLog
from agile_team.git_ops import Git, GitError
from agile_team.upstream import command_runner

from .clock import about
from .fake_system import Done, FakeSystem, Hang

NAME = stages.Name
EXPECTED = [
    "env.prepare",
    "presentation.layout",
    "quality.lint",
    "quality.static",
    "quality.coverage",
    "checkout.guard",
    "checkout.verify",
    "gate.tests-red",
    "gate.tests-rework",
    "gate.tests+coverage",
    "gate.suite-runs",
    "gate.dispute-output",
    "gate.route-lint",
    "presentation.trial",
    "gate.green",
    "boundary.sync",
    "boundary.check",
    "boundary.push",
    "boundary.ci-wait",
    "boundary.rebase",
    "boundary.push-rebased",
    "boundary.ci-rebased",
    "runner-tool.run_tests",
    "runner-tool.run_new_tests",
    "stop.handoff",
    "stop.lint",
    "stop.suite",
    "stop.red",
    "stop.presentation",
]


class Clock:
    """A Marker handing out scripted marks."""

    def __init__(self, *marks: Mark, platform: Platform = Platform.POSIX) -> None:
        self.marks = list(marks)
        self.platform = platform

    def mark(self) -> Mark:
        return self.marks.pop(0)


FLAT = Mark(1.0, 1.0, 0.0)


def make_log(repo: Path, clock: Clock | None = None) -> stage_log.StageLog:
    return stage_log.StageLog(EventLog(repo / "ev.jsonl"), clock or Clock(*[FLAT] * 20))


def runs(log: stage_log.StageLog) -> list:
    return [e for e in log.log.events() if e.kind == EventKind.RUNNER_STAGE]


# -- the table -------------------------------------------------------------


def test_table_has_every_name_in_order() -> None:
    assert set(stages.STAGES) == set(NAME)
    assert [str(n) for n in stages.STAGES] == EXPECTED
    ends = [n for n in EXPECTED if n.startswith("boundary.")]
    assert ends[-3:] == ["boundary.rebase", "boundary.push-rebased", "boundary.ci-rebased"]
    for key, row in stages.STAGES.items():
        assert row.name == key and stages.STAGE_NAME.fullmatch(row.name)
        assert isinstance(row.when, stages.When) and isinstance(row.attach, stages.Attach)
        assert row.description


def test_only_runner_tools_use_during() -> None:
    during = {n for n, s in stages.STAGES.items() if s.when == stages.When.DURING}
    assert during == {NAME.RUN_TESTS, NAME.RUN_NEW_TESTS}


def test_boundary_rows_attach_to_boundary() -> None:
    rows = [s for n, s in stages.STAGES.items() if n.startswith("boundary.")]
    assert rows and all(s.attach == stages.Attach.BOUNDARY for s in rows)


def test_as_dict_has_four_string_keys() -> None:
    d = stages.STAGES[NAME.GATE_GREEN].as_dict()
    assert list(d) == ["name", "label", "description", "when", "attach"]
    assert d["when"] == "after" and d["attach"] == "story" and d["name"] == "gate.green"


def test_mappings_cover_their_sources() -> None:
    assert set(stages.QUALITY) == {*gates.ROUTED_COMMANDS, "coverage"}
    assert set(stages.BOUNDARY) == {str(s) for s in boundary.Stage}
    assert set(stages.RUNNER_TOOL) == set(runner_tools.SCHEMAS)


def test_runner_tool_names_equal_s98_labels() -> None:
    for tool, name in stages.RUNNER_TOOL.items():
        assert tool_calls.named(f"mcp__runner__{tool}") == name


def test_reserved_names_and_namespaces() -> None:
    assert stages.reserved("gate.tests+coverage")
    assert stages.reserved("gate.mine") and stages.reserved("po.run_role")
    assert not stages.reserved("deploy.preview")


def test_unlisted_stage_fails() -> None:
    with pytest.raises(KeyError), stages.opened("gate.nope", stages.NOWHERE):  # type: ignore[arg-type]
        pass


# -- notes -----------------------------------------------------------------


def test_note_outside_a_stage_does_nothing() -> None:
    stages.note("ls", 0)
    with stages.unlogged(NAME.GATE_GREEN) as run:
        stages.note("a", 0)
    stages.note("b", 0)
    assert run.detail == "a"


def test_note_reaches_stage_in_a_thread() -> None:
    async def go(run: stages.Run) -> None:
        await asyncio.to_thread(stages.note, "in thread", 0)

    with stages.unlogged(NAME.RUN_TESTS) as run:
        asyncio.run(go(run))
    assert run.detail == "in thread"


def test_nested_notes_go_to_innermost() -> None:
    with stages.unlogged(NAME.GATE_GREEN) as outer:
        with stages.unlogged(NAME.GATE_ROUTE_LINT) as inner:
            stages.note("inner", 0)
        stages.note("outer", 0)
    assert inner.detail == "inner" and outer.detail == "outer"


def test_first_failure_is_kept() -> None:
    run = stages.Run(stages.STAGES[NAME.GATE_GREEN], stages.NOWHERE)
    for command, code in [("a", 0), ("b", 2), ("c", 0), ("d", 3)]:
        run.note(command, code)
    assert (run.detail, run.code) == ("b", 2)


def test_latest_passing_is_kept() -> None:
    run = stages.Run(stages.STAGES[NAME.GATE_GREEN], stages.NOWHERE)
    run.note("a", 0)
    run.note("b", 0)
    assert (run.detail, run.code) == ("b", 0)


def test_opened_records_raised_and_reraises() -> None:
    with pytest.raises(ValueError), stages.unlogged(NAME.GATE_GREEN) as run:
        raise ValueError("x")
    assert run.raised == "ValueError"


def test_place_of() -> None:
    from agile_team.gates import StoryState

    assert stage_log.place_of(None) == stages.NOWHERE
    story = StoryState("s1", "One", "implement")
    assert stage_log.place_of(story) == stages.Place("s1", "implement")


# -- the event -------------------------------------------------------------


def test_event_keys_and_values(repo: Path) -> None:
    log = make_log(repo, Clock(Mark(100, 50, 0.0), Mark(702, 52, 600.0)))
    with log.within(stages.Place("s1", "implement")), log.open(NAME.GATE_TESTS_COVERAGE):
        stages.note("uv run pytest --cov -q", 0)
    (event,) = runs(log)
    assert event.role == stages.RUNNER_ROLE == "runner" and event.story == "s1"
    assert list(event.data) == [
        "stage", "when", "attach", "step", "attempt", "detail", "code", "raised",
        "started_at", "started_mono", "started_slept", "seconds",
    ]  # fmt: skip
    assert event.data == {
        "stage": "gate.tests+coverage", "when": "after", "attach": "step",
        "step": "implement", "attempt": None, "detail": "uv run pytest --cov -q", "code": 0,
        "raised": None, "started_at": 100, "started_mono": 50, "started_slept": 0.0,
        "seconds": about(2.0),
    }  # fmt: skip


def test_windows_seconds_less_sleep(repo: Path) -> None:
    log = make_log(repo, Clock(Mark(100, 50, 0.0), Mark(702, 52, 600.0), platform=Platform.WINDOWS))
    with log.open(NAME.GATE_GREEN):
        pass
    assert runs(log)[0].data["seconds"] == about(2.0)


def test_awake_gap_clamps_and_rounds() -> None:
    gap = tool_calls.awake_gap
    assert gap(Platform.POSIX, (Mark(0, 10.0, 0.0), Mark(0, 5.0, 0.0))) == 0
    assert gap(Platform.POSIX, (Mark(0, 1.0, 0.0), Mark(0, 1.12349, 0.0))) == 0.123


def test_awake_seconds_with_the_fake_machine_asleep(repo: Path, fake: FakeSystem) -> None:
    from agile_team import live

    log = stage_log.StageLog(EventLog(repo / "ev.jsonl"), live.Pulse(repo / "run"))
    with log.open(NAME.GATE_GREEN):
        fake.doze(600)
        fake.clock += 2
    assert runs(log)[0].data["seconds"] == about(2.0)


def test_no_notes_normal_exit_and_raise(repo: Path) -> None:
    log = make_log(repo)
    with log.open(NAME.GATE_GREEN):
        pass
    with pytest.raises(GitError), log.open(NAME.GATE_GREEN):
        raise GitError("boom")
    ok, bad = runs(log)
    assert (ok.data["detail"], ok.data["code"], ok.data["raised"]) == ("", 0, None)
    assert (bad.data["code"], bad.data["raised"]) == (None, "GitError")


def test_detail_masked_and_cut(repo: Path) -> None:
    log = make_log(repo)
    with log.open(NAME.GATE_GREEN):
        stages.note("TOKEN=abc uv run x", 0)
    with log.open(NAME.GATE_GREEN):
        stages.note("x" * 200, 0)
    first, second = runs(log)
    assert first.data["detail"] == "TOKEN=*** uv run x"
    assert len(second.data["detail"]) == 80


def test_within_restores_place(repo: Path) -> None:
    log = make_log(repo)
    with pytest.raises(ValueError), log.within(stages.Place("s1", "tests")):
        assert log.place.story == "s1"
        raise ValueError
    assert log.place == stages.NOWHERE
    with log.open(NAME.CHECKOUT_GUARD):
        pass
    event = runs(log)[0]
    assert event.story is None and event.data["step"] is None


def test_lost_line_does_not_stop_the_run(repo: Path) -> None:
    log = make_log(repo)

    def fail(event):
        raise OSError("disk")

    log.log.emit = fail  # type: ignore[method-assign]
    with log.open(NAME.GATE_GREEN):
        pass


def test_query_outside_a_stage_writes_no_event(repo: Path, fake: FakeSystem) -> None:
    log = make_log(repo)
    Git(repo).run("status")
    assert runs(log) == []


# -- choke points ----------------------------------------------------------


def test_command_shell_notes_exit_and_timeout(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("make",), Done(3, "bad"))
    fake.reply(("sleep",), Hang("x"))
    with stages.unlogged(NAME.GATE_GREEN) as run:
        assert CommandShell(repo, 0.3).run("make")[0] == 3
    assert (run.detail, run.code) == ("make", 3)
    with stages.unlogged(NAME.GATE_GREEN) as run:
        assert CommandShell(repo, 0.3).run("sleep 9")[0] == TIMED_OUT
    assert (run.detail, run.code) == ("sleep 9", TIMED_OUT)


def test_git_notes_its_args(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse"), Done(0, "abc\n"))
    with stages.unlogged(NAME.CHECKOUT_GUARD) as run:
        Git(repo).run("rev-parse", "HEAD")
    assert (run.detail, run.code) == ("git rev-parse HEAD", 0)


def test_command_runner_notes_exit_and_timeout(repo: Path, fake: FakeSystem) -> None:
    fake.reply(("gh", "pr"), Done(2, "no"))
    fake.reply(("gh", "run"), Hang(""))
    with stages.unlogged(NAME.BOUNDARY_CI_WAIT) as run:
        assert command_runner(repo)(["gh", "pr", "checks"], 1.0)[0] == 2
    assert (run.detail, run.code) == ("gh pr checks", 2)
    with stages.unlogged(NAME.BOUNDARY_CI_WAIT) as run:
        assert command_runner(repo)(["gh", "run", "view"], 1.0)[0] == TIMED_OUT
    assert run.code == TIMED_OUT


# -- [[tool]] --------------------------------------------------------------


def tool(name: str, description: str = "d", command: str = "c") -> dict:
    return {"name": name, "description": description, "command": command}


def load(repo: Path, *rows: dict) -> cfg.Config:
    return cfg.from_raw(repo, {"tool": list(rows)})


def test_tools_load_in_file_order(repo: Path) -> None:
    c = load(repo, tool("deploy.preview"), tool("lint-all"))
    assert [t.name for t in c.tools] == ["deploy.preview", "lint-all"]
    assert c.tools[0] == cfg.Tool("deploy.preview", "d", "c")
    assert cfg.from_raw(repo, {}).tools == []


@pytest.mark.parametrize("name", ["gate.tests+coverage", "gate.mine", "po.run_role"])
def test_clash_with_built_in_refused(repo: Path, name: str) -> None:
    with pytest.raises(cfg.ConfigError, match=r"clashes with a built-in name"):
        load(repo, tool(name))


def test_clash_message_names_the_row(repo: Path) -> None:
    with pytest.raises(cfg.ConfigError) as exc:
        load(repo, tool("gate.mine"))
    assert "[[tool]] 'gate.mine' clashes" in str(exc.value)


@pytest.mark.parametrize(
    "row",
    [tool("Deploy"), tool("ok", description="  "), tool("ok", command=""), tool("")],
)
def test_bad_rows_refused(repo: Path, row: dict) -> None:
    with pytest.raises(cfg.ConfigError):
        load(repo, row)


def test_repeated_name_refused(repo: Path) -> None:
    with pytest.raises(cfg.ConfigError, match=r"\[\[tool\]\] name 'a' is repeated"):
        load(repo, tool("a"), tool("a"))


def test_two_problems_one_message(repo: Path) -> None:
    with pytest.raises(cfg.ConfigError) as exc:
        load(repo, tool("a", description=""), tool("b", command=""))
    parts = str(exc.value).split("; ")
    assert len(parts) == 2
    assert "'a' needs a description" in parts[0] and "'b' needs a command" in parts[1]


def test_tool_is_a_devops_section() -> None:
    assert "tool" in dispatch.DEVOPS_SECTIONS


def test_tool_edit_kept_and_gates_edit_quarantined(configured: Path) -> None:
    path = configured / cfg.CONFIG_NAME
    text = system.read_text(path)

    class Committed:
        """A git whose HEAD holds the original config (the fake world has no commits)."""

        repo = configured

        def run(self, *args: str) -> str:
            return text

    system.write_text(path, text + '\n[[tool]]\nname = "x.y"\ndescription = "d"\ncommand = "c"\n')
    assert dispatch.config_edit_allowed(Committed())
    system.write_text(path, text + "\n[extra]\nk = 1\n")
    assert not dispatch.config_edit_allowed(Committed())


# -- agile-team tools ------------------------------------------------------


def test_tools_command_prints_both_lists(configured: Path, capsys) -> None:
    path = configured / cfg.CONFIG_NAME
    system.write_text(
        path,
        system.read_text(path) + '\n[[tool]]\nname = "x.y"\ndescription = "D"\ncommand = "C"\n',
    )
    assert cli.main(["--repo", str(configured), "tools"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in out["built_in"]] == EXPECTED
    assert "boundary.ci-rebased" in [r["name"] for r in out["built_in"]]
    assert list(out["built_in"][0]) == ["name", "label", "description", "when", "attach"]
    assert out["repo"] == [{"name": "x.y", "description": "D", "command": "C", "label": ""}]


def test_tools_command_refuses_broken_rows(configured: Path, capsys) -> None:
    path = configured / cfg.CONFIG_NAME
    system.write_text(
        path,
        system.read_text(path)
        + '\n[[tool]]\nname = "gate.mine"\ndescription = "D"\ncommand = "C"\n',
    )
    assert cli.main(["--repo", str(configured), "tools"]) != 0
    assert "clashes with a built-in name" in capsys.readouterr().err


def test_event_kind() -> None:
    assert EventKind.RUNNER_STAGE == "runner-stage"
