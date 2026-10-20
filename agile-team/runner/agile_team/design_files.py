"""The design's ## Files section (s163 F1)."""

from __future__ import annotations

FILES_HEADING = "## Files"


def parse_files(text: str) -> list[str]:
    """The entries under ``## Files``, up to the next line that starts with ``#``."""
    lines = text.splitlines()
    if FILES_HEADING not in (ln.strip() for ln in lines):
        return []
    body = lines[[ln.strip() for ln in lines].index(FILES_HEADING) + 1 :]
    return [e for ln in _take_section(body) if (e := _read_entry(ln))]


def _take_section(body: list[str]) -> list[str]:
    section: list[str] = []
    for line in body:
        if line.startswith("#"):
            break
        section.append(line)
    return section


def _read_entry(line: str) -> str:
    text = line.strip()
    for bullet in ("- ", "* "):
        if text.startswith(bullet):
            text = text[2:]
    token = text.split(maxsplit=1)[0] if text.strip() else ""
    return token.strip("`")
