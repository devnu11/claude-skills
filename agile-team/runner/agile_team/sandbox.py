"""The Customer Proxy's sandbox: one per delivery, holding no source.

``DELIVERY_KINDS`` is the data table that decides, per kind, which tools the
Proxy gets and how a customer reaches the product. ``prepare`` runs the
DevOps-owned prepare command; ``proxy_scope`` and ``os_sandbox_settings``
build the three read-blocking layers (tool globs, Bash hook, OS sandbox).
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config, Delivery
from .guard import Scope
from .paths import literal_root

CUSTOMER_DIR = "customer"
SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
STORIES_GLOB = ".team/stories/**"
NOTES_GLOB = ".team/acceptance/**"
PLAYWRIGHT = {"type": "stdio", "command": "npx", "args": ["@playwright/mcp@latest", "--headless"]}


class SandboxError(Exception):
    """The prepare step failed or the delivery is unusable."""


@dataclass(frozen=True)
class DeliveryKind:
    """How the Proxy reaches one kind of product."""

    tools: tuple[str, ...]
    guidance: str
    background: bool = False
    browser: bool = False
    consumer: bool = False
    allowlist: tuple[str, ...] | None = None


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
        tools=("Bash", "Write"),
        guidance="The product is a running web app at {url}. Use the browser tools as a "
        "customer would; `curl` is available for API checks.",
        background=True,
        browser=True,
        allowlist=("curl",),
    ),
    "library": DeliveryKind(
        tools=("Bash", "Read", "Grep", "Glob", "Write", "Edit"),
        guidance="Your working directory is an empty consumer project that depends on the "
        "library. Write small programs from the customer docs and run them.",
        consumer=True,
    ),
    "harness": DeliveryKind(
        tools=("Bash", "Write"),
        guidance="DevOps prepared a harness. Only these commands are available: {commands}.",
        allowlist=(),
    ),
    "manual": DeliveryKind(
        tools=("Write",),
        guidance="The team cannot reach this product. Write a numbered, step-by-step "
        "acceptance script a human can follow, with the expected result of each step.",
    ),
}

Runner = Callable[[str, Path, dict[str, str]], int]
Popen = Callable[..., subprocess.Popen[bytes]]


def run_shell(command: str, cwd: Path, env: dict[str, str]) -> int:
    """Default prepare runner: a blocking shell command."""
    return subprocess.run(command, shell=True, cwd=cwd, env=env, check=False).returncode


@dataclass
class Prepared:
    """A ready sandbox; ``stop`` tears down anything started in the background."""

    delivery: Delivery
    kind: DeliveryKind
    root: Path
    workdir: Path
    env: dict[str, str] = field(default_factory=dict)
    process: subprocess.Popen[bytes] | None = None

    def stop(self) -> None:
        """Stop the background process and everything it spawned (its process group)."""
        if self.process and self.process.poll() is None:
            _signal_group(self.process, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _signal_group(self.process, signal.SIGKILL)

    def guidance(self) -> str:
        commands = ", ".join(self.delivery.commands) or "none"
        return self.kind.guidance.format(url=self.delivery.url, commands=commands)


def _signal_group(process: subprocess.Popen[bytes], sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(process.pid), sig)


def kind_of(delivery: Delivery) -> DeliveryKind:
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


def expand(command: str, repo: Path, sandbox: Path) -> str:
    """Fill ``{repo}`` and ``{sandbox}`` in a prepare command."""
    return command.replace("{repo}", str(repo)).replace("{sandbox}", str(sandbox))


def sandbox_env(
    delivery: Delivery, root: Path, base: dict[str, str] | None = None
) -> dict[str, str]:
    """``base`` (default: os.environ) with the delivery's ``bin`` dirs prepended to PATH."""
    env = dict(os.environ if base is None else base)
    extra = [str(root / b) for b in delivery.bin]
    env["PATH"] = os.pathsep.join([*extra, env.get("PATH", "")]) if extra else env.get("PATH", "")
    return env


def sandbox_root(config: Config, delivery: Delivery) -> Path:
    """``.team/run/customer/<name>``; refuses names that would escape it (it gets wiped)."""
    if not SAFE_NAME.fullmatch(delivery.name):
        raise SandboxError(f"delivery name {delivery.name!r} must match {SAFE_NAME.pattern}")
    return config.run_dir / CUSTOMER_DIR / delivery.name


def prepare(
    config: Config,
    delivery: Delivery,
    runner: Runner = run_shell,
    popen: Popen = subprocess.Popen,
) -> Prepared:
    """Create a clean sandbox and run the delivery's prepare step."""
    kind = kind_of(delivery)
    root = fresh_dir(sandbox_root(config, delivery))
    workdir = fresh_dir(root / "consumer") if kind.consumer else root
    prepared = Prepared(delivery, kind, root, workdir, sandbox_env(delivery, root))
    if delivery.prepare:
        command = expand(delivery.prepare, config.repo, root)
        if kind.background:
            prepared.process = popen(
                command, shell=True, cwd=config.repo, env=prepared.env, start_new_session=True
            )
        elif runner(command, config.repo, prepared.env) != 0:
            raise SandboxError(f"prepare for delivery {delivery.name!r} failed: {command}")
    return prepared


def _rel(config: Config, path: Path) -> str:
    return path.relative_to(config.repo).as_posix()


def proxy_read_globs(config: Config, prepared: Prepared) -> list[str]:
    """The Proxy reads only its sandbox, the stories and the customer docs."""
    docs = config.team.docs_dir.rstrip("/")
    return [f"{_rel(config, prepared.root)}/**", STORIES_GLOB, f"{docs}/customer/**"]


def forbidden_roots(config: Config) -> list[str]:
    """Top-level directories holding source or tests, which Bash may not name."""
    globs = [g for key in ("source", "tests", "e2e") for g in config.toolchain.globs.get(key, [])]
    return sorted({r for r in map(literal_root, globs) if r})


def proxy_scope(config: Config, prepared: Prepared, write: list[str]) -> Scope:
    """Guard scope for a Customer Proxy step in ``prepared``."""
    allow = prepared.kind.allowlist
    if allow is not None and not allow:
        allow = tuple(prepared.delivery.commands)
    return Scope(
        role="customer-proxy",
        repo=config.repo,
        write=[*write, f"{_rel(config, prepared.root)}/**"],
        read=proxy_read_globs(config, prepared),
        cwd=prepared.workdir,
        bash_forbidden=forbidden_roots(config) or ["src"],
        bash_allowed=list(allow) if allow is not None else None,
    )


def os_sandbox_settings(config: Config, prepared: Prepared) -> dict[str, Any]:
    """Claude Code settings: OS sandbox denies reading the repo except allowed paths.

    Not verified end to end in the spike (needs bubblewrap/Seatbelt on the host);
    the hook and glob layers do not depend on it.
    """
    repo = config.repo.resolve()
    allowed = [str(prepared.root.resolve()), str(repo / ".team/stories")]
    allowed.append(str(repo / config.team.docs_dir / "customer"))
    deny_rules = [f"Read(/{repo}/{root}/**)" for root in forbidden_roots(config)]
    return {
        "sandbox": {
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {"denyRead": [str(repo)], "allowRead": allowed},
        },
        "permissions": {"deny": deny_rules},
    }


def mcp_servers(prepared: Prepared) -> dict[str, Any]:
    """Browser MCP for web deliveries; nothing otherwise."""
    return {"playwright": dict(PLAYWRIGHT)} if prepared.kind.browser else {}
