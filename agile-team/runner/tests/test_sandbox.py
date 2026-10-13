"""Customer sandbox: one fixture per delivery kind, plus the read-blocking layers."""

import os
import signal
from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import guard, sandbox, system
from agile_team.config import Delivery
from agile_team.guard import Scope, ToolCall

from .conftest import GUIDE_TEXT, present
from .fake_system import FAKE_REPO, FIRST_CHILD_PID, Done, FakeSystem, Hang


def use(scope: Scope, name: str, tool_input: dict) -> str | None:
    return guard.check_tool_use(scope, ToolCall(name, tool_input))


def load(configured: Path, *deliveries: Delivery) -> cfg.Config:
    c = cfg.load(configured)
    if deliveries:
        c.deliveries = list(deliveries)
    return c


def test_package_prepare_runs_in_the_repo_with_the_bin_on_the_path(
    configured: Path, fake: FakeSystem
) -> None:
    fake.env["PATH"] = "/usr/bin"
    d = Delivery("cli", "package", prepare="make install PREFIX={sandbox}", bin=["bin"])
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    root = system.resolve(p.root)
    (run,) = fake.commands
    assert run == system.ShellCommand(f"make install PREFIX={root}", configured, p.env)
    assert p.env["PATH"] == os.pathsep.join([str(p.root / "bin"), "/usr/bin"])
    assert p.workdir == configured / ".team/run/customer/cli"
    assert "do not read" in p.guidance()


def test_script_prepare_expands_the_repo_placeholder(configured: Path, fake: FakeSystem) -> None:
    d = Delivery("s", "script", prepare="cp {repo}/tool.sh {sandbox}/")
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert fake.commands[0].text == f"cp {configured}/tool.sh {system.resolve(p.root)}/"


def test_prepare_failure(configured: Path, fake: FakeSystem) -> None:
    fake.reply(("exit",), Done(3))
    d = Delivery("bad", "package", prepare="exit 3")
    with pytest.raises(sandbox.SandboxError, match="prepare"):
        sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))


def test_prepare_recreates_sandbox(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    stale = configured / ".team/run/customer/cli/stale"
    system.make_dirs(stale.parent)
    system.write_text(stale, "x")
    sandbox.Preparer().prepare(c, sandbox.Order(d))
    assert not system.exists(stale)


URL = "http://127.0.0.1:8799/"
UP = system.HttpReply(200, "text/html", b"ok")


def test_web_starts_in_background_and_stops(configured: Path, fake: FakeSystem) -> None:
    fake.reply(("serve",), Hang("serving\n"))
    fake.web[URL] = UP
    d = Delivery("ui", "web", prepare="exec serve 8799", url=URL)
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert p.process.pid == FIRST_CHILD_PID
    assert system.read_text(p.pid_file()) == str(FIRST_CHILD_PID)
    assert system.read_text(p.log_file()) == "serving\n"
    assert URL in p.guidance()
    assert p.mcp_servers()["playwright"]["command"] == "npx"
    p.stop()
    assert p.process.poll() is not None
    assert not system.exists(p.pid_file())


def test_stop_escalates_to_sigkill(fake: FakeSystem) -> None:
    fake.reply(("serve",), Hang())
    child = system.spawn_piped(system.ShellCommand("serve", FAKE_REPO))
    fake.survivors.add(child.pid)
    root = FAKE_REPO / "root"
    p = sandbox.Prepared(
        Delivery("w", "web"), sandbox.DELIVERY_KINDS["web"], FAKE_REPO, root, root, process=child
    )
    p.stop()
    assert [sig for _, _, sig in fake.signals] == [signal.SIGTERM, signal.SIGKILL]


def test_stop_ignores_vanished_group(fake: FakeSystem) -> None:
    gone = type("P", (), {"pid": FIRST_CHILD_PID + 2})()
    sandbox._signal_group(gone, signal.SIGTERM)  # type: ignore[arg-type]
    assert fake.signals == [("killpg", gone.pid, signal.SIGTERM)]  # sent, and the miss is fine


def test_web_stop_ends_child_processes(configured: Path, fake: FakeSystem) -> None:
    fake.reply(("serve",), Hang())
    d = Delivery("ui", "web", prepare="serve", url=URL)
    p = sandbox.Preparer(probe=lambda _u: True).prepare(load(configured, d), sandbox.Order(d))
    grandchild = FIRST_CHILD_PID + 100
    fake.groups[grandchild] = p.process.pid
    p.stop()
    assert grandchild not in fake.groups


def test_delivery_name_cannot_escape(configured: Path) -> None:
    d = Delivery("../../..", "package")
    with pytest.raises(sandbox.SandboxError, match="must match"):
        sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert system.exists(configured / "src/app.py")


def test_library_consumer_project(configured: Path, fake: FakeSystem) -> None:
    d = Delivery("lib", "library", prepare="touch {sandbox}/built.whl")
    c = load(configured, d)
    p = sandbox.Preparer().prepare(c, sandbox.Order(d))
    assert p.workdir == p.root / "consumer" and system.is_dir(p.workdir)
    assert fake.commands[0].text == f"touch {system.resolve(p.root)}/built.whl"
    scope = sandbox.proxy_scope(c, p)
    assert use(scope, "Write", {"file_path": "example.py"}) is None
    assert use(scope, "Write", {"file_path": str(configured / "src/x.py")})
    assert p.mcp_servers() == {}


def test_harness_allows_only_listed_commands(configured: Path) -> None:
    d = Delivery("hw", "harness", commands=["drvctl", "vmrun"])
    c = load(configured, d)
    p = sandbox.Preparer(runner=lambda *a: 0).prepare(c, sandbox.Order(d))
    scope = sandbox.proxy_scope(c, p)
    assert scope.bash_allowed == ["drvctl", "vmrun"]
    assert guard.check_bash(scope, "drvctl status; vmrun list") is None
    assert guard.check_bash(scope, "cat /etc/passwd")
    assert "drvctl, vmrun" in p.guidance()


def test_web_bash_is_curl_only(configured: Path) -> None:
    d = Delivery("ui", "web", url="http://x")
    c = load(configured, d)
    p = sandbox.Preparer(probe=lambda _u: True).prepare(c, sandbox.Order(d))
    assert sandbox.proxy_scope(c, p).bash_allowed == ["curl"]


def test_manual_has_no_shell(configured: Path) -> None:
    d = Delivery("hw", "manual")
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert p.kind.tools == ("Read", "Write")
    assert "acceptance script" in p.guidance()


def test_unknown_kind(configured: Path) -> None:
    with pytest.raises(sandbox.SandboxError):
        sandbox.kind_of(Delivery("x", "bogus"))


def test_proxy_cannot_read_source(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    p = sandbox.Preparer().prepare(c, sandbox.Order(d))
    scope = sandbox.proxy_scope(c, p)
    assert use(scope, "Read", {"file_path": str(configured / "src/app.py")})
    assert use(scope, "Bash", {"command": "cat ../../src/x"})
    assert use(scope, "Read", {"file_path": str(configured / "docs/customer/a.md")}) is None
    assert scope.bash_forbidden == ["src", "tests"]


def test_forbidden_roots_default(repo: Path) -> None:
    c = cfg.from_raw(repo, {"toolchain": {"globs": {"source": ["**/*.py"]}}})
    assert sandbox.forbidden_roots(c) == []


def test_os_sandbox_settings(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    p = sandbox.Preparer().prepare(c, sandbox.Order(d))
    s = sandbox.os_sandbox_settings(c, p)
    repo = str(system.resolve(configured))
    assert s["sandbox"]["filesystem"]["denyRead"] == [repo]
    assert str(system.resolve(p.root)) in s["sandbox"]["filesystem"]["allowRead"]
    assert f"Read(/{repo}/src/**)" in s["permissions"]["deny"]


def _settings(configured: Path, d: Delivery) -> dict:
    c = load(configured, d)
    return sandbox.os_sandbox_settings(c, sandbox.layout(c, d))


def test_web_sandbox_may_reach_loopback(configured: Path) -> None:
    s = _settings(configured, Delivery("dash", "web", url="http://127.0.0.1:8799/"))
    assert s["sandbox"]["network"] == {"allowLocalBinding": True}


def test_web_sandbox_keeps_filesystem_rules(configured: Path) -> None:
    d = Delivery("dash", "web", url="http://127.0.0.1:8799/")
    c = load(configured, d)
    p = sandbox.layout(c, d)
    s = sandbox.os_sandbox_settings(c, p)
    assert s["sandbox"]["filesystem"]["denyRead"] == [str(system.resolve(configured))]
    assert str(system.resolve(p.root)) in s["sandbox"]["filesystem"]["allowRead"]


@pytest.mark.parametrize(
    "kind",
    [k for k, v in sandbox.DELIVERY_KINDS.items() if v.start is not sandbox.Start.BACKGROUND],
)
def test_other_kinds_have_no_network_key(configured: Path, kind: str) -> None:
    assert "network" not in _settings(configured, Delivery("x", kind))["sandbox"]


def test_network_section_is_a_fresh_copy(configured: Path) -> None:
    s = _settings(configured, Delivery("dash", "web", url="http://127.0.0.1:8799/"))
    del s["sandbox"]["network"]["allowLocalBinding"]
    assert sandbox.LOCAL_SERVICE_NETWORK == {"allowLocalBinding": True}


def test_os_sandbox_docstring_names_the_e2e_test() -> None:
    doc = sandbox.os_sandbox_settings.__doc__ or ""
    assert "Not verified" not in doc and "test_proxy_sandbox_e2e" in doc


def test_sandbox_env(scratch: Path, fake: FakeSystem) -> None:
    fake.env["PATH"] = "/usr/bin"
    env = sandbox.sandbox_env(Delivery("x", "package", bin=["b"]), scratch)
    assert env["PATH"] == os.pathsep.join([str(scratch / "b"), "/usr/bin"])
    del fake.env["PATH"]
    assert sandbox.sandbox_env(Delivery("x", "package"), scratch)["PATH"] == ""


def test_sandbox_env_is_a_copy(fake: FakeSystem, scratch: Path) -> None:
    fake.env["K"] = "v"
    env = sandbox.sandbox_env(Delivery("x", "package"), scratch)
    env["K"] = "changed"
    assert fake.env["K"] == "v"


def test_run_shell(configured: Path, fake: FakeSystem) -> None:
    fake.reply(("exit",), Done(2))
    d = Delivery("cli", "package")
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert sandbox.run_shell("exit 2", p) == 2
    assert fake.commands[-1] == system.ShellCommand("exit 2", p.repo, p.env)


# ----- s13: presentation copy and acceptance reads (E7, E9) -----------------


def test_order_defaults_to_no_presentation() -> None:
    assert sandbox.Order(Delivery("cli", "package")).presentation is None


def test_prepare_copies_the_presentation_before_the_runner(configured: Path) -> None:
    d = Delivery("cli", "package", prepare="true")
    c = load(configured, d)
    seen: list[bool] = []

    def runner(_command, prepared) -> int:
        seen.append(system.exists(prepared.root / "presentation" / "PRESENTATION.md"))
        return 0

    p = sandbox.Preparer(runner=runner).prepare(c, sandbox.Order(d, present(c, "s1")))
    assert seen == [True]
    assert p.presentation == p.root / "presentation"
    assert system.read_text(p.presentation / "workspace" / "todo.txt") == "milk\n"
    assert system.read_text(p.presentation / "PRESENTATION.md") == GUIDE_TEXT


def test_prepare_copies_the_presentation_before_a_background_start(
    configured: Path, monkeypatch
) -> None:
    d = Delivery("ui", "web", prepare="serve", url="http://x")
    c = load(configured, d)
    seen: list[bool] = []
    spawn = system.spawn_logged

    def spy(command, log):
        seen.append(system.exists(c.run_dir / "customer/ui/presentation/workspace/todo.txt"))
        return spawn(command, log)

    monkeypatch.setattr(system, "spawn_logged", spy)
    sandbox.Preparer(probe=lambda _u: True, listening=lambda *_a: False).prepare(
        c, sandbox.Order(d, present(c, "s1"))
    )
    assert seen == [True]


def test_prepare_wipes_an_old_copy_with_the_sandbox(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    source = present(c, "s1")
    sandbox.Preparer().prepare(c, sandbox.Order(d, source))
    system.write_text(c.run_dir / "customer/cli/presentation/old.txt", "old")
    sandbox.Preparer().prepare(c, sandbox.Order(d, source))
    assert not system.exists(c.run_dir / "customer/cli/presentation/old.txt")


def test_prepare_without_a_presentation_copies_nothing(configured: Path) -> None:
    d = Delivery("cli", "package")
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert p.presentation is None
    assert not system.exists(p.root / "presentation")


def test_proxy_reads_the_copied_presentation_but_not_source(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    p = sandbox.Preparer().prepare(c, sandbox.Order(d, present(c, "s1")))
    scope = sandbox.proxy_scope(c, p)
    assert use(scope, "Read", {"file_path": str(p.presentation / "workspace/todo.txt")}) is None
    assert use(scope, "Read", {"file_path": str(configured / "src/app.py")})


def test_acceptance_dir_constant() -> None:
    assert sandbox.ACCEPTANCE_DIR == ".team/acceptance"


def test_proxy_reads_its_own_report_but_not_source(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    scope = sandbox.proxy_scope(c, sandbox.Preparer().prepare(c, sandbox.Order(d)))
    assert ".team/acceptance/**" in scope.read
    assert use(scope, "Read", {"file_path": str(configured / ".team/acceptance/s8.md")}) is None
    assert use(scope, "Read", {"file_path": str(configured / "src/app.py")})
    assert use(scope, "Read", {"file_path": str(configured / "tests/test_x.py")})
    assert use(scope, "Read", {"file_path": str(configured / ".team/stories/s8.md")}) is None


def test_os_sandbox_allows_reading_the_acceptance_dir(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    p = sandbox.Preparer().prepare(c, sandbox.Order(d))
    allowed = sandbox.os_sandbox_settings(c, p)["sandbox"]["filesystem"]["allowRead"]
    assert str(system.resolve(configured) / ".team/acceptance") in allowed
    assert str(system.resolve(configured) / "src") not in allowed


@pytest.mark.parametrize(
    ("kind", "tools"),
    [
        ("web", ("Bash", "Read", "Write")),
        ("harness", ("Bash", "Read", "Write")),
        ("manual", ("Read", "Write")),
    ],
)
def test_read_joins_the_restricted_kinds(kind: str, tools: tuple[str, ...]) -> None:
    assert sandbox.DELIVERY_KINDS[kind].tools == tools


# ----- s105: seeds ----------------------------------------------------------

SEED_TOML = '[dashboard]\ntoken = "presentation"\n'


def seeded(configured: Path) -> Delivery:
    system.make_dirs(configured / "seedsrc")
    system.write_text(configured / "seedsrc" / ".agile-team.toml", SEED_TOML)
    return Delivery("cli", "package", prepare="true", seed="seedsrc")


def test_prepare_plants_the_seed_before_the_runner_without_a_presentation(
    configured: Path,
) -> None:
    d = seeded(configured)
    c = load(configured, d)
    seen: list[str | None] = []

    def runner(_command, prepared) -> int:
        target = prepared.root / "presentation" / "workspace" / ".agile-team.toml"
        seen.append(system.read_text(target) if system.exists(target) else None)
        return 0

    sandbox.Preparer(runner=runner).prepare(c, sandbox.Order(d))
    assert seen == [SEED_TOML]


def test_prepare_keeps_the_workspaces_own_config_in_the_copy(configured: Path) -> None:
    d = seeded(configured)
    c = load(configured, d)
    source = present(c, "s1")
    system.write_text(source / "workspace" / ".agile-team.toml", 'x = "mine"\n')
    p = sandbox.Preparer().prepare(c, sandbox.Order(d, source))
    assert system.read_text(p.presentation / "workspace" / ".agile-team.toml") == 'x = "mine"\n'


def test_prepare_plants_into_a_copy_that_lacks_the_seed(configured: Path) -> None:
    d = seeded(configured)
    c = load(configured, d)
    p = sandbox.Preparer().prepare(c, sandbox.Order(d, present(c, "s1")))
    assert system.read_text(p.presentation / "workspace" / ".agile-team.toml") == SEED_TOML


def test_prepare_without_a_seed_plants_nothing(configured: Path) -> None:
    d = Delivery("cli", "package")
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert not system.exists(p.root / "presentation")
    assert p.seed_problems() == []


def test_seed_problems_are_empty_before_anything_is_seeded(configured: Path) -> None:
    d = seeded(configured)
    assert sandbox.layout(load(configured, d), d).seed_problems() == []


def prepared_web(configured: Path, fake: FakeSystem, **extra: str) -> sandbox.Prepared:
    """Prepare a web delivery with no presentation; its fake server hangs and answers."""
    fake.reply(("serve",), Hang())
    d = Delivery("ui", "web", prepare="serve", url=URL, **extra)
    return sandbox.Preparer(probe=lambda _u: True).prepare(load(configured, d), sandbox.Order(d))


def test_prepare_seeds_a_web_delivery_without_a_seed_key_with_the_packaged_seed(
    configured: Path, fake: FakeSystem
) -> None:
    p = prepared_web(configured, fake)
    target = p.root / "presentation" / "workspace" / ".agile-team.toml"
    assert system.read_text(target) == SEED_TOML
    assert p.seed_problems() == []


def test_prepare_with_seed_off_plants_nothing_for_web(configured: Path, fake: FakeSystem) -> None:
    p = prepared_web(configured, fake, seed="")
    assert not system.exists(p.root / "presentation" / "workspace" / ".agile-team.toml")
    assert p.seed_problems() == []
