"""Find Chrome and print a page to PDF with it, keeping it out of the user's home."""

from __future__ import annotations

import ntpath
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from . import system

OVERRIDE = "RENDER_MARKDOWN_CHROME"
MIN_VERSION = 112
BUDGET_MS = 15000
CANDIDATES: dict[str, tuple[str, ...]] = {
    "darwin": (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ),
    "linux": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
    "win32": (
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ),
}
FLAGS = (
    "--headless=new",
    "--no-pdf-header-footer",
    "--no-first-run",
    "--disable-crash-reporter",
    "--use-mock-keychain",
    f"--virtual-time-budget={BUDGET_MS}",
)
VERSION = re.compile(r"(\d+)\.\d+\.\d+")
VERSION_FOLDER = re.compile(r"(\d+)\.\d+\.\d+\.\d+")


class ChromeError(Exception):
    """Chrome is missing, too old, or failed to print."""


def find_chrome() -> Path:
    """The first Chrome candidate that exists and is new enough."""
    looked = list(list_candidates())
    for candidate in looked:
        found = search_candidate(candidate)
        if found:
            return require_version(found)
    raise ChromeError(f"Chrome {MIN_VERSION}+ not found; looked for: {', '.join(looked)}")


def list_candidates() -> tuple[str, ...]:
    """The override, then this platform's install paths or command names."""
    override = system.get_environment().get(OVERRIDE)
    return ((override,) if override else ()) + CANDIDATES.get(sys.platform, ())


def search_candidate(candidate: str) -> Path | None:
    """A path that exists, or a command name found on ``PATH``."""
    expanded = ntpath.expandvars(candidate)  # %VAR% and $VAR alike, on every OS
    if os.sep in expanded or "/" in expanded:
        return Path(expanded) if Path(expanded).is_file() else None
    found = shutil.which(expanded)
    return Path(found) if found else None


def require_version(chrome: Path) -> Path:
    """``chrome``, unless it reports a major version below the minimum."""
    major = read_major_version(chrome)
    if major is not None and major < MIN_VERSION:
        raise ChromeError(f"{chrome} is Chrome {major}; {MIN_VERSION} or later is needed")
    return chrome


def read_major_version(chrome: Path) -> int | None:
    """The major version from ``--version``, or from a Windows install's version folder."""
    match = VERSION.search(system.capture([str(chrome), "--version"]) or "")
    if match:
        return int(match[1])
    folders = [VERSION_FOLDER.fullmatch(child.name) for child in list_siblings(chrome)]
    majors = [int(folder[1]) for folder in folders if folder]
    return max(majors) if majors else None


def list_siblings(chrome: Path) -> list[Path]:
    """The folders beside ``chrome`` (Windows keeps one per version there)."""
    return [child for child in chrome.parent.iterdir() if child.is_dir()]


def write_pdf(page: Path, pdf: Path) -> None:
    """Print ``page`` to ``pdf`` with headless Chrome, in a scratch home it removes after."""
    chrome = find_chrome()
    with tempfile.TemporaryDirectory(prefix="render-markdown-") as scratch:
        environment = system.get_environment() | {"HOME": scratch}
        profile = f"--user-data-dir={Path(scratch) / 'profile'}"
        argv = [str(chrome), *FLAGS, profile, f"--print-to-pdf={pdf}", page.as_uri()]
        pdf.unlink(missing_ok=True)
        done = system.run(argv, environment)
    if not pdf.is_file():
        raise ChromeError(f"Chrome made no PDF (exit {done.code}): {done.err.strip()[-400:]}")
