"""s118 R10: the runner side of the tally plugin (environment, watcher, retry)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from agile_team import stages, system, tally_watch
from agile_team.commands import CommandShell

from .fake_system import FAKE_REPO, Done, FakeSystem

NAME = stages.Name
PLACE = stages.Place("s1", "implement")
TALLY = FAKE_REPO / "tally.json"
PLUGIN_NAMES = sorted(n for n in os.listdir(tally_watch.PLUGIN_DIR) if n != "__pycache__")
IMPORT_ERROR = (
    'ImportError while loading\nError importing plugin "agile_team_tally": No module named x'
)


@pytest.fixture(autouse=True)
def temp_dir(fake: FakeSystem) -> None:
    """The scratch file lives in the temp dir, which the fake does not have by default."""
    fake.dirs.add("/tmp")


def a_run() -> stages.Run:
    return stages.Run(stages.STAGES[NAME.GATE_TESTS_COVERAGE], PLACE)


# ----- the environment -----


def test_the_constants() -> None:
    assert tally_watch.PLUGIN == "agile_team_tally"
    assert tally_watch.TALLY_ENV == "AGILE_TEAM_TALLY"
    assert tally_watch.TALLY_POLL_S == 0.5
    assert tally_watch.PLUGIN_DIR.name == "pytest_plugin"
    assert tally_watch.PLUGIN_DIR.parent.name == "agile_team"


def test_the_plugin_directory_holds_only_the_plugin() -> None:
    assert PLUGIN_NAMES == ["agile_team_tally.py"]


def test_plugin_env_adds_the_directory_the_plugin_and_the_file() -> None:
    env = tally_watch.plugin_env({"PATH": "p"}, TALLY)
    assert env == {
        "PATH": "p",
        "PYTHONPATH": str(tally_watch.PLUGIN_DIR),
        "PYTEST_PLUGINS": "agile_team_tally",
        "AGILE_TEAM_TALLY": str(TALLY),
    }


def test_plugin_env_keeps_the_repos_own_entries_first() -> None:
    base = {"PYTHONPATH": "src", "PYTEST_PLUGINS": "x"}
    env = tally_watch.plugin_env(base, TALLY)
    assert env["PYTHONPATH"] == f"src{os.pathsep}{tally_watch.PLUGIN_DIR}"
    assert env["PYTEST_PLUGINS"] == "x,agile_team_tally"
    assert base == {"PYTHONPATH": "src", "PYTEST_PLUGINS": "x"}


def test_an_empty_existing_value_counts_as_none() -> None:
    env = tally_watch.plugin_env({"PYTHONPATH": "", "PYTEST_PLUGINS": ""}, TALLY)
    assert env["PYTHONPATH"] == str(tally_watch.PLUGIN_DIR)
    assert env["PYTEST_PLUGINS"] == "agile_team_tally"


def test_append_onto() -> None:
    row = tally_watch.Append("K", "v", ":")
    assert row.onto({}) == "v" and row.onto({"K": ""}) == "v" and row.onto({"K": "a"}) == "a:v"


# ----- plugin_failed -----


@pytest.mark.parametrize(
    ("output", "failed"),
    [
        (IMPORT_ERROR, True),
        ('Error importing plugin "agile_team_tally": No module named agile_team_tally', True),
        ("", False),
        ("2 passed in 0.1s", False),
        ('Error importing plugin "other": No module named other', False),
        ("agile_team_tally", False),
    ],
)
def test_plugin_failed(output: str, failed: bool) -> None:
    assert tally_watch.plugin_failed(output) is failed


# ----- TallyWatch -----


def test_look_tells_the_run_a_new_text_once(fake: FakeSystem) -> None:
    run, heard = a_run(), []
    run.listeners.append(heard.append)
    watch = tally_watch.TallyWatch(TALLY, run)
    fake.write_text(TALLY, '{"a": 1}')
    watch._look()
    watch._look()
    fake.write_text(TALLY, '{"a": 2}')
    watch._look()
    assert heard == ['{"a": 1}', '{"a": 2}']


def test_look_ignores_an_empty_file(fake: FakeSystem) -> None:
    run, heard = a_run(), []
    run.listeners.append(heard.append)
    fake.write_text(TALLY, "")
    tally_watch.TallyWatch(TALLY, run)._look()
    assert heard == []


def test_look_swallows_a_missing_file(fake: FakeSystem) -> None:
    run, heard = a_run(), []
    run.listeners.append(heard.append)
    tally_watch.TallyWatch(TALLY, run)._look()
    assert heard == []


def test_look_swallows_a_listener_that_raises(fake: FakeSystem) -> None:
    run, heard = a_run(), []

    def boom(text: str) -> None:
        raise RuntimeError(text)

    run.listeners.extend([heard.append, boom])
    fake.write_text(TALLY, "x")
    tally_watch.TallyWatch(TALLY, run)._look()
    assert heard == ["x"]


def test_stop_ends_the_thread_and_looks_once_more(fake: FakeSystem) -> None:
    run, heard = a_run(), []
    run.listeners.append(heard.append)
    fake.write_text(TALLY, "last")
    watch = tally_watch.TallyWatch(TALLY, run)
    watch.start()
    watch.stop()
    assert watch.thread is not None and not watch.thread.is_alive()
    assert watch.stopping.is_set()
    assert heard == ["last"]


def test_the_watch_loop_looks_each_poll_until_stopped(fake: FakeSystem) -> None:
    run, heard = a_run(), []
    run.listeners.append(heard.append)
    fake.write_text(TALLY, "one")
    fake.ticks = 2  # two polls pass, then the fake wait ends the loop
    start = fake.clock
    watch = tally_watch.TallyWatch(TALLY, run)
    watch._watch()
    assert heard == ["one"] and fake.clock == start + 2 * tally_watch.TALLY_POLL_S


# ----- watching -----


def test_watching_yields_the_environment_and_cleans_up(fake: FakeSystem) -> None:
    fake.env = {"PATH": "p"}
    with tally_watch.watching(a_run()) as env:
        path = Path(env["AGILE_TEAM_TALLY"])
        assert env["PATH"] == "p" and env["PYTEST_PLUGINS"] == "agile_team_tally"
        assert str(path) in fake.files
    assert str(path) not in fake.files
    removed = [str(p) for kind, p in fake.ops if kind == "remove"]
    assert str(path) in removed and str(path) + ".tmp" in removed


def test_watching_cleans_up_after_an_error(fake: FakeSystem) -> None:
    with pytest.raises(RuntimeError), tally_watch.watching(a_run()) as env:
        path = env["AGILE_TEAM_TALLY"]
        raise RuntimeError("x")
    assert path not in fake.files


def test_watching_tells_the_run_the_final_record(fake: FakeSystem) -> None:
    run, heard = a_run(), []
    run.listeners.append(heard.append)
    with tally_watch.watching(run) as env:
        fake.write_text(Path(env["AGILE_TEAM_TALLY"]), "final")
    assert heard == ["final"]


# ----- CommandShell.run -----


def test_a_command_outside_a_stage_gets_only_the_coverage_redirect(fake: FakeSystem) -> None:
    fake.env = {"PATH": "p"}
    fake.reply(("pytest",), Done(0, "ok\n"))
    assert CommandShell(FAKE_REPO).run("pytest") == (0, "ok\n")
    coverage = str(FAKE_REPO / ".team/run/.coverage")
    assert [c.env for c in fake.commands] == [{"PATH": "p", "COVERAGE_FILE": coverage}]


def test_a_command_in_a_stage_gets_the_plugin_environment(fake: FakeSystem) -> None:
    fake.env = {"PATH": "p"}
    fake.reply(("pytest",), Done(0, "ok\n"))
    with stages.opened(NAME.GATE_TESTS_COVERAGE, PLACE):
        assert CommandShell(FAKE_REPO).run("pytest") == (0, "ok\n")
    (command,) = fake.commands
    env = command.env
    assert env["PATH"] == "p" and env["PYTEST_PLUGINS"] == "agile_team_tally"
    assert env["PYTHONPATH"] == str(tally_watch.PLUGIN_DIR)
    assert env["COVERAGE_FILE"] == str(FAKE_REPO / ".team/run/.coverage")
    assert env["AGILE_TEAM_TALLY"] not in fake.files  # removed afterwards


def test_a_record_written_by_the_command_reaches_the_stage(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.reply(("pytest",), Done(0, "ok\n"))
    heard: list[str] = []
    with stages.opened(NAME.GATE_TESTS_COVERAGE, PLACE) as run:
        run.listeners.append(heard.append)
        original = system.spawn_piped

        def spawn(command: object) -> object:
            fake.write_text(Path(command.env["AGILE_TEAM_TALLY"]), "record")  # type: ignore[attr-defined]
            return original(command)

        monkeypatch.setattr(system, "spawn_piped", spawn)  # install bound the fake's method
        CommandShell(FAKE_REPO).run("pytest")
    assert heard == ["record"]


def test_an_import_failure_runs_the_command_again_without_the_plugin(fake: FakeSystem) -> None:
    fake.reply(("pytest",), Done(4, IMPORT_ERROR), Done(0, "plain\n"))
    with stages.opened(NAME.GATE_TESTS_COVERAGE, PLACE):
        assert CommandShell(FAKE_REPO).run("pytest") == (0, "plain\n")
    first, second = fake.commands
    assert "PYTEST_PLUGINS" in first.env and "PYTEST_PLUGINS" not in second.env
    assert "COVERAGE_FILE" in second.env


def test_the_second_result_is_returned_even_when_it_fails(fake: FakeSystem) -> None:
    fake.reply(("pytest",), Done(4, IMPORT_ERROR), Done(1, "2 failed\n"))
    with stages.opened(NAME.GATE_TESTS_COVERAGE, PLACE):
        assert CommandShell(FAKE_REPO).run("pytest") == (1, "2 failed\n")
    assert len(fake.commands) == 2


def test_a_zero_exit_with_the_same_text_does_not_retry(fake: FakeSystem) -> None:
    fake.reply(("pytest",), Done(0, IMPORT_ERROR))
    with stages.opened(NAME.GATE_TESTS_COVERAGE, PLACE):
        assert CommandShell(FAKE_REPO).run("pytest") == (0, IMPORT_ERROR)
    assert len(fake.commands) == 1


def test_a_failure_without_the_import_error_does_not_retry(fake: FakeSystem) -> None:
    fake.reply(("pytest",), Done(1, "1 failed\n"))
    with stages.opened(NAME.GATE_TESTS_COVERAGE, PLACE):
        assert CommandShell(FAKE_REPO).run("pytest") == (1, "1 failed\n")
    assert len(fake.commands) == 1
