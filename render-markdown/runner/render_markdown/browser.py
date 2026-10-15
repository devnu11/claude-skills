"""Open a file in the system's default browser."""

from __future__ import annotations

import sys
from pathlib import Path

from . import system

OPENERS: dict[str, tuple[str, ...]] = {
    "darwin": ("open",),
    "linux": ("xdg-open",),
    "win32": ("cmd", "/c", "start", ""),
}


class BrowserError(Exception):
    """The system has no known way to open a browser, or the opener failed."""


def open_in_browser(page: Path) -> None:
    """Open ``page`` with this platform's opener."""
    opener = OPENERS.get(sys.platform)
    if not opener:
        raise BrowserError(f"no browser opener for {sys.platform}; open {page} by hand")
    done = system.run([*opener, str(page)])
    if done.code != 0:
        raise BrowserError(f"{opener[0]} failed (exit {done.code}): {done.err.strip()}")
