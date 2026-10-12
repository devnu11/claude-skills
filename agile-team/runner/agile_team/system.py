"""The one place the runner touches the operating system (ADR-011, s71).

Other modules write ``from agile_team import system`` and call ``system.name(...)``
at the call site, never ``from agile_team.system import name``: unit tests swap
every function in ``__all__`` for an in-memory fake. Functions are thin: one call.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import stat as stat_bits
import subprocess
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "append_text",
    "async_sleep",
    "connect",
    "copy_tree",
    "cwd",
    "environ",
    "exists",
    "expand_user",
    "glob",
    "hard_link",
    "home",
    "hostname",
    "http_get",
    "is_dir",
    "is_file",
    "kill",
    "killpg",
    "list_dir",
    "listen_http",
    "local_time",
    "make_dirs",
    "monotonic",
    "now",
    "on_signal",
    "open_browser",
    "pgid",
    "pgrp",
    "pid",
    "read_bytes",
    "read_end",
    "read_text",
    "remove",
    "remove_tree",
    "replace",
    "resolve",
    "run",
    "run_shell",
    "sleep",
    "spawn_logged",
    "spawn_piped",
    "stat",
    "wait_event",
    "which",
    "write_text",
]

TimeoutExpired = subprocess.TimeoutExpired
Process = subprocess.Popen
HttpServer = ThreadingHTTPServer


class Completed(NamedTuple):
    """A finished command: exit code, stdout, stderr."""

    code: int
    out: str
    err: str


@dataclass(frozen=True)
class Command:
    """An argv to run without a shell."""

    argv: tuple[str, ...]
    cwd: Path | None = None
    timeout: float | None = None


@dataclass(frozen=True)
class ShellCommand:
    """A shell command line, where it runs, and its environment (None inherits)."""

    text: str
    cwd: Path
    env: Mapping[str, str] | None = None


class HttpReply(NamedTuple):
    """An HTTP response: status, content type (no parameters), body."""

    status: int
    content_type: str
    body: bytes


class FileStat(NamedTuple):
    """What the runner reads from ``stat``: mtime (s and ns), size, permission bits."""

    mtime: float
    mtime_ns: int
    size: int
    mode: int


def read_text(path: Path) -> str:
    """The text of a file."""
    return path.read_text()


def read_bytes(path: Path) -> bytes:
    """The bytes of a file."""
    return path.read_bytes()


def read_end(path: Path, size: int) -> tuple[bytes, int]:
    """The last ``size`` bytes of a file and the file's length."""
    with path.open("rb") as fh:
        end = fh.seek(0, os.SEEK_END)
        fh.seek(max(0, end - size))
        return fh.read(), end


def write_text(path: Path, text: str) -> None:
    """Write a file's text."""
    path.write_text(text)


def append_text(path: Path, text: str) -> None:
    """Append text to a file."""
    with path.open("a") as fh:
        fh.write(text)


def replace(source: Path, target: Path) -> None:
    """Atomically move ``source`` onto ``target``."""
    os.replace(source, target)


def hard_link(link: Path, target: Path) -> None:
    """Make ``link`` a hard link to ``target``; fails if ``link`` exists."""
    link.hardlink_to(target)


def make_dirs(path: Path) -> None:
    """Create a directory and its parents."""
    path.mkdir(parents=True, exist_ok=True)


def remove(path: Path) -> None:
    """Delete a file; a missing file is fine."""
    path.unlink(missing_ok=True)


def remove_tree(path: Path) -> None:
    """Delete a directory and everything under it."""
    shutil.rmtree(path)


def copy_tree(source: Path, target: Path) -> None:
    """Copy a directory tree, keeping symlinks."""
    shutil.copytree(source, target, symlinks=True)


def is_file(path: Path) -> bool:
    """Whether the path is a file."""
    return path.is_file()


def is_dir(path: Path) -> bool:
    """Whether the path is a directory."""
    return path.is_dir()


def exists(path: Path) -> bool:
    """Whether the path exists."""
    return path.exists()


def list_dir(path: Path) -> list[Path]:
    """The direct children of a directory, sorted."""
    return sorted(path.iterdir())


def glob(path: Path, pattern: str) -> list[Path]:
    """The paths under ``path`` matching ``pattern``, sorted."""
    return sorted(path.glob(pattern))


def stat(path: Path) -> FileStat:
    """A file's mtime, size and permission bits."""
    info = os.stat(path)
    return FileStat(info.st_mtime, info.st_mtime_ns, info.st_size, stat_bits.S_IMODE(info.st_mode))


def resolve(path: Path) -> Path:
    """The absolute path with links resolved."""
    return path.resolve()


def expand_user(path: Path) -> Path:
    """The path with a leading ``~`` expanded."""
    return path.expanduser()


def now() -> float:
    """Wall-clock seconds since the epoch."""
    return time.time()


def monotonic() -> float:
    """Monotonic seconds, for measuring intervals."""
    return time.monotonic()


def local_time(fmt: str) -> str:
    """The local time formatted with ``fmt``."""
    return time.strftime(fmt)


def sleep(seconds: float) -> None:
    """Block for ``seconds``."""
    time.sleep(seconds)


def pid() -> int:
    """The runner's process id."""
    return os.getpid()


def kill(pid: int, sig: int) -> None:
    """Send signal ``sig`` to process ``pid``."""
    os.kill(pid, sig)


def pgrp() -> int:
    """The runner's process group id."""
    return os.getpgrp()


def pgid(pid: int) -> int:
    """The process group id of ``pid``."""
    return os.getpgid(pid)


def killpg(pgid: int, sig: int) -> None:
    """Send signal ``sig`` to process group ``pgid``."""
    os.killpg(pgid, sig)


def run(command: Command) -> Completed:
    """Run an argv to the end and capture its output."""
    done = subprocess.run(
        list(command.argv),
        cwd=command.cwd,
        timeout=command.timeout,
        capture_output=True,
        text=True,
        check=False,
    )
    return Completed(done.returncode, done.stdout, done.stderr)


def run_shell(command: ShellCommand) -> int:
    """Run a shell line to the end; return its exit code."""
    return subprocess.run(
        command.text, shell=True, cwd=command.cwd, env=command.env, check=False
    ).returncode


def spawn_piped(command: ShellCommand) -> Process:
    """Start a shell line in a new session, output piped (stderr merged)."""
    return subprocess.Popen(
        command.text,
        shell=True,
        cwd=command.cwd,
        env=command.env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )


def spawn_logged(command: ShellCommand, log: Path) -> Process:
    """Start a shell line in a new session, output written to ``log``."""
    with log.open("wb") as out:
        return subprocess.Popen(
            command.text,
            shell=True,
            cwd=command.cwd,
            env=command.env,
            start_new_session=True,
            stdout=out,
            stderr=subprocess.STDOUT,
        )


def wait_event(event: threading.Event, timeout: float) -> bool:
    """Wait for the event up to ``timeout`` seconds; whether it is set."""
    return event.wait(timeout)


def environ() -> Mapping[str, str]:
    """The process environment."""
    return os.environ


def http_get(url: str, timeout: float) -> HttpReply:
    """GET a URL; raises OSError when it cannot be reached."""
    with urllib.request.urlopen(url, timeout=timeout) as reply:
        return HttpReply(reply.status, reply.headers.get_content_type(), reply.read())


def connect(address: tuple[str, int]) -> None:
    """Open and close a TCP connection; raises OSError when refused."""
    socket.create_connection(address, timeout=1).close()


def hostname() -> str:
    """This machine's host name."""
    return socket.gethostname()


def listen_http(address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> HttpServer:
    """Bind a threaded HTTP server (daemon threads) on ``address``."""
    server = HttpServer(address, handler)
    server.daemon_threads = True
    return server


async def async_sleep(seconds: float) -> None:
    """Wait for ``seconds`` without blocking the event loop."""
    await asyncio.sleep(seconds)


def which(name: str) -> str | None:
    """The path of an executable on ``PATH``, or None."""
    return shutil.which(name)


def home() -> Path:
    """The user's home directory."""
    return Path.home()


def cwd() -> Path:
    """The current working directory."""
    return Path.cwd()


def open_browser(url: str) -> bool:
    """Ask the desktop to open ``url``; whether it did."""
    return webbrowser.open(url)


def on_signal(sig: int, callback: Callable[[], object]) -> None:
    """Call ``callback`` on the running loop when ``sig`` arrives."""
    asyncio.get_running_loop().add_signal_handler(sig, callback)
