"""CLI wiring for every subcommand."""

import json
import signal
from pathlib import Path

import pytest
from agile_team import cli, system
from agile_team import config as cfg
from agile_team.dispatch import StepRequest
from agile_team.providers import Provider
from agile_team.relay import Note, Relay
from agile_team.state import PID_FILE, STOP_FILE

from .conftest import FakeQuery
from .fake_system import FAKE_IDS, FAKE_REPO, FREE_PORT, Done, FakeSystem


def run(*argv: str) -> int:
    return cli.main(list(argv))


def test_init_detect(repo: Path, capsys) -> None:
    assert run("--repo", str(repo), "init", "--detect") == 0
    assert json.loads(capsys.readouterr().out)["preset"] is None
    system.write_text(repo / "Cargo.toml", "")
    run("--repo", str(repo), "init", "--detect")
    assert json.loads(capsys.readouterr().out)["preset"] == "rust"


def test_init_requires_answers(repo: Path, capsys) -> None:
    assert run("--repo", str(repo), "init") == 1
    assert "--preset" in capsys.readouterr().err


def test_init_and_reinit(repo: Path, capsys, fake: FakeSystem) -> None:
    clean, dirty = Done(0, ""), Done(0, "?? .agile-team.toml\0")
    fake.reply(("git", "status"), clean, dirty, clean, clean, clean)
    args = ["--repo", str(repo), "init", "--preset", "python", "--delivery", "package"]
    assert run(*args) == 0
    assert "onboarded" in capsys.readouterr().out
    assert run(*args) == 1
    assert run(*args, "--reconfigure") == 0
    assert "nothing to change" in capsys.readouterr().out


def test_config_check(configured: Path, capsys) -> None:
    assert run("--repo", str(configured), "config", "check") == 0
    assert "config ok" in capsys.readouterr().out
    roles = configured / ".team/roles"
    system.make_dirs(roles)
    system.write_text(roles / "architect.md", "Prefer hexagonal architecture.")
    system.write_text(roles / "broken.md", "---\nextends: nope\n---\nx")
    assert run("--repo", str(configured), "config", "check") == 1
    out = capsys.readouterr().out
    assert "role broken" in out


def test_config_missing(scratch: Path, capsys) -> None:
    assert run("--repo", str(scratch), "config", "check") == 1
    assert "not found" in capsys.readouterr().err


def test_addendum_reaches_architect_prompt(configured: Path, key_home: Path) -> None:
    system.make_dirs(configured / ".team/roles")
    system.write_text(configured / ".team/roles/architect.md", "Prefer hexagonal architecture.")
    rt = cli.make_runtime(cli.Place(configured, key_home), FakeQuery())
    plan = rt.plan(StepRequest("architect", "b"))
    assert "Prefer hexagonal architecture." in plan.options.system_prompt


def any_tool(fake: FakeSystem) -> None:
    """Pretend every toolchain executable is on PATH."""
    fake.programs.update({"pytest": "/bin/pytest", "ruff": "/bin/ruff"})


def start_args(repo: Path, home: Path, *extra: str):
    return cli.build_parser().parse_args(
        ["--repo", str(repo), "--home", str(home), "start", *extra]
    )


def test_start_runs_po(configured: Path, key_home: Path, capsys, fake: FakeSystem) -> None:
    any_tool(fake)
    q = FakeQuery("PO finished")
    args = start_args(configured, key_home, "--task", "todo app", "--cadence", "until-blocker")
    assert cli.cmd_start(args, q) == 0
    assert "PO finished" in capsys.readouterr().out
    assert q.calls[0]["options"].env["ANTHROPIC_API_KEY"] == "sk-test"
    assert not system.exists(configured / ".team/run" / PID_FILE)
    state = json.loads(system.read_text(configured / ".team/run/state.json"))
    assert state["cadence"] == "until-blocker"


def test_start_refuses_dirty_tree(configured: Path, key_home: Path, fake: FakeSystem) -> None:
    any_tool(fake)
    fake.reply(("git", "status"), Done(0, "?? dirty\0"))
    with pytest.raises(cli.CliError, match="dirty"):
        cli.cmd_start(start_args(configured, key_home, "--task", "t"), FakeQuery())


def test_start_needs_task(configured: Path, key_home: Path, fake: FakeSystem) -> None:
    any_tool(fake)
    with pytest.raises(cli.CliError, match="--task"):
        cli.cmd_start(start_args(configured, key_home), FakeQuery())


def test_start_via_main_reports_missing_key(configured: Path, scratch: Path, capsys) -> None:
    assert run("--repo", str(configured), "--home", str(scratch / "x"), "start", "--task", "t") == 1
    assert "no API key" in capsys.readouterr().err


def test_status_answer_stop(configured: Path, capsys) -> None:
    run_dir = configured / ".team/run"
    Relay(run_dir).post(Note("question", "DB?", ["s1"]))
    assert run("--repo", str(configured), "status") == 0
    status = json.loads(capsys.readouterr().out)
    assert status["open_questions"][0]["id"] == "m1" and not status["running"]
    assert run("--repo", str(configured), "answer", "m1", "sqlite") == 0
    assert run("--repo", str(configured), "answer", "m9", "x") == 1
    assert run("--repo", str(configured), "stop") == 0
    assert system.exists(run_dir / STOP_FILE)


def test_status_shows_story_sprints(configured: Path, capsys) -> None:
    from agile_team import state as state_mod
    from agile_team.gates import StoryState

    st = state_mod.RunState(sprint=2)
    st.stories["s1"] = StoryState("s1", "One", "design", sprint=2)
    st.stories["s2"] = StoryState("s2", "Two", "design")
    state_mod.save(configured / ".team/run", st)
    assert run("--repo", str(configured), "status") == 0
    status = json.loads(capsys.readouterr().out)
    assert status["sprint"] == 2
    assert status["stories"]["s1"]["sprint"] == 2
    assert status["stories"]["s2"]["sprint"] is None


def test_stop_now_signals(configured: Path, fake: FakeSystem) -> None:
    run_dir = configured / ".team/run"
    system.make_dirs(run_dir)
    system.write_text(run_dir / PID_FILE, str(FAKE_IDS[0]))
    args = cli.build_parser().parse_args(["--repo", str(configured), "stop", "--now"])
    assert cli.cmd_stop(args) == 0
    assert fake.signals == [("kill", FAKE_IDS[0], signal.SIGTERM)]
    assert system.exists(run_dir / STOP_FILE)


def test_stop_now_without_a_pid_file_signals_nothing(configured: Path, fake: FakeSystem) -> None:
    args = cli.build_parser().parse_args(["--repo", str(configured), "stop", "--now"])
    assert cli.cmd_stop(args) == 0
    assert fake.signals == []
    assert system.exists(configured / ".team/run" / STOP_FILE)


def test_keyboard_interrupt(monkeypatch, configured: Path) -> None:
    def boom(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "status_report", boom)
    assert run("--repo", str(configured), "status") == 130


def test_default_query() -> None:
    from claude_agent_sdk import query

    assert cli.default_query() is query


def test_check_config_flags_bad_glob(configured: Path) -> None:
    c = cfg.load(configured)
    c.roles["developer"] = {"write": ["{nope}"]}
    assert any("placeholder" in p for p in cli.check_config(c, configured))


def test_check_config_flags_unknown_provider(configured: Path) -> None:
    c = cfg.load(configured)
    c.roles["scribe"] = {"provider": "local"}
    assert "role scribe: unknown provider 'local'; add [providers.local]" in cli.check_config(
        c, configured
    )
    c.providers["local"] = Provider("local", "http://localhost:11434")
    assert cli.check_config(c, configured) == []


def test_init_refuses_dirty_tree(repo: Path, capsys, fake: FakeSystem) -> None:
    system.write_text(repo / "wip.txt", "x")
    fake.reply(("git", "status"), Done(0, "?? wip.txt\0"))
    assert run("--repo", str(repo), "init", "--preset", "python", "--delivery", "package") == 1
    assert "dirty" in capsys.readouterr().err
    assert system.read_text(repo / "wip.txt") == "x"


def test_make_runtime_lists_secrets(configured: Path, key_home: Path) -> None:
    rt = cli.make_runtime(cli.Place(configured, key_home), FakeQuery())
    assert key_home / "secrets" in rt.secrets


def test_roles_list_shows_layers(configured: Path, isolated_global_roles: Path, capsys) -> None:
    system.make_dirs(isolated_global_roles)
    system.write_text(isolated_global_roles / "scribe.md", "Keep ADRs short.")
    system.make_dirs(configured / ".team/roles")
    system.write_text(configured / ".team/roles/scribe.md", "---\nextends: nope\n---\nbroken")
    assert run("--repo", str(configured), "roles", "list") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["_shared"] == {"layers": {"builtin": "base", "global": None, "repo": None}}
    assert out["architect"]["model"] == "opus" and out["architect"]["enabled"]
    assert out["scribe"]["layers"] == {"builtin": "base", "global": "addendum", "repo": "replace"}
    assert "unknown role" in out["scribe"]["error"]


def test_roles_scaffold_repo_and_global(
    configured: Path, isolated_global_roles: Path, capsys
) -> None:
    assert run("--repo", str(configured), "roles", "scaffold") == 0
    assert system.is_file(configured / ".team/roles/product-owner.md")
    assert "stub(s) in" in capsys.readouterr().out
    assert run("--repo", str(configured), "roles", "scaffold") == 0
    assert "nothing to add" in capsys.readouterr().out
    assert run("--repo", str(configured), "roles", "scaffold", "--global") == 0
    assert system.is_file(isolated_global_roles / "_shared.md")


def test_login_auth_runtime_carries_no_key(configured: Path, scratch: Path) -> None:
    path = configured / cfg.CONFIG_NAME
    system.write_text(path, system.read_text(path).replace("[team]\n", '[team]\nauth = "login"\n'))
    rt = cli.make_runtime(cli.Place(configured, scratch / "no-home"), FakeQuery())
    assert "ANTHROPIC_API_KEY" not in rt.env


def test_init_writes_auth(repo: Path) -> None:
    args = ["--repo", str(repo), "init", "--preset", "python", "--delivery", "package"]
    assert run(*args, "--auth", "login") == 0
    assert cfg.load(repo).team.auth == "login"


# ----- dashboard (s4) ---------------------------------------------------------


def dashboard_args(repo: Path, *extra: str):
    return cli.build_parser().parse_args(["--repo", str(repo), "dashboard", *extra])


def test_dashboard_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["dashboard"])
    assert (args.host, args.port, args.browser) == (None, 8765, cli.Browser.OPEN)
    args = cli.build_parser().parse_args(["dashboard", "--no-open", "--port", "0", "--host", "h"])
    assert (args.host, args.port, args.browser) == ("h", 0, cli.Browser.SKIP)


def test_dashboard_is_the_last_command() -> None:
    assert cli.COMMANDS[-1].name == "dashboard"


def test_dashboard_port_zero_prints_real_url_and_opens(
    configured: Path, capsys, fake: FakeSystem
) -> None:
    args = dashboard_args(configured, "--host", "127.0.0.1", "--port", "0")
    assert cli.cmd_dashboard(args) == 0
    out = capsys.readouterr().out
    assert out == f"dashboard: http://localhost:{FREE_PORT}/?token=tok1\n"
    assert fake.opened == [f"http://localhost:{FREE_PORT}/?token=tok1"]
    assert fake.servers[0].closed


def test_dashboard_no_open_skips_browser(configured: Path, capsys, fake: FakeSystem) -> None:
    args = dashboard_args(configured, "--host", "127.0.0.1", "--port", "0", "--no-open")
    assert cli.cmd_dashboard(args) == 0
    assert fake.opened == [] and len(fake.servers) == 1
    assert capsys.readouterr().out.startswith("dashboard: http://localhost:")


def test_dashboard_default_host_on_windows(configured: Path, monkeypatch, fake: FakeSystem) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    assert cli.cmd_dashboard(dashboard_args(configured, "--port", "0", "--no-open")) == 0
    assert fake.listened == [("127.0.0.1", 0)]


def test_dashboard_port_in_use(configured: Path, capsys, fake: FakeSystem) -> None:
    fake.listening.add(("127.0.0.1", 8123))
    code = run(
        "--repo", str(configured), "dashboard", "--host", "127.0.0.1",
        "--port", "8123", "--no-open",
    )  # fmt: skip
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("agile-team dashboard: cannot listen on 127.0.0.1:8123:")
    assert "in use" in err


def test_dashboard_needs_config(scratch: Path, capsys) -> None:
    assert run("--repo", str(scratch), "dashboard", "--no-open") == 1
    assert "not found" in capsys.readouterr().err


def test_start_stores_task_but_resume_keeps_it(configured: Path, key_home: Path, fake: FakeSystem):
    from agile_team import state as state_mod

    any_tool(fake)
    run_dir = configured / ".team/run"
    assert cli.cmd_start(start_args(configured, key_home, "--task", "todo app"), FakeQuery()) == 0
    assert state_mod.load(run_dir).task == "todo app"
    cli.cmd_start(start_args(configured, key_home, "--resume", "--task", "nudge"), FakeQuery())
    assert state_mod.load(run_dir).task == "todo app"


# ----- s13: init outside git (E11) and the presentation check ----------------


@pytest.fixture
def plain(scratch: Path, fake: FakeSystem) -> Path:
    """A directory outside any git work tree (git says so)."""
    fake.reply(("git", "rev-parse", "--git-dir"), Done(128, "", "fatal: not a git repository"))
    path = scratch / "plain"
    system.make_dirs(path)
    return path


INIT = ["init", "--preset", "python", "--delivery", "package"]


def test_init_outside_git_prints_the_message_and_exits_1(plain: Path, capsys) -> None:
    assert run("--repo", str(plain), *INIT) == 1
    captured = capsys.readouterr()
    expected = f"agile-team init: not a git repository: {plain}; run git init first\n"
    assert captured.err == expected
    assert "Traceback" not in captured.err and captured.out == ""
    assert list(system.list_dir(plain)) == []


def test_init_on_a_missing_path_prints_the_same_message(plain: Path, capsys) -> None:
    missing = plain / "nope"
    assert run("--repo", str(missing), *INIT) == 1
    expected = f"agile-team init: not a git repository: {missing}; run git init first\n"
    assert capsys.readouterr().err == expected


def test_init_checks_git_before_the_answers(plain: Path, capsys) -> None:
    assert run("--repo", str(plain), "init") == 1
    err = capsys.readouterr().err
    assert "not a git repository" in err and "--preset" not in err


def test_init_detect_still_works_outside_git(plain: Path, capsys) -> None:
    assert run("--repo", str(plain), "init", "--detect") == 0
    assert "preset" in json.loads(capsys.readouterr().out)


def test_pipeline_checks_the_story_presentation(configured: Path) -> None:
    from agile_team.gates import StoryState

    from .conftest import present

    config = cfg.load(configured)
    pipeline = cli.make_pipeline(config)
    story = StoryState("s4", "T", "e2e", sprint=1)
    assert "no presentation" in pipeline.checks.presentation(story)
    present(config, "s4")
    assert pipeline.checks.presentation(story) is None


# ----- s29: status shows the boundary and upstream (U26) -----------------------------


def test_status_report_has_boundary_and_upstream(configured) -> None:
    from agile_team import boundary as bd
    from agile_team import config as config_mod
    from agile_team import state as state_mod

    config = config_mod.load(configured)
    empty = cli.status_report(config)
    assert empty["boundary"] is None and empty["upstream"]["push"] == "unasked"
    assert empty["upstream"]["stack"] == []
    st = state_mod.RunState(sprint=1)
    st.boundary = bd.Boundary(bd.Edge.END, 1, stage=bd.Stage.PUSH)
    state_mod.save(config.run_dir, st)
    report = cli.status_report(config)
    assert report["boundary"]["edge"] == "end" and report["boundary"]["stage"] == "push"


def test_make_runtime_wires_the_gh_pr_service(configured: Path, key_home: Path) -> None:
    from agile_team import upstream

    rt = cli.make_runtime(cli.Place(configured, key_home), FakeQuery())
    assert isinstance(rt.prs, upstream.GhPrs)
    assert rt.upstream.target == "origin/main"


def test_cli_resolves_the_repo_once(fake: FakeSystem) -> None:
    """s26 L1: a relative ``--repo`` becomes an absolute path from the working directory."""
    import argparse

    fake.workdir = FAKE_REPO / "sub"
    args = argparse.Namespace(repo=".", home=str(FAKE_REPO / "h"))
    assert cli.repo_of(args) == FAKE_REPO / "sub"
    assert cli.Place.of(args).repo == FAKE_REPO / "sub"
    assert cli.Place.of(args).repo.is_absolute()


def test_home_defaults_to_the_users_home(fake: FakeSystem) -> None:
    import argparse

    from .fake_system import FAKE_HOME

    absent = argparse.Namespace(repo=".", home=None)
    given = argparse.Namespace(repo=".", home="/elsewhere")
    assert cli.home_of(absent) == FAKE_HOME
    assert cli.home_of(given) == Path("/elsewhere")
    assert cli.build_parser().parse_args(["status"]).home is None


def test_pid_file_records_the_runner_and_clears_a_stale_stop(fake: FakeSystem) -> None:
    run_dir = FAKE_REPO / ".team" / "run"
    system.make_dirs(run_dir)
    system.write_text(run_dir / STOP_FILE, "")
    with cli.pid_file(run_dir):
        assert system.read_text(run_dir / PID_FILE) == str(FAKE_IDS[0])
        assert not system.exists(run_dir / STOP_FILE)
    assert not system.exists(run_dir / PID_FILE)


def test_pid_file_is_removed_when_the_run_raises(fake: FakeSystem) -> None:
    run_dir = FAKE_REPO / ".team" / "run"
    with pytest.raises(RuntimeError), cli.pid_file(run_dir):
        raise RuntimeError("boom")
    assert not system.exists(run_dir / PID_FILE)


def test_request_stop_leaves_a_stop_marker(configured: Path) -> None:
    run_dir = cli._request_stop(configured)
    assert system.is_file(run_dir / STOP_FILE)
    assert system.read_text(run_dir / STOP_FILE) == ""


def test_sigterm_handler_is_registered_for_the_po_task(monkeypatch, fake: FakeSystem) -> None:
    import asyncio

    class Quiet:
        pulse = type("P", (), {"start": lambda self: None, "end": lambda self: None})()

    async def noop(runtime, start):
        return "done"

    monkeypatch.setattr(cli, "run_po", noop)
    assert asyncio.run(cli._po_until_sigterm(Quiet(), None)) == "done"
    [(sig, callback)] = fake.handlers
    assert sig == signal.SIGTERM and callback.__name__ == "cancel"
