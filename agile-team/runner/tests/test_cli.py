"""CLI wiring for every subcommand."""

import json
from functools import partial
from pathlib import Path

import pytest
from agile_team import cli, preflight
from agile_team import config as cfg
from agile_team.dispatch import StepRequest
from agile_team.providers import Provider
from agile_team.relay import Note, Relay
from agile_team.state import PID_FILE, STOP_FILE

from .conftest import FakeQuery


def run(*argv: str) -> int:
    return cli.main(list(argv))


def test_init_detect(repo: Path, capsys) -> None:
    assert run("--repo", str(repo), "init", "--detect") == 0
    assert json.loads(capsys.readouterr().out)["preset"] is None
    (repo / "Cargo.toml").write_text("")
    run("--repo", str(repo), "init", "--detect")
    assert json.loads(capsys.readouterr().out)["preset"] == "rust"


def test_init_requires_answers(repo: Path, capsys) -> None:
    assert run("--repo", str(repo), "init") == 1
    assert "--preset" in capsys.readouterr().err


def test_init_and_reinit(repo: Path, capsys) -> None:
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
    roles.mkdir(parents=True)
    (roles / "architect.md").write_text("Prefer hexagonal architecture.")
    (roles / "broken.md").write_text("---\nextends: nope\n---\nx")
    assert run("--repo", str(configured), "config", "check") == 1
    out = capsys.readouterr().out
    assert "role broken" in out


def test_config_missing(tmp_path: Path, capsys) -> None:
    assert run("--repo", str(tmp_path), "config", "check") == 1
    assert "not found" in capsys.readouterr().err


def test_addendum_reaches_architect_prompt(configured: Path, key_home: Path) -> None:
    (configured / ".team/roles").mkdir(parents=True)
    (configured / ".team/roles/architect.md").write_text("Prefer hexagonal architecture.")
    rt = cli.make_runtime(cli.Place(configured, key_home), FakeQuery())
    plan = rt.plan(StepRequest("architect", "b"))
    assert "Prefer hexagonal architecture." in plan.options.system_prompt


def any_tool(monkeypatch) -> None:
    """Pretend every toolchain executable is on PATH."""
    monkeypatch.setattr(cli, "Preflight", partial(preflight.Preflight, which=lambda e: e))


def start_args(repo: Path, home: Path, *extra: str):
    return cli.build_parser().parse_args(
        ["--repo", str(repo), "--home", str(home), "start", *extra]
    )


def test_start_runs_po(configured: Path, key_home: Path, capsys, monkeypatch) -> None:
    any_tool(monkeypatch)
    q = FakeQuery("PO finished")
    args = start_args(configured, key_home, "--task", "todo app", "--cadence", "until-blocker")
    assert cli.cmd_start(args, q) == 0
    assert "PO finished" in capsys.readouterr().out
    assert q.calls[0]["options"].env["ANTHROPIC_API_KEY"] == "sk-test"
    assert not (configured / ".team/run" / PID_FILE).exists()
    state = json.loads((configured / ".team/run/state.json").read_text())
    assert state["cadence"] == "until-blocker"


def test_start_refuses_dirty_tree(configured: Path, key_home: Path) -> None:
    (configured / "dirty").write_text("x")
    with pytest.raises(cli.CliError, match="dirty"):
        cli.cmd_start(start_args(configured, key_home, "--task", "t"), FakeQuery())


def test_start_needs_task(configured: Path, key_home: Path, monkeypatch) -> None:
    any_tool(monkeypatch)
    with pytest.raises(cli.CliError, match="--task"):
        cli.cmd_start(start_args(configured, key_home), FakeQuery())


def test_start_via_main_reports_missing_key(configured: Path, tmp_path: Path, capsys) -> None:
    assert (
        run("--repo", str(configured), "--home", str(tmp_path / "x"), "start", "--task", "t") == 1
    )
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
    assert (run_dir / STOP_FILE).exists()


def test_stop_now_signals(configured: Path) -> None:
    run_dir = configured / ".team/run"
    run_dir.mkdir(parents=True)
    (run_dir / PID_FILE).write_text("4242")
    sent = []
    args = cli.build_parser().parse_args(["--repo", str(configured), "stop", "--now"])
    cli.cmd_stop(args, kill=lambda pid, sig: sent.append(pid))
    assert sent == [4242]


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


def test_init_refuses_dirty_tree(repo: Path, capsys) -> None:
    (repo / "wip.txt").write_text("x")
    assert run("--repo", str(repo), "init", "--preset", "python", "--delivery", "package") == 1
    assert "dirty" in capsys.readouterr().err
    assert (repo / "wip.txt").read_text() == "x"


def test_make_runtime_lists_secrets(configured: Path, key_home: Path) -> None:
    rt = cli.make_runtime(cli.Place(configured, key_home), FakeQuery())
    assert key_home / "secrets" in rt.secrets


def test_roles_list_shows_layers(configured: Path, isolated_global_roles: Path, capsys) -> None:
    isolated_global_roles.mkdir(parents=True)
    (isolated_global_roles / "scribe.md").write_text("Keep ADRs short.")
    (configured / ".team/roles").mkdir(parents=True)
    (configured / ".team/roles/scribe.md").write_text("---\nextends: nope\n---\nbroken")
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
    assert (configured / ".team/roles/product-owner.md").is_file()
    assert "stub(s) in" in capsys.readouterr().out
    assert run("--repo", str(configured), "roles", "scaffold") == 0
    assert "nothing to add" in capsys.readouterr().out
    assert run("--repo", str(configured), "roles", "scaffold", "--global") == 0
    assert (isolated_global_roles / "_shared.md").is_file()
