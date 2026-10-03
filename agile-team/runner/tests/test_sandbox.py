"""Customer sandbox: one fixture per delivery kind, plus the read-blocking layers."""

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


def load(configured: Path, *deliveries: Delivery) -> cfg.Config:
    c = cfg.load(configured)
    if deliveries:
        c.deliveries = list(deliveries)
    return c


def test_package_installs_and_runs(configured: Path) -> None:
    script = "mkdir -p {sandbox}/bin && printf '#!/bin/sh\\necho todo-ok\\n' > {sandbox}/bin/todo"
    d = Delivery("cli", "package", prepare=script + " && chmod +x {sandbox}/bin/todo", bin=["bin"])
    p = sandbox.prepare(load(configured, d), d)
    out = subprocess.run(
        "todo", shell=True, env=p.env, cwd=p.workdir, capture_output=True, text=True
    )
    assert out.stdout.strip() == "todo-ok"
    assert p.workdir == configured / ".team/run/customer/cli"
    assert "do not read" in p.guidance()


def test_script_copies_and_runs(configured: Path) -> None:
    (configured / "tool.sh").write_text("echo script-ok\n")
    d = Delivery("s", "script", prepare="cp {repo}/tool.sh {sandbox}/")
    p = sandbox.prepare(load(configured, d), d)
    out = subprocess.run(["sh", "tool.sh"], cwd=p.workdir, capture_output=True, text=True)
    assert out.stdout.strip() == "script-ok"


def test_prepare_failure(configured: Path) -> None:
    d = Delivery("bad", "package", prepare="exit 3")
    with pytest.raises(sandbox.SandboxError, match="prepare"):
        sandbox.prepare(load(configured, d), d)


def test_prepare_recreates_sandbox(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    stale = configured / ".team/run/customer/cli/stale"
    stale.parent.mkdir(parents=True)
    stale.write_text("x")
    sandbox.prepare(c, d)
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
    p = sandbox.prepare(load(configured, d), d)
    try:
        body = _fetch(url)
        assert body is not None
        assert url in p.guidance()
        assert sandbox.mcp_servers(p)["playwright"]["command"] == "npx"
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


def test_stop_kills_stubborn_process() -> None:
    class Stubborn:
        killed = False

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("x", timeout)

        def kill(self):
            Stubborn.killed = True

    p = sandbox.Prepared(
        Delivery("w", "web"),
        sandbox.DELIVERY_KINDS["web"],
        Path("."),
        Path("."),
        process=Stubborn(),
    )  # type: ignore[arg-type]
    p.stop()
    assert Stubborn.killed


def test_library_consumer_project(configured: Path) -> None:
    d = Delivery("lib", "library", prepare="touch {sandbox}/built.whl")
    c = load(configured, d)
    p = sandbox.prepare(c, d)
    assert p.workdir == p.root / "consumer" and p.workdir.is_dir()
    assert (p.root / "built.whl").exists()
    scope = sandbox.proxy_scope(c, p, [])
    assert guard.check_tool_use(scope, "Write", {"file_path": "example.py"}) is None
    assert guard.check_tool_use(scope, "Write", {"file_path": str(configured / "src/x.py")})
    assert sandbox.mcp_servers(p) == {}


def test_harness_allows_only_listed_commands(configured: Path) -> None:
    d = Delivery("hw", "harness", commands=["drvctl", "vmrun"])
    c = load(configured, d)
    p = sandbox.prepare(c, d, runner=lambda *a: 0)
    scope = sandbox.proxy_scope(c, p, [])
    assert scope.bash_allowed == ["drvctl", "vmrun"]
    assert guard.check_bash(scope, "drvctl status; vmrun list") is None
    assert guard.check_bash(scope, "cat /etc/passwd")
    assert "drvctl, vmrun" in p.guidance()


def test_web_bash_is_curl_only(configured: Path) -> None:
    d = Delivery("ui", "web", url="http://x")
    c = load(configured, d)
    p = sandbox.prepare(c, d)
    assert sandbox.proxy_scope(c, p, []).bash_allowed == ["curl"]


def test_manual_has_no_shell(configured: Path) -> None:
    d = Delivery("hw", "manual")
    p = sandbox.prepare(load(configured, d), d)
    assert p.kind.tools == ("Write",)
    assert "acceptance script" in p.guidance()


def test_unknown_kind(configured: Path) -> None:
    with pytest.raises(sandbox.SandboxError):
        sandbox.kind_of(Delivery("x", "bogus"))


def test_proxy_cannot_read_source(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    p = sandbox.prepare(c, d)
    scope = sandbox.proxy_scope(c, p, [".team/acceptance/**"])
    assert guard.check_tool_use(scope, "Read", {"file_path": str(configured / "src/app.py")})
    assert guard.check_tool_use(scope, "Bash", {"command": "cat ../../src/x"})
    assert (
        guard.check_tool_use(scope, "Read", {"file_path": str(configured / "docs/customer/a.md")})
        is None
    )
    assert scope.bash_forbidden == ["src", "tests"]


def test_forbidden_roots_default(tmp_path: Path) -> None:
    c = cfg.from_raw(tmp_path, {"toolchain": {"globs": {"source": ["**/*.py"]}}})
    assert sandbox.forbidden_roots(c) == []


def test_os_sandbox_settings(configured: Path) -> None:
    d = Delivery("cli", "package")
    c = load(configured, d)
    p = sandbox.prepare(c, d)
    s = sandbox.os_sandbox_settings(c, p)
    repo = str(configured.resolve())
    assert s["sandbox"]["filesystem"]["denyRead"] == [repo]
    assert str(p.root.resolve()) in s["sandbox"]["filesystem"]["allowRead"]
    assert f"Read(/{repo}/src/**)" in s["permissions"]["deny"]


def test_sandbox_env(tmp_path: Path) -> None:
    env = sandbox.sandbox_env(Delivery("x", "package", bin=["b"]), tmp_path, {"PATH": "/usr/bin"})
    assert env["PATH"].startswith(str(tmp_path / "b"))
    assert sandbox.sandbox_env(Delivery("x", "package"), tmp_path, {})["PATH"] == ""


def test_run_shell(tmp_path: Path) -> None:
    assert sandbox.run_shell("exit 2", tmp_path, {}) == 2
