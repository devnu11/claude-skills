"""Customer sandbox: one fixture per delivery kind, plus the read-blocking layers."""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import guard, sandbox
from agile_team.config import Delivery
from agile_team.guard import Scope, ToolCall

from .conftest import GUIDE_TEXT, present


def use(scope: Scope, name: str, tool_input: dict) -> str | None:
    return guard.check_tool_use(scope, ToolCall(name, tool_input))


def load(configured: Path, *deliveries: Delivery) -> cfg.Config:
    c = cfg.load(configured)
    if deliveries:
        c.deliveries = list(deliveries)
    return c


def test_package_installs_and_runs(configured: Path) -> None:
    script = "mkdir -p {sandbox}/bin && printf '#!/bin/sh\\necho todo-ok\\n' > {sandbox}/bin/todo"
    d = Delivery("cli", "package", prepare=script + " && chmod +x {sandbox}/bin/todo", bin=["bin"])
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    out = subprocess.run(
        "todo", shell=True, env=p.env, cwd=p.workdir, capture_output=True, text=True
    )
    assert out.stdout.strip() == "todo-ok"
    assert p.workdir == configured / ".team/run/customer/cli"
    assert "do not read" in p.guidance()


def test_script_copies_and_runs(configured: Path) -> None:
    (configured / "tool.sh").write_text("echo script-ok\n")
    d = Delivery("s", "script", prepare="cp {repo}/tool.sh {sandbox}/")
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    out = subprocess.run(["sh", "tool.sh"], cwd=p.workdir, capture_output=True, text=True)
    assert out.stdout.strip() == "script-ok"


def test_prepare_failure(configured: Path) -> None:
    d = Delivery("bad", "package", prepare="exit 3")
    with pytest.raises(sandbox.SandboxError, match="prepare"):
        sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))


def test_prepare_recreates_sandbox(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    stale = configured / ".team/run/customer/cli/stale"
    stale.parent.mkdir(parents=True)
    stale.write_text("x")
    sandbox.Preparer().prepare(c, sandbox.Order(d))
    assert not stale.exists()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_web_starts_in_background_and_stops(configured: Path) -> None:
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    d = Delivery(
        "ui", "web", prepare=f"exec {sys.executable} -m http.server {port} -b 127.0.0.1", url=url
    )
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    try:
        body = _fetch(url)
        assert body is not None
        assert url in p.guidance()
        assert p.mcp_servers()["playwright"]["command"] == "npx"
    finally:
        p.stop()
    assert p.process.poll() is not None


def _fetch(url: str) -> bytes | None:
    for _ in range(50):
        try:
            return urllib.request.urlopen(url, timeout=1).read()
        except OSError:
            time.sleep(0.1)
    return None


def test_stop_escalates_to_sigkill(monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(sandbox.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(sandbox.os, "killpg", lambda pgid, sig: sent.append(sig))

    class Stubborn:
        pid = 4242

        def poll(self):
            return None

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("x", timeout)

    p = sandbox.Prepared(
        Delivery("w", "web"),
        sandbox.DELIVERY_KINDS["web"],
        Path("."),
        Path("."),
        Path("."),
        process=Stubborn(),
    )  # type: ignore[arg-type]
    p.stop()
    assert sent == [signal.SIGTERM, signal.SIGKILL]


def test_stop_ignores_vanished_group(monkeypatch) -> None:
    def gone(_pid):
        raise ProcessLookupError

    monkeypatch.setattr(sandbox.os, "getpgid", gone)
    sandbox._signal_group(type("P", (), {"pid": 1})(), signal.SIGTERM)  # type: ignore[arg-type]


def test_web_stop_kills_child_processes(configured: Path) -> None:
    pidfile = configured / "child.pid"
    d = Delivery("ui", "web", prepare=f"sleep 300 & echo $! > {pidfile}; wait")
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    for _ in range(50):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.05)
    child = int(pidfile.read_text())
    p.stop()
    time.sleep(0.2)
    assert not _alive(child)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as fh:  # a zombie still answers kill(0)
            return fh.read().split()[2] != "Z"
    except OSError:
        return True


def test_delivery_name_cannot_escape(configured: Path) -> None:
    d = Delivery("../../..", "package")
    with pytest.raises(sandbox.SandboxError, match="must match"):
        sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert (configured / "src/app.py").exists()


def test_library_consumer_project(configured: Path) -> None:
    d = Delivery("lib", "library", prepare="touch {sandbox}/built.whl")
    c = load(configured, d)
    p = sandbox.Preparer().prepare(c, sandbox.Order(d))
    assert p.workdir == p.root / "consumer" and p.workdir.is_dir()
    assert (p.root / "built.whl").exists()
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
    p = sandbox.Preparer().prepare(c, sandbox.Order(d))
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


def test_forbidden_roots_default(tmp_path: Path) -> None:
    c = cfg.from_raw(tmp_path, {"toolchain": {"globs": {"source": ["**/*.py"]}}})
    assert sandbox.forbidden_roots(c) == []


def test_os_sandbox_settings(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    p = sandbox.Preparer().prepare(c, sandbox.Order(d))
    s = sandbox.os_sandbox_settings(c, p)
    repo = str(configured.resolve())
    assert s["sandbox"]["filesystem"]["denyRead"] == [repo]
    assert str(p.root.resolve()) in s["sandbox"]["filesystem"]["allowRead"]
    assert f"Read(/{repo}/src/**)" in s["permissions"]["deny"]


def test_sandbox_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    env = sandbox.sandbox_env(Delivery("x", "package", bin=["b"]), tmp_path)
    assert env["PATH"] == os.pathsep.join([str(tmp_path / "b"), "/usr/bin"])
    monkeypatch.delenv("PATH")
    assert sandbox.sandbox_env(Delivery("x", "package"), tmp_path)["PATH"] == ""


def test_run_shell(configured: Path) -> None:
    d = Delivery("cli", "package")
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert sandbox.run_shell("exit 2", p) == 2


# ----- s13: presentation copy and acceptance reads (E7, E9) -----------------


def test_order_defaults_to_no_presentation() -> None:
    assert sandbox.Order(Delivery("cli", "package")).presentation is None


def test_prepare_copies_the_presentation_before_the_runner(configured: Path) -> None:
    d = Delivery("cli", "package", prepare="true")
    c = load(configured, d)
    seen: list[bool] = []

    def runner(_command, prepared) -> int:
        seen.append((prepared.root / "presentation" / "PRESENTATION.md").exists())
        return 0

    p = sandbox.Preparer(runner=runner).prepare(c, sandbox.Order(d, present(c, "s1")))
    assert seen == [True]
    assert p.presentation == p.root / "presentation"
    assert (p.presentation / "workspace" / "todo.txt").read_text() == "milk\n"
    assert (p.presentation / "PRESENTATION.md").read_text() == GUIDE_TEXT


def test_prepare_copies_the_presentation_before_a_background_start(configured: Path) -> None:
    d = Delivery("ui", "web", prepare="serve", url="http://x")
    c = load(configured, d)
    seen: list[bool] = []

    def popen(_command, **kw):
        seen.append((c.run_dir / "customer/ui/presentation/workspace/todo.txt").exists())
        return object()

    sandbox.Preparer(popen=popen).prepare(c, sandbox.Order(d, present(c, "s1")))
    assert seen == [True]


def test_prepare_wipes_an_old_copy_with_the_sandbox(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    source = present(c, "s1")
    sandbox.Preparer().prepare(c, sandbox.Order(d, source))
    (c.run_dir / "customer/cli/presentation/old.txt").write_text("old")
    sandbox.Preparer().prepare(c, sandbox.Order(d, source))
    assert not (c.run_dir / "customer/cli/presentation/old.txt").exists()


def test_prepare_without_a_presentation_copies_nothing(configured: Path) -> None:
    d = Delivery("cli", "package")
    p = sandbox.Preparer().prepare(load(configured, d), sandbox.Order(d))
    assert p.presentation is None
    assert not (p.root / "presentation").exists()


def test_prepare_keeps_a_symlink_in_the_copy_a_link(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    source = present(c, "s1")
    os.symlink(configured / "src/app.py", source / "workspace" / "peek.py")
    p = sandbox.Preparer().prepare(c, sandbox.Order(d, source))
    assert (p.presentation / "workspace" / "peek.py").is_symlink()


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
    assert str(configured.resolve() / ".team/acceptance") in allowed
    assert str(configured.resolve() / "src") not in allowed


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
