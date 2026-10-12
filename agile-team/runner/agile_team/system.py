"""The one place the runner touches the operating system (ADR-011, s71).

Other modules write ``from agile_team import system`` and call ``system.name(...)``
at the call site, never ``from agile_team.system import name``: unit tests swap
every function in ``__all__`` for an in-memory fake. Functions are thin: one call.
"""

from __future__ import annotations

import os
import shutil
import stat as stat_bits
import time
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "append_text",
    "copy_tree",
    "exists",
    "expand_user",
    "glob",
    "is_dir",
    "is_file",
    "kill",
    "list_dir",
    "local_time",
    "make_dirs",
    "monotonic",
    "now",
    "pid",
    "read_bytes",
    "read_end",
    "read_text",
    "remove",
    "remove_tree",
    "replace",
    "resolve",
    "sleep",
    "stat",
    "write_text",
]


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
