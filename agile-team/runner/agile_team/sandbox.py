"""The Customer Proxy's sandbox: one per acceptance environment, holding no source.

``ENVIRONMENT_KINDS`` is the data table that decides, per kind, which tools the
Proxy gets and how a customer reaches the product. ``prepare`` runs the
DevOps-owned prepare command; ``proxy_scope`` and ``os_sandbox_settings``
build the three read-blocking layers (tool globs, Bash hook, OS sandbox).
"""

from __future__ import annotations

import json
import os
import re
import signal
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from . import runner_venv, stages, system
from .config import Config, Environment
from .guard import Scope
from .paths import literal_root, under_root
from .process_groups import Recorded, RunnerIds, signal_child_group
from .seeds import Seeds, seed_dir

CUSTOMER_DIR = "customer"
SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
STORIES_GLOB = ".team/stories/**"
ACCEPTANCE_DIR = ".team/acceptance"
DEFAULT_PORTS = {"http": 80, "https": 443}
PROBE_ATTEMPTS = 120
PROBE_EVERY_S = 0.25
PROBE_TIMEOUT_S = 2
STOP_WAIT_S = 10
KILL_WAIT_S = 5
PORT_WAIT_S = 5
POLL_EVERY_S = 0.05
PORT_HELD = (
    "acceptance environment {name!r} did not let go of {host}:{port}: it was still in use "
    "{seconds:g}s after the service was stopped; keep the service in its start "
    "command's process group"
)
Listening = Callable[[str, int], bool]
LOG_TAIL_LINES = 20
PID_SUFFIX = ".pid"
LOG_SUFFIX = ".log"
PLAYWRIGHT = {"type": "stdio", "command": "npx", "args": ["@playwright/mcp@latest", "--headless"]}


class SandboxError(Exception):
    """The prepare step failed or the environment is unusable."""


class NotUp(SandboxError):
    """The environment's service did not come up and answer."""


class PortBusy(SandboxError):
    """The environment's port is taken by a process the runner did not start."""


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
class EnvironmentKind:
    """How the Proxy reaches one kind of product."""

    tools: tuple[str, ...]
    guidance: str
    start: Start = Start.FOREGROUND
    workdir: Workdir = Workdir.SANDBOX
    shell: Shell = Shell.ANY
    mcp: tuple[str, ...] = ()


ENVIRONMENT_KINDS: dict[str, EnvironmentKind] = {
    "package": EnvironmentKind(
        tools=("Bash", "Read", "Grep", "Glob", "Write"),
        guidance="The product is installed in your working directory. Run it the way the "
        "customer docs say. Use the installed files; do not read them.",
    ),
    "script": EnvironmentKind(
        tools=("Bash", "Read", "Grep", "Glob", "Write"),
        guidance="The shipped scripts and sample inputs are in your working directory. "
        "Run them as the customer docs describe; do not read their source.",
    ),
    "web": EnvironmentKind(
        tools=("Bash", "Read", "Write"),
        guidance="The product is a running web app at {url}. Use the browser tools as a "
        "customer would; `curl` is available for API checks.",
        start=Start.BACKGROUND,
        shell=Shell.CURL,
        mcp=("playwright",),
    ),
    "library": EnvironmentKind(
        tools=("Bash", "Read", "Grep", "Glob", "Write", "Edit"),
        guidance="Your working directory is an empty consumer project that depends on the "
        "library. Write small programs from the customer docs and run them.",
        workdir=Workdir.CONSUMER,
    ),
    "harness": EnvironmentKind(
        tools=("Bash", "Read", "Write"),
        guidance="DevOps prepared a harness. Only these commands are available: {commands}.",
        shell=Shell.LISTED,
    ),
    "manual": EnvironmentKind(
        tools=("Read", "Write"),
        guidance="The team cannot reach this product. Write a numbered, step-by-step "
        "acceptance script a human can follow, with the expected result of each step.",
    ),
    "document": EnvironmentKind(
        tools=("Read", "Grep", "Glob", "Write"),
        guidance="Nothing runs for this story: it changes prompts, docs or designs. "
        "The presentation's workspace holds the changed files. Read the guide and those "
        "files, and judge each criterion against them. Do not ask the human anything.",
    ),
}
MCP_SERVERS = {"playwright": PLAYWRIGHT}
LOCAL_SERVICE_NETWORK: dict[str, Any] = {"allowLocalBinding": True}
NETWORK_BY_START: dict[Start, dict[str, Any]] = {Start.BACKGROUND: LOCAL_SERVICE_NETWORK}


@dataclass
class Prepared:
    """A ready sandbox; ``stop`` tears down anything started in the background."""

    environment: Environment
    kind: EnvironmentKind
    repo: Path
    root: Path
    workdir: Path
    env: dict[str, str] = field(default_factory=dict)
    process: system.Process | None = None
    presentation: Path | None = None
    seeds: Seeds | None = None
    shared: tuple[str, ...] = ()

    def stop(self) -> str | None:
        """End the service's whole process group, wait for its port and drop the pid file.

        Returns why the port is still in use at the deadline (PORT_HELD), else ``None``.
        """
        held = self._end() if self.process else None
        system.remove(self.pid_file())
        return held

    def _end(self) -> str | None:
        end_group(self.process)  # type: ignore[arg-type]
        return port_released(self)

    def seed_problems(self) -> list[str]:
        """The seeds' problems (S7); [] when nothing was seeded."""
        return self.seeds.problems() if self.seeds else []

    def pid_file(self) -> Path:
        """Where the service's process group id is kept, beside the sandbox."""
        return _beside(self.root, PID_SUFFIX)

    def log_file(self) -> Path:
        """Where the service's output goes, beside the sandbox."""
        return _beside(self.root, LOG_SUFFIX)

    def address(self) -> tuple[str, int | str]:
        """The environment url's host and port (the scheme's default port; ``""`` without a url)."""
        parts = urlsplit(self.environment.url)
        return parts.hostname or "", parts.port or DEFAULT_PORTS.get(parts.scheme, "")

    def probe_url(self) -> str:
        """The url that must answer for the service to count as up."""
        return urljoin(self.environment.url, self.environment.probe)

    def guidance(self) -> str:
        """Prompt text telling the proxy how to reach this environment."""
        commands = ", ".join(self.environment.commands) or "none"
        return self.kind.guidance.format(url=self.environment.url, commands=commands)

    def expand(self, command: str) -> str:
        """Fill ``{repo}``, ``{sandbox}`` (absolute), ``{host}`` and ``{port}`` in a command."""
        for key, value in self._placeholders().items():
            command = command.replace(key, value)
        return command

    def _placeholders(self) -> dict[str, str]:
        host, port = self.address()
        paths = {"{repo}": system.resolve(self.repo), "{sandbox}": system.resolve(self.root)}
        return {**{k: str(v) for k, v in paths.items()}, "{host}": host, "{port}": str(port)}

    def bash_allowed(self) -> list[str] | None:
        """The Proxy's Bash allowlist, or ``None`` for any command."""
        lists = {Shell.CURL: ["curl"], Shell.LISTED: list(self.environment.commands)}
        return lists.get(self.kind.shell)

    def mcp_servers(self) -> dict[str, Any]:
        """MCP servers the Proxy needs (the browser for web environments)."""
        return {name: dict(MCP_SERVERS[name]) for name in self.kind.mcp}


def _signal_group(process: system.Process, sig: int) -> None:
    signal_child_group(process.pid, sig)


def _beside(root: Path, suffix: str) -> Path:
    return root.parent / f"{root.name}{suffix}"


def _recorded(pid_file: Path) -> Recorded | None:
    try:
        return Recorded(int(system.read_text(pid_file).strip()), system.stat(pid_file).mtime)
    except (OSError, ValueError):
        return None


def wait_until(done: Callable[[], bool], seconds: float) -> bool:
    """Poll ``done`` every POLL_EVERY_S; True once it holds, False at the deadline."""
    deadline = system.monotonic() + seconds
    while not done():
        if system.monotonic() >= deadline:
            return False
        system.sleep(POLL_EVERY_S)
    return True


def _group_alive(pgid: int) -> bool:
    """True while group ``pgid`` has a process we may see (signal 0 sends nothing)."""
    try:
        system.killpg(pgid, 0)
    except OSError:
        return False
    return True


def _ended(process: system.Process) -> bool:
    """True once the leader is reaped (poll reaps it) and its group is empty."""
    return process.poll() is not None and not _group_alive(process.pid)


def end_group(process: system.Process) -> None:
    """SIGTERM the child's group and wait for it to end; SIGKILL what is left (Q2, Q3)."""
    if process.poll() is not None:
        return
    _signal_group(process, signal.SIGTERM)
    if not wait_until(lambda: _ended(process), STOP_WAIT_S):
        _signal_group(process, signal.SIGKILL)
        wait_until(lambda: _ended(process), KILL_WAIT_S)


def _joined(reason: str, note: str | None) -> str:
    """``reason``, plus ``note`` on its own line when there is one."""
    return f"{reason}\n{note}" if note else reason


def _ends_within(pgid: int, seconds: float) -> bool:
    """True once the group is gone (or not ours to signal); False at the deadline."""
    return wait_until(lambda: not _group_alive(pgid), seconds)


def _end_group(recorded: Recorded) -> None:
    signal_child_group(recorded.pid, signal.SIGTERM)
    still_ours = recorded.is_ours()  # read before the wait: the group may change hands meanwhile
    if not _ends_within(recorded.pid, STOP_WAIT_S) and still_ours:
        signal_child_group(recorded.pid, signal.SIGKILL)


def _may_end(recorded: Recorded, runner_ids: RunnerIds) -> bool:
    """True when the recorded group is not the runner's and is still ours."""
    return not runner_ids.names(recorded.pid) and recorded.is_ours()


def stop_stale(root: Path, runner_ids: RunnerIds | None = None) -> None:
    """End a service an earlier step left (by its pid file) and delete the file.

    A pid the runner's ids name is never ended (s70); ``None`` reads them now.
    """
    pid_file = _beside(root, PID_SUFFIX)
    recorded = _recorded(pid_file)
    if recorded and _may_end(recorded, runner_ids or RunnerIds.current()):
        _end_group(recorded)
    system.remove(pid_file)


def http_answers(url: str) -> bool:
    """True when ``GET url`` returns 200 (and valid JSON, if it says it is JSON)."""
    try:
        reply = system.http_get(url, PROBE_TIMEOUT_S)
        if reply.status != 200:
            return False
        if reply.content_type == "application/json":
            json.loads(reply.body)
        return True
    except (OSError, ValueError):
        return False


def port_in_use(host: str, port: int) -> bool:
    """True when something accepts a TCP connection on ``host:port``."""
    try:
        system.connect((host, port))
    except OSError:
        return False
    return True


def port_released(prepared: Prepared, listening: Listening = port_in_use) -> str | None:
    """Wait up to PORT_WAIT_S until nothing listens on the environment's port (Q4).

    Returns PORT_HELD filled in when the port is still in use, else ``None``.
    """
    host, port = prepared.address()
    if not host or not port:
        return None
    if wait_until(lambda: not listening(host, int(port)), PORT_WAIT_S):
        return None
    return PORT_HELD.format(
        name=prepared.environment.name, host=host, port=port, seconds=PORT_WAIT_S
    )


Runner = Callable[[str, Prepared], int]


def run_shell(command: str, prepared: Prepared) -> int:
    """Default prepare runner: a blocking shell command in the repo."""
    code = system.run_shell(system.ShellCommand(command, prepared.repo, prepared.env))
    stages.note(command, code)
    return code


def kind_of(environment: Environment) -> EnvironmentKind:
    """The registered kind for ``environment`` (``SandboxError`` if unknown)."""
    try:
        return ENVIRONMENT_KINDS[environment.kind]
    except KeyError:
        raise SandboxError(f"unknown acceptance environment kind {environment.kind!r}") from None


def fresh_dir(path: Path) -> Path:
    """Empty ``path`` and return it."""
    if system.exists(path):
        system.remove_tree(path)
    system.make_dirs(path)
    return path


def sandbox_env(environment: Environment, root: Path) -> dict[str, str]:
    """The current environment with the environment's ``bin`` dirs prepended to PATH."""
    env = runner_venv.get_command_environ()
    path = [str(root / b) for b in environment.bin] + [env.get("PATH", "")]
    env["PATH"] = os.pathsep.join(p for p in path if p)
    return env


def sandbox_root(config: Config, environment: Environment) -> Path:
    """``.team/run/customer/<name>``; refuses names that would escape it (it gets wiped)."""
    if not SAFE_NAME.fullmatch(environment.name):
        raise SandboxError(
            f"acceptance environment name {environment.name!r} must match {SAFE_NAME.pattern}"
        )
    return config.run_dir / CUSTOMER_DIR / environment.name


@dataclass(frozen=True)
class Order:
    """What to prepare: the environment and, if any, the presentation to copy in."""

    environment: Environment
    presentation: Path | None = None
    shared: tuple[str, ...] = ()


PrepareFn = Callable[[Config, "Order"], Prepared]


@dataclass
class Preparer:
    """Builds sandboxes; the prepare runner, probe and port check are injectable."""

    runner: Runner = run_shell
    probe: Callable[[str], bool] = http_answers
    listening: Callable[[str, int], bool] = port_in_use
    attempts: int = PROBE_ATTEMPTS

    def prepare(self, config: Config, order: Order) -> Prepared:
        """Replace any stale service, lay out the sandbox, copy the presentation, then start."""
        stop_stale(sandbox_root(config, order.environment))
        prepared = layout(config, order.environment)
        prepared.shared = order.shared
        _present(prepared, order.presentation)
        launches = {Start.BACKGROUND: self._serve, Start.FOREGROUND: self._run_blocking}
        launches[prepared.kind.start](prepared, order.environment.prepare)
        return prepared

    def _run_blocking(self, prepared: Prepared, prepare: str) -> None:
        command = prepared.expand(prepare)
        if prepare and self.runner(command, prepared) != 0:
            raise SandboxError(
                f"prepare for environment {prepared.environment.name!r} failed: {command}"
            )

    def _serve(self, prepared: Prepared, prepare: str) -> None:
        if prepare:
            self._start(prepared, prepare)
        self._answered(prepared, prepare)

    def _answered(self, prepared: Prepared, prepare: str) -> None:
        try:
            self._await_answer(prepared)
        except NotUp:
            self._note_start(prepare, stages.NOT_UP)
            raise
        self._note_start(prepare, 0)

    def _note_start(self, prepare: str, code: int) -> None:
        if prepare:
            stages.note(prepare, code)

    def _start(self, prepared: Prepared, command: str) -> None:
        self._refuse_busy(prepared)
        shell = system.ShellCommand(prepared.expand(command), prepared.repo, prepared.env)
        prepared.process = system.spawn_logged(shell, prepared.log_file())
        system.write_text(prepared.pid_file(), str(prepared.process.pid))

    def _refuse_busy(self, prepared: Prepared) -> None:
        host, port = prepared.address()
        if host and port and self.listening(host, int(port)):
            raise PortBusy(
                f"acceptance environment {prepared.environment.name!r} cannot start: "
                f"{host}:{port} is already in use by a process the runner did not start; "
                "stop it or change the environment's url"
            )

    def _await_answer(self, prepared: Prepared) -> None:
        for attempt in range(self.attempts):
            if self.probe(prepared.probe_url()):
                return
            if prepared.process and prepared.process.poll() is not None:
                break
            if attempt + 1 < self.attempts:
                system.sleep(PROBE_EVERY_S)
        reason = self._not_up_reason(prepared)  # before stop(): it sets a signal exit code
        raise NotUp(_joined(reason, prepared.stop()))

    def _not_up_reason(self, prepared: Prepared) -> str:
        return "\n".join([*prepared.seed_problems(), self._start_failure(prepared)])

    def _start_failure(self, prepared: Prepared) -> str:
        name, url = prepared.environment.name, prepared.probe_url()
        tail = _log_tail(prepared.log_file())
        code = prepared.process.poll() if prepared.process else None
        if code is None:
            waited = f"{self.attempts * PROBE_EVERY_S:g}"
            return (
                f"acceptance environment {name!r} did not answer {url} within {waited}s. "
                f"Last output:\n{tail}"
            )
        return (
            f"acceptance environment {name!r} did not start: "
            f"the start command exited with code {code} "
            f"before {url} answered. Last output:\n{tail}"
        )


def _log_tail(path: Path) -> str:
    text = system.read_bytes(path).decode(errors="replace") if system.is_file(path) else ""
    lines = text.splitlines()[-LOG_TAIL_LINES:]
    return "\n".join(lines) if lines else "(no output)"


def _present(prepared: Prepared, source: Path | None) -> None:
    from . import presentation  # deferred: presentation imports this module

    if source is not None:
        prepared.presentation = presentation.copy_into(source, prepared.root)
    workspace = presentation.copied_workspace(prepared.root)
    prepared.seeds = Seeds(seed_dir(prepared.repo, prepared.environment), workspace)
    prepared.seeds.plant()


def layout(config: Config, environment: Environment) -> Prepared:
    """Wipe and recreate the environment's sandbox (and consumer project, if any)."""
    kind = kind_of(environment)
    root = fresh_dir(sandbox_root(config, environment))
    workdir = fresh_dir(root / "consumer") if kind.workdir is Workdir.CONSUMER else root
    return Prepared(environment, kind, config.repo, root, workdir, sandbox_env(environment, root))


def _rel(config: Config, path: Path) -> str:
    """A sandbox path as the guard measures it: relative to the checkout holding the run dir."""
    return path.relative_to(config.run_home or config.repo).as_posix()


def proxy_read_globs(config: Config, prepared: Prepared) -> list[str]:
    """The Proxy reads only its sandbox, the stories, its reports and the customer docs."""
    docs = config.team.docs_dir.rstrip("/")
    sandbox_glob = f"{_rel(config, prepared.root)}/**"
    return [
        sandbox_glob,
        STORIES_GLOB,
        f"{ACCEPTANCE_DIR}/**",
        f"{docs}/customer/**",
        *prepared.shared,
    ]


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
        run_home=config.run_home,
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
    acceptance environment that serves locally (``NETWORK_BY_START``), allows reaching it on
    loopback. ``tests/e2e/test_proxy_sandbox_e2e.py`` runs the bundled claude
    CLI with these settings on macOS (Seatbelt): a sandboxed ``curl`` gets 200
    from a live local service, and exits 7 when the ``network`` key is removed.
    The Linux (bubblewrap) sandbox is not verified end to end.
    """
    repo = system.resolve(config.repo)
    return {
        "sandbox": _sandbox_section(config, prepared),
        "permissions": {"deny": [d for r in forbidden_roots(config) for d in _deny_reads(repo, r)]},
    }


def _sandbox_section(config: Config, prepared: Prepared) -> dict[str, Any]:
    repo = system.resolve(config.repo)
    return {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,
        "filesystem": {"denyRead": [str(repo)], "allowRead": _allowed_reads(config, prepared)},
        **_network(prepared),
    }


def _network(prepared: Prepared) -> dict[str, Any]:
    """The ``network`` key for an environment that serves locally; nothing for the rest."""
    network = NETWORK_BY_START.get(prepared.kind.start)
    return {"network": dict(network)} if network else {}


def _allowed_reads(config: Config, prepared: Prepared) -> list[str]:
    repo = system.resolve(config.repo)
    customer_docs = repo / config.team.docs_dir / "customer"
    stories, acceptance = repo / ".team/stories", repo / ACCEPTANCE_DIR
    base = [str(system.resolve(prepared.root)), str(stories), str(acceptance), str(customer_docs)]
    return [*base, *(str(repo / p) for p in prepared.shared)]
