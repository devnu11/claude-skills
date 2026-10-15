"""Which paper to lay the page out for: asked for, the printer's, the locale's, or letter."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from enum import StrEnum

from . import system


class Paper(StrEnum):
    """The paper sizes the page can be laid out for."""

    LETTER = "letter"
    A4 = "a4"


PAGE_RULES = {
    Paper.LETTER: "size: letter; margin: 0.7in",
    Paper.A4: "size: A4; margin: 18mm",
}
PRINTER_NAMES = {"letter": Paper.LETTER, "a4": Paper.A4}
LETTER_REGIONS = frozenset({"US", "CA", "MX"})
LINUX_LETTER_HEIGHT = "279"
DEFAULT = Paper.LETTER


def select_paper(requested: Paper | None, printer: str | None) -> Paper:
    """The first of: ``requested``, the printer's default, the locale's, letter."""
    sources: tuple[Callable[[], Paper | None], ...] = (
        lambda: requested,
        lambda: read_printer_paper(printer),
        read_locale_paper,
    )
    return next((paper for paper in (source() for source in sources) if paper), DEFAULT)


def read_printer_paper(printer: str | None) -> Paper | None:
    """The printer's default PageSize from ``lpoptions -l``, when it is letter or A4."""
    out = system.capture(["lpoptions", "-p", printer, "-l"]) if printer else None
    match = re.search(r"^PageSize/[^:]*:.*\*(\S+)", out or "", re.M)
    return PRINTER_NAMES.get(match[1].lower()) if match else None


def read_locale_paper() -> Paper | None:
    """The paper the user's locale implies, where the OS says."""
    readers = {"darwin": read_mac_region_paper, "linux": read_linux_locale_paper}
    reader = readers.get(sys.platform)
    return reader() if reader else None


def read_mac_region_paper() -> Paper | None:
    """Letter for a US, Canadian or Mexican ``AppleLocale`` region, else A4."""
    region = find_region(system.capture(["defaults", "read", "-g", "AppleLocale"]) or "")
    if not region:
        return None
    return Paper.LETTER if region in LETTER_REGIONS else Paper.A4


def find_region(locale: str) -> str | None:
    """The region of a macOS locale (``en_US``, ``zh-Hans_CN``, ``en_US@rg=gbzzzz``)."""
    override = re.search(r"@rg=([a-z]{2})", locale)
    if override:
        return override[1].upper()
    match = re.match(r"[a-z]+(?:-[A-Za-z]+)?_([A-Z]{2})\b", locale.strip())
    return match[1] if match else None


def read_linux_locale_paper() -> Paper | None:
    """Letter or A4 from the height ``LC_PAPER`` gives, in millimetres."""
    match = re.search(r"^height=(\d+)", system.capture(["locale", "-k", "LC_PAPER"]) or "", re.M)
    if not match:
        return None
    return Paper.LETTER if match[1] == LINUX_LETTER_HEIGHT else Paper.A4
