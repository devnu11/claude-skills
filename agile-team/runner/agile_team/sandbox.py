"""The Customer Proxy's sandbox: one per delivery, holding no source.

``DELIVERY_KINDS`` is the data table that decides, per kind, which tools the
Proxy gets and how a customer reaches the product. ``prepare`` runs the
DevOps-owned prepare command; ``proxy_scope`` and ``os_sandbox_settings``
build the three read-blocking layers (tool globs, Bash hook, OS sandbox).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from .config import Config, Delivery
from .guard import Scope
from .paths import literal_root, under_root

CUSTOMER_DIR = "customer"
SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
STORIES_GLOB = ".team/stories/**"
ACCEPTANCE_DIR = ".team/acceptance"
DEFAULT_PORTS = {"http": 80, "https": 443}
PROBE_ATTEMPTS = 120
PROBE_EVERY_S = 0.25
PROBE_TIMEOUT_S = 2
STOP_WAIT_S = 10
LOG_TAIL_LINES = 20
PID_SUFFIX = ".pid"
LOG_SUFFIX = ".log"
PLAYWRIGHT = {"type": "stdio", "command": "npx", "args": ["@playwright/mcp@latest", "--headless"]}


class SandboxError(Exception):
    """The prepare step failed or the delivery is unusable."""


class NotUp(SandboxError):
    """The delivery's service did not come up and answer."""


class PortBusy(SandboxError):
    """The delivery's port is taken by a process the runner did not start."""


class Start(StrEnum):
    """Whether the prepare command blocks or keeps running (a server) during the step."""

    FOREGROUND = "foreground"
    BACKGROUND = "background"


class Workdir(StrEnum):
    """Where the Proxy works: the sandbox itself, or an empty consumer project in it."""

    SANDBOX = "sandbox"
    CONSUMER = "consumer"


class Shell(StrEnum):
    """Which commands the Proxy's Bash may start."""

    ANY = "any"
    CURL = "curl"
    LISTED = "listed"


@dataclass(frozen=True)
class DeliveryKind:
    """How the Proxy reaches one kind of product."""

    tools: tuple[str, ...]
    guidance: str
    start: Start = Start.FOREGROUND
    workdir: Workdir = Workdir.SANDBOX
    shell: Shell = Shell.ANY
    mcp: tuple[str, ...] = ()


DELIVERY_KINDS: dict[str, DeliveryKind] = {
    "package": DeliveryKind(
        tools=("Bash", "Read", "Grep", "Glob", "Write"),
        guidance="The product is installed in your working directory. Run it the way the "
        "customer docs say. Use the installed files; do not read them.",
    ),
    "script": DeliveryKind(
        tools=("Bash", "Read", "Grep", "Glob", "Write"),
        guidance="The shipped scripts and sample inputs are in your working directory. "
        "Run them as the customer docs describe; do not read their source.",
    ),
    "web": DeliveryKind(
        tools=("Bash", "Read", "Write"),
        guidance="The product is a running web app at {url}. Use the browser tools as a "
        "customer would; `curl` is available for API checks.",
        start=Start.BACKGROUND,
        shell=Shell.CURL,
        mcp=("playwright",),
    ),
    "library": DeliveryKind(
        tools=("Bash", "Read", "Grep", "Glob", "Write", "Edit"),
        guidance="Your working directory is an empty consumer project that depends on the "
        "library. Write small programs from the customer docs and run them.",
        workdir=Workdir.CONSUMER,
    ),
    "harness": DeliveryKind(
        tools=("Bash", "Read", "Write"),
        guidance="DevOps prepared a harness. Only these commands are available: {commands}.",
        shell=Shell.LISTED,
    ),
    "manual": DeliveryKind(
        tools=("Read", "Write"),
        guidance="The team cannot reach this product. Write a numbered, step-by-step "
        "acceptance script a human can follow, with the expected result of each step.",
    ),
}
MCP_SERVERS = {"playwright": PLAYWRIGHT}
LOCAL_SERVICE_NETWORK: dict[str, Any] = {"allowLocalBinding": True}
NETWORK_BY_START: dict[Start, dict[str, Any]] = {Start.BACKGROUND: LOCAL_SERVICE_NETWORK}


@dataclass
class Prepared:
    """A ready sandbox; ``stop`` tears down anything started in the background."""

    delivery: Delivery
    kind: DeliveryKind
    repo: Path
    root: Path
    workdir: Path
    env: dict[str, str] = field(default_factory=dict)
    process: subprocess.Popen[bytes] | None = None
    presentation: Path | None = None

    def stop(self) -> None:
        """Stop the background process and its process group, and drop the pid file."""
        if self.process and self.process.poll() is None:
            _signal_group(self.process, signal.SIGTERM)
            try:
                self.process.wait(timeout=STOP_WAIT_S)
            except subprocess.TimeoutExpired:
                _signal_group(self.process, signal.SIGKILL)
        self.pid_file().unlink(missing_ok=True)

    def pid_file(self) -> Path:
        """Where the service's process group id is kept, beside the sandbox."""
        return _beside(self.root, PID_SUFFIX)

    def log_file(self) -> Path:
        """Where the service's output goes, beside the sandbox."""
        return _beside(self.root, LOG_SUFFIX)

    def address(self) -> tuple[str, int | str]:
        """The delivery url's host and port (the scheme's default port; ``""`` without a url)."""
        parts = urlsplit(self.delivery.url)
        return parts.hostname or "", parts.port or DEFAULT_PORTS.get(parts.scheme, "")

    def probe_url(self) -> str:
        """The url that must answer for the service to count as up."""
        return urljoin(self.delivery.url, self.delivery.probe)

    def guidance(self) -> str:
        """Prompt text telling the proxy how to reach this delivery."""
        commands = ", ".join(self.delivery.commands) or "none"
        return self.kind.guidance.format(url=self.delivery.url, commands=commands)

    def expand(self, command: str) -> str:
        """Fill ``{repo}``, ``{sandbox}`` (absolute), ``{host}`` and ``{port}`` in a command."""
        for key, value in self._placeholders().items():
            command = command.replace(key, value)
        return command

    def _placeholders(self) -> dict[str, str]:
        host, port = self.address()
        paths = {"{repo}": self.repo.resolve(), "{sandbox}": self.root.resolve()}
        return {**{k: str(v) for k, v in paths.items()}, "{host}": host, "{port}": str(port)}

    def bash_allowed(self) -> list[str] | None:
        """The Proxy's Bash allowlist, or ``None`` for any command."""
        lists = {Shell.CURL: ["curl"], Shell.LISTED: list(self.delivery.commands)}
        return lists.get(self.kind.shell)

    def mcp_servers(self) -> dict[str, Any]:
        """MCP servers the Proxy needs (the browser for web deliveries)."""
        return {name: dict(MCP_SERVERS[name]) for name in self.kind.mcp}


def _signal_group(process: subprocess.Popen[bytes], sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(process.pid), sig)


def _beside(root: Path, suffix: str) -> Path:
    return root.parent / f"{root.name}{suffix}"


def _group_leader(pid: int) -> bool:
    try:
        return os.getpgid(pid) == pid
    except (ProcessLookupError, PermissionError):
        return False


def _end_group(pgid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGTERM)
        deadline = time.monotonic() + STOP_WAIT_S
        while time.monotonic() < deadline:
            os.killpg(pgid, 0)
            time.sleep(0.05)
        os.killpg(pgid, signal.SIGKILL)


def stop_stale(root: Path) -> None:
    """End a service an earlier step left (by its pid file) and delete the file."""
    pid_file = _beside(root, PID_SUFFIX)
    with contextlib.suppress(OSError, ValueError):
        pid = int(pid_file.read_text().strip())
        if _group_leader(pid):
            _end_group(pid)
    pid_file.unlink(missing_ok=True)


def http_answers(url: str) -> bool:
    """True when ``GET url`` returns 200 (and valid JSON, if it says it is JSON)."""
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_S) as response:
            body = response.read()
            if response.status != 200:
                return False
            if response.headers.get_content_type() == "application/json":
                json.loads(body)
            return True
    except (OSError, ValueError):
        return False


def port_in_use(host: str, port: int) -> bool:
    """True when something accepts a TCP connection on ``host:port``."""
    try:
        socket.create_connection((host, port), timeout=1).close()
    except OSError:
        return False
    return True


Runner = Callable[[str, Prepared], int]
Popen = Callable[..., subprocess.Popen[bytes]]


def run_shell(command: str, prepared: Prepared) -> int:
    """Default prepare runner: a blocking shell command in the repo."""
    proc = subprocess.run(command, shell=True, cwd=prepared.repo, env=prepared.env, check=False)
    return proc.returncode


def kind_of(delivery: Delivery) -> DeliveryKind:
    """The registered kind for ``delivery`` (``SandboxError`` if unknown)."""
    try:
        return DELIVERY_KINDS[delivery.kind]
    except KeyError:
        raise SandboxError(f"unknown delivery kind {delivery.kind!r}") from None


def fresh_dir(path: Path) -> Path:
    """Empty ``path`` and return it."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def sandbox_env(delivery: Delivery, root: Path) -> dict[str, str]:
    """The current environment with the delivery's ``bin`` dirs prepended to PATH."""
    env = dict(os.environ)
    path = [str(root / b) for b in delivery.bin] + [env.get("PATH", "")]
    env["PATH"] = os.pathsep.join(p for p in path if p)
    return env


def sandbox_root(config: Config, delivery: Delivery) -> Path:
    """``.team/run/customer/<name>``; refuses names that would escape it (it gets wiped)."""
    if not SAFE_NAME.fullmatch(delivery.name):
        raise SandboxError(f"delivery name {delivery.name!r} must match {SAFE_NAME.pattern}")
    return config.run_dir / CUSTOMER_DIR / delivery.name


@dataclass(frozen=True)
class Order:
    """What to prepare: the delivery and, if any, the presentation to copy in."""

    delivery: Delivery
    presentation: Path | None = None


PrepareFn = Callable[[Config, "Order"], Prepared]


@dataclass
class Preparer:
    """Builds sandboxes; the runner, popen, probe and clock are injectable for tests."""

    runner: Runner = run_shell
    popen: Popen = subprocess.Popen
    probe: Callable[[str], bool] = http_answers
    listening: Callable[[str, int], bool] = port_in_use
    sleep: Callable[[float], None] = time.sleep
    attempts: int = PROBE_ATTEMPTS

    def prepare(self, config: Config, order: Order) -> Prepared:
        """Replace any stale service, lay out the sandbox, copy the presentation, then start."""
        stop_stale(sandbox_root(config, order.delivery))
        prepared = layout(config, order.delivery)
        _copy_presentation(prepared, order.presentation)
        launches = {Start.BACKGROUND: self._serve, Start.FOREGROUND: self._run_blocking}
        launches[prepared.kind.start](prepared, order.delivery.prepare)
        return prepared

    def _run_blocking(self, prepared: Prepared, prepare: str) -> None:
        command = prepared.expand(prepare)
        if prepare and self.runner(command, prepared) != 0:
            raise SandboxError(f"prepare for delivery {prepared.delivery.name!r} failed: {command}")

    def _serve(self, prepared: Prepared, prepare: str) -> None:
        if prepare:
            self._start(prepared, prepare)
        self._await_answer(prepared)

    def _start(self, prepared: Prepared, command: str) -> None:
        self._refuse_busy(prepared)
        with prepared.log_file().open("wb") as log:
            prepared.process = self.popen(
                prepared.expand(command),
                shell=True,
                cwd=prepared.repo,
                env=prepared.env,
                start_new_session=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        prepared.pid_file().write_text(str(prepared.process.pid))

    def _refuse_busy(self, prepared: Prepared) -> None:
        host, port = prepared.address()
        if host and port and self.listening(host, int(port)):
            raise PortBusy(
                f"delivery {prepared.delivery.name!r} cannot start: {host}:{port} is already in "
                "use by a process the runner did not start; stop it or change the delivery's url"
            )

    def _await_answer(self, prepared: Prepared) -> None:
        for attempt in range(self.attempts):
            if self.probe(prepared.probe_url()):
                return
            if prepared.process and prepared.process.poll() is not None:
                break
            if attempt + 1 < self.attempts:
                self.sleep(PROBE_EVERY_S)
        reason = self._not_up_reason(prepared)  # before stop(): it sets a signal exit code
        prepared.stop()
        raise NotUp(reason)

    def _not_up_reason(self, prepared: Prepared) -> str:
        name, url = prepared.delivery.name, prepared.probe_url()
        tail = _log_tail(prepared.log_file())
        code = prepared.process.poll() if prepared.process else None
        if code is None:
            waited = f"{self.attempts * PROBE_EVERY_S:g}"
            return f"delivery {name!r} did not answer {url} within {waited}s. Last output:\n{tail}"
        return (
            f"delivery {name!r} did not start: the start command exited with code {code} "
            f"before {url} answered. Last output:\n{tail}"
        )


def _log_tail(path: Path) -> str:
    text = path.read_bytes().decode(errors="replace") if path.is_file() else ""
    lines = text.splitlines()[-LOG_TAIL_LINES:]
    return "\n".join(lines) if lines else "(no output)"


def _copy_presentation(prepared: Prepared, source: Path | None) -> None:
    if source is None:
        return
    from . import presentation  # deferred: presentation imports this module

    prepared.presentation = presentation.copy_into(source, prepared.root)


def layout(config: Config, delivery: Delivery) -> Prepared:
    """Wipe and recreate the delivery's sandbox (and consumer project, if any)."""
    kind = kind_of(delivery)
    root = fresh_dir(sandbox_root(config, delivery))
    workdir = fresh_dir(root / "consumer") if kind.workdir is Workdir.CONSUMER else root
    return Prepared(delivery, kind, config.repo, root, workdir, sandbox_env(delivery, root))


def _rel(config: Config, path: Path) -> str:
    return path.relative_to(config.repo).as_posix()


def proxy_read_globs(config: Config, prepared: Prepared) -> list[str]:
    """The Proxy reads only its sandbox, the stories, its reports and the customer docs."""
    docs = config.team.docs_dir.rstrip("/")
    sandbox_glob = f"{_rel(config, prepared.root)}/**"
    return [sandbox_glob, STORIES_GLOB, f"{ACCEPTANCE_DIR}/**", f"{docs}/customer/**"]


def forbidden_roots(config: Config) -> list[str]:
    """The outermost directories holding source or tests, which Bash may not name."""
    globs = [g for key in ("source", "tests", "e2e") for g in config.toolchain.globs.get(key, [])]
    roots = {r for r in map(literal_root, globs) if r}
    return sorted(r for r in roots if not any(o != r and under_root(r, o) for o in roots))


def _deny_reads(repo: Path, root: str) -> list[str]:
    return [f"Read(/{repo}/{root})", f"Read(/{repo}/{root}/**)"]


def proxy_scope(config: Config, prepared: Prepared) -> Scope:
    """Guard scope for a Customer Proxy step in ``prepared`` (sandbox writes only)."""
    return Scope(
        role="customer-proxy",
        repo=config.repo,
        write=[f"{_rel(config, prepared.root)}/**"],
        read=proxy_read_globs(config, prepared),
        cwd=prepared.workdir,
        **_bash_limits(config, prepared),
    )


def _bash_limits(config: Config, prepared: Prepared) -> dict[str, Any]:
    return {
        "bash_forbidden": forbidden_roots(config) or ["src"],
        "bash_allowed": prepared.bash_allowed(),
    }


def os_sandbox_settings(config: Config, prepared: Prepared) -> dict[str, Any]:
    """Claude Code settings for the Proxy's OS sandbox.

    The sandbox denies reading the repo except the allowed paths and, for a
    delivery that serves locally (``NETWORK_BY_START``), allows reaching it on
    loopback. ``tests/e2e/test_proxy_sandbox_e2e.py`` runs the bundled claude
    CLI with these settings on macOS (Seatbelt): a sandboxed ``curl`` gets 200
    from a live local service, and exits 7 when the ``network`` key is removed.
    The Linux (bubblewrap) sandbox is not verified end to end.
    """
    repo = config.repo.resolve()
    return {
        "sandbox": _sandbox_section(config, prepared),
        "permissions": {"deny": [d for r in forbidden_roots(config) for d in _deny_reads(repo, r)]},
    }


def _sandbox_section(config: Config, prepared: Prepared) -> dict[str, Any]:
    repo = config.repo.resolve()
    return {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,
        "filesystem": {"denyRead": [str(repo)], "allowRead": _allowed_reads(config, prepared)},
        **_network(prepared),
    }


def _network(prepared: Prepared) -> dict[str, Any]:
    """The ``network`` key for a delivery that serves locally; nothing for the rest."""
    network = NETWORK_BY_START.get(prepared.kind.start)
    return {"network": dict(network)} if network else {}


def _allowed_reads(config: Config, prepared: Prepared) -> list[str]:
    repo = config.repo.resolve()
    customer_docs = repo / config.team.docs_dir / "customer"
    stories, acceptance = repo / ".team/stories", repo / ACCEPTANCE_DIR
    return [str(prepared.root.resolve()), str(stories), str(acceptance), str(customer_docs)]
